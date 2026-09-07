from __future__ import annotations

import asyncio
import inspect
import re
from datetime import date, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from .config import Settings
from .db import Database, StaleSlotError
from .locations import display_location, resolve_code_token, suggest_locations
from .models import ALERT_ARMED, ALERT_SENDING, ALERTED, FlightOffer, WatchSlot
from .providers import NaverFlightsSSEProvider, ProviderError


HELP = """✈️ 항공권 감시봇 도움말

버튼 메뉴에서 다음 기능을 사용할 수 있습니다.
• ➕ 감시 등록: 최대 20개 슬롯
• 🔎 바로 검색: 슬롯 등록 없이 1회 검색
• 📋 내 슬롯: 슬롯별 지금 검색/목표가/일시정지/삭제

공항 입력은 코드뿐 아니라 이름도 지원합니다.
예: 청주, 인천, 도쿄, 서울, CJJ, TYO
도쿄/서울/오사카처럼 공항이 여러 개인 도시는
'도시 전체' 또는 개별 공항을 버튼으로 선택할 수 있습니다.
잘못된 IATA 코드는 저장하지 않고 비슷한 실제 공항을 추천합니다.

명령어도 계속 지원합니다.
/flight search CJJ TPE 2026-09-18 2026-09-20
/flight search SEL TYO 2026-09-22 2026-09-24
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
/help 또는 /?

검색 조건: 성인 1명 / 이코노미 / 직항 / 왕복
가격 소스: Naver Flights SSE API
조회 결과: 가격순 최대 TOP 5 왕복 조합
정기 검색: 기본 2시간 주기
아침 정기 보고: 사용자당 요약 메시지 1개
목표가 도달 알림: 목표가 설정당 최초 1회
"""

# Kept for backward-compatible tests and basic syntax checks. Actual save/search
# validation additionally checks the bundled real IATA catalogue.
_AIRPORT_RE = re.compile(r"^[A-Z]{3}$")


class FlightService:
    def __init__(self, settings: Settings, db: Database, provider=None):
        self.settings = settings
        self.db = db
        self.provider = provider or NaverFlightsSSEProvider(settings)
        self.notifier = None
        self._operation_lock = asyncio.Lock()
        self._scan_active = False

    def set_notifier(self, notifier) -> None:
        self.notifier = notifier

    @property
    def scan_active(self) -> bool:
        return self._scan_active

    @staticmethod
    def format_slot(slot: WatchSlot) -> str:
        state = "ON" if slot.enabled else "PAUSED"
        observed = f" / 최근 {slot.last_observed_price:,}{slot.currency}" if slot.last_observed_price else ""
        return (
            f"#{slot.id} [{state}/{slot.alert_state}] "
            f"{display_location(slot.origin)}→{display_location(slot.destination)} "
            f"{slot.depart_date}~{slot.return_date} / 직항 왕복 / 목표 {slot.target_price:,}{slot.currency}{observed}"
        )

    def format_offer(self, slot: WatchSlot, offer: FlightOffer, *, include_target: bool = True) -> str:
        raw_rows = list(offer.display_offers or [])
        rows: list[dict] = []
        seen_rows: set[tuple] = set()
        for row in raw_rows:
            try:
                price = int(row.get("price"))
            except (TypeError, ValueError, AttributeError):
                continue
            times_value = row.get("times") or []
            times = tuple(str(value).strip() for value in times_value) if isinstance(times_value, list) else ()
            key = (
                price,
                str(row.get("outbound_flight") or ""),
                str(row.get("return_flight") or ""),
                times,
            )
            if key in seen_rows:
                continue
            seen_rows.add(key)
            rows.append(row)
            if len(rows) >= self.settings.alert_max_offers:
                break

        if not rows:
            rows = [
                {
                    "price": offer.observed_price,
                    "outbound_airline": offer.airline,
                    "return_airline": offer.airline,
                    "outbound_flight": offer.outbound_flight,
                    "return_flight": offer.inbound_flight,
                    "times": [],
                }
            ]

        price_lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            try:
                price = int(row.get("price"))
            except (TypeError, ValueError, AttributeError):
                continue
            times = row.get("times") or []
            out_airline = str(row.get("outbound_airline") or row.get("outbound_airline_code") or "").strip()
            ret_airline = str(row.get("return_airline") or row.get("return_airline_code") or "").strip()
            out_flight = str(row.get("outbound_flight") or "").strip()
            ret_flight = str(row.get("return_flight") or "").strip()

            price_lines.append(f"{index}. {price:,}{offer.currency}")
            if isinstance(times, list) and len(times) >= 4:
                out_label = " ".join(value for value in (out_airline, out_flight) if value) or "가는편"
                ret_label = " ".join(value for value in (ret_airline, ret_flight) if value) or "오는편"
                out_dep = str(row.get("outbound_departure_airport") or "").strip()
                out_arr = str(row.get("outbound_arrival_airport") or "").strip()
                ret_dep = str(row.get("return_departure_airport") or "").strip()
                ret_arr = str(row.get("return_arrival_airport") or "").strip()
                out_times = (
                    f"{out_dep} {times[0]} → {out_arr} {times[1]}"
                    if out_dep and out_arr
                    else f"{times[0]} → {times[1]}"
                )
                ret_times = (
                    f"{ret_dep} {times[2]} → {ret_arr} {times[3]}"
                    if ret_dep and ret_arr
                    else f"{times[2]} → {times[3]}"
                )
                price_lines.append(f"   가는편: {out_label} · {out_times}")
                price_lines.append(f"   오는편: {ret_label} · {ret_times}")
            else:
                details = " / ".join(value for value in (out_airline, out_flight, ret_airline, ret_flight) if value)
                if details:
                    price_lines.append(f"   {details}")

        if not price_lines:
            price_lines.append(f"1. {offer.observed_price:,}{offer.currency}")

        result_url = offer.result_url or offer.booking_url or "링크 확인 불가"
        target_line = f"\n목표가: {slot.target_price:,}{slot.currency}" if include_target else ""
        return (
            f"✈️ {display_location(slot.origin)} → {display_location(slot.destination)} 왕복\n"
            f"{slot.depart_date} ~ {slot.return_date}\n"
            f"Naver Flights 직항 왕복가 TOP {min(self.settings.alert_max_offers, len(rows))}\n"
            + "\n".join(price_lines)
            + target_line
            + f"\n위탁수하물: {offer.checked_baggage or '정보 확인 불가'}"
            + f"\nNaver Flights 검색결과: {result_url}"
        )

    @staticmethod
    def _valid_date(value: str) -> bool:
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False

    @staticmethod
    def _valid_airport(value: str) -> bool:
        return bool(_AIRPORT_RE.fullmatch((value or "").strip().upper()))

    @staticmethod
    def _unknown_location_message(value: str) -> str:
        suggestions = suggest_locations(value, limit=4)
        if suggestions:
            labels = ", ".join(f"{option.name} {option.code}" for option in suggestions)
            return f"'{value}' 위치 코드를 찾을 수 없습니다. 비슷한 실제 공항/도시: {labels}"
        return f"'{value}' 위치 코드를 찾을 수 없습니다. 실제 IATA 공항/도시 코드를 확인해 주세요."

    def validate_trip(self, origin: str, destination: str, depart_date: str, return_date: str) -> str | None:
        origin = origin.strip().upper()
        destination = destination.strip().upper()
        if not self._valid_airport(origin):
            return self._unknown_location_message(origin)
        if not self._valid_airport(destination):
            return self._unknown_location_message(destination)
        if resolve_code_token(origin) is None:
            return self._unknown_location_message(origin)
        if resolve_code_token(destination) is None:
            return self._unknown_location_message(destination)
        if origin == destination:
            return "출발지와 도착지는 서로 달라야 합니다."
        if not (self._valid_date(depart_date) and self._valid_date(return_date)):
            return "날짜 형식은 YYYY-MM-DD 입니다."
        if date.fromisoformat(return_date) < date.fromisoformat(depart_date):
            return "귀국일은 출발일보다 빠를 수 없습니다."
        return None

    async def add_watch(
        self,
        platform: str,
        owner_id: str,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
        target_price: int,
    ) -> WatchSlot:
        error = self.validate_trip(origin, destination, depart_date, return_date)
        if error:
            raise ValueError(error)
        if int(target_price) <= 0:
            raise ValueError("목표가는 0원보다 커야 합니다.")
        async with self._operation_lock:
            return self.db.add_slot(
                platform=platform,
                owner_id=owner_id,
                origin=origin.strip().upper(),
                destination=destination.strip().upper(),
                depart_date=depart_date,
                return_date=return_date,
                target_price=int(target_price),
                nonstop=True,
                checked_bag=0,
            )

    async def search_now(
        self,
        origin: str,
        destination: str,
        depart_date: str,
        return_date: str,
    ) -> str:
        error = self.validate_trip(origin, destination, depart_date, return_date)
        if error:
            return error
        slot = WatchSlot(
            id=0,
            owner_platform="adhoc",
            owner_id=uuid4().hex,
            origin=origin.strip().upper(),
            destination=destination.strip().upper(),
            depart_date=depart_date,
            return_date=return_date,
            nonstop=True,
            checked_bag=0,
            enabled=False,
            target_price=0,
        )
        try:
            offer = await self.provider.search(slot)
        except ProviderError as exc:
            return f"조회 실패: {exc}"
        except Exception as exc:
            return f"조회 실패: 예상하지 못한 오류 ({type(exc).__name__})"
        return self.format_offer(slot, offer, include_target=False)

    async def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def check_slot(
        self,
        slot_id: int,
        *,
        notify_target: bool = False,
        notify_daily_summary: bool = False,
    ) -> str:
        async with self._operation_lock:
            return await self._check_slot_locked(
                slot_id,
                notify_target=notify_target,
                notify_daily_summary=notify_daily_summary,
            )

    async def _check_slot_locked(
        self,
        slot_id: int,
        *,
        notify_target: bool,
        notify_daily_summary: bool = False,
    ) -> str:
        slot = self.db.get_slot(slot_id)
        if not slot:
            return f"슬롯 #{slot_id}을 찾을 수 없습니다."

        provider_alert_capable = bool(getattr(self.provider, "accepted_for_alerts", True))
        verify_threshold = slot.target_price if slot.alert_state == ALERT_ARMED else None
        run_id = self.db.start_search(slot.id, self.provider.name)
        try:
            offer = await self.provider.search(slot, verify_below_price=verify_threshold)
        except ProviderError as exc:
            self.db.finish_search(run_id, status="failed", message=str(exc)[:500])
            return f"조회 실패: {exc}"
        except Exception as exc:
            self.db.finish_search(run_id, status="failed", message=f"unexpected: {exc}"[:500])
            return f"조회 실패: 예상하지 못한 오류 ({type(exc).__name__})"

        try:
            self.db.save_offer(
                slot.id,
                offer,
                expected_generation=slot.generation,
                expected_revision=slot.revision,
            )
        except StaleSlotError as exc:
            self.db.finish_search(run_id, status="stale", message=str(exc)[:500])
            return "조회 중 슬롯 설정이 변경되어 이전 검색 결과를 폐기했습니다."

        self.db.finish_search(
            run_id,
            status="success",
            message=(
                f"observed={offer.observed_price}; verified={offer.verified_price}; "
                f"verification_status={offer.verification_status}"
            )[:500],
        )

        effective_price = (
            offer.verified_price
            if offer.price_verified and offer.verified_price is not None
            else offer.observed_price
        )
        below_target = effective_price <= slot.target_price
        alert_eligible = provider_alert_capable and (
            offer.price_verified or not self.settings.require_verified_alerts
        )
        target_alert_sent = False

        if (
            below_target
            and notify_target
            and slot.alert_state == ALERT_ARMED
            and alert_eligible
            and self.notifier
        ):
            try:
                self.db.set_alert_state(slot.id, ALERT_SENDING, alerted_price=effective_price)
                pending_slot = self.db.get_slot(slot.id) or slot
                alert_id = self.db.begin_alert(pending_slot, offer)
            except Exception as exc:
                try:
                    self.db.set_alert_state(slot.id, ALERT_ARMED)
                except Exception:
                    pass
                return self.format_offer(slot, offer) + f"\n알림 준비 실패: {type(exc).__name__}"

            try:
                await self.notifier.send(
                    slot.owner_platform,
                    slot.owner_id,
                    "🔥 목표가 도달\n" + self.format_offer(slot, offer),
                )
            except Exception as exc:
                self.db.finish_alert(alert_id, state="FAILED", error=f"{type(exc).__name__}: {exc}"[:500])
                self.db.set_alert_state(slot.id, ALERT_ARMED)
                return self.format_offer(slot, offer) + f"\n알림 전송 실패: {type(exc).__name__}"

            try:
                self.db.finish_alert(alert_id, state="SENT")
                self.db.set_alert_state(slot.id, ALERTED, alerted_price=effective_price)
                target_alert_sent = True
            except Exception:
                return (
                    self.format_offer(slot, offer)
                    + "\n알림은 전송됐지만 상태 저장을 확인하지 못했습니다. 중복 방지를 위해 SENDING 상태를 유지합니다."
                )

        # Kept for the explicit per-slot admin endpoint. Full daily scans use
        # the aggregate path in check_all and therefore never emit N messages.
        if notify_daily_summary and self.notifier and not target_alert_sent:
            try:
                await self.notifier.send(
                    slot.owner_platform,
                    slot.owner_id,
                    "📊 슬롯 정기 가격 확인\n" + self.format_offer(slot, offer),
                )
            except Exception as exc:
                return self.format_offer(slot, offer) + f"\n정기 알림 전송 실패: {type(exc).__name__}"

        return self.format_offer(slot, offer)

    def format_daily_summary(self, entries: list[dict]) -> str:
        now = datetime.now(ZoneInfo(self.settings.timezone))
        lines = [
            f"📊 {now:%m/%d} 항공권 정기 보고",
            f"활성 슬롯 {len(entries)}개 · 최저 왕복가 기준",
            "",
        ]
        for entry in entries:
            slot: WatchSlot = entry["slot"]
            current = entry.get("current")
            previous = entry.get("previous")
            failed = bool(entry.get("failed"))
            route = f"{slot.origin}→{slot.destination}"
            if failed or current is None:
                lines.append(f"#{slot.id} {route}  ⚠ 조회 실패")
                continue
            current = int(current)
            if previous is None:
                change = "신규"
            else:
                delta = current - int(previous)
                if delta < 0:
                    change = f"▼{abs(delta):,}"
                elif delta > 0:
                    change = f"▲{delta:,}"
                else:
                    change = "─"
            target = " 🎯" if current <= slot.target_price else ""
            lines.append(f"#{slot.id} {route}  {current:,}원  {change}{target}")
        lines.extend(["", "아래 상세 버튼을 누르면 해당 슬롯을 즉시 다시 검색합니다."])
        return "\n".join(lines)

    async def _send_daily_summaries(self, grouped: dict[tuple[str, str], list[dict]]) -> None:
        if not self.notifier:
            return
        for (platform, owner_id), entries in grouped.items():
            if not entries:
                continue
            text = self.format_daily_summary(entries)
            slot_ids = [int(entry["slot"].id) for entry in entries]
            try:
                send_summary = getattr(self.notifier, "send_summary", None)
                if send_summary:
                    await send_summary(platform, owner_id, text, slot_ids)
                else:
                    await self.notifier.send(platform, owner_id, text)
            except Exception:
                # A summary delivery failure must not abort the scheduler or
                # prevent another owner's summary from being sent.
                continue

    async def check_all(
        self,
        *,
        notify_target: bool = True,
        notify_daily_summary: bool = False,
    ) -> bool:
        if self._scan_active:
            return False
        self._scan_active = True
        grouped: dict[tuple[str, str], list[dict]] = {}
        try:
            for slot in self.db.list_slots(enabled_only=True):
                previous = slot.last_observed_price
                result = await self.check_slot(
                    slot.id,
                    notify_target=notify_target,
                    # Daily all-slot reports are aggregated below.
                    notify_daily_summary=False,
                )
                updated = self.db.get_slot(slot.id) or slot
                failed = result.startswith("조회 실패:") or updated.last_observed_price is None
                grouped.setdefault((slot.owner_platform, slot.owner_id), []).append(
                    {
                        "slot": updated,
                        "previous": previous,
                        "current": updated.last_observed_price,
                        "failed": failed,
                    }
                )
            if notify_daily_summary:
                await self._send_daily_summaries(grouped)
            return True
        finally:
            self._scan_active = False

    async def command(self, platform: str, owner_id: str, text: str) -> str:
        text = (text or "").strip()
        if text in {"/help", "/?", "help", "도움말", "시작", "/start"}:
            return HELP
        if not text.startswith("/flight"):
            return HELP
        parts = text.split()
        if len(parts) < 2:
            return HELP
        action = parts[1].lower()

        if action == "search":
            if len(parts) < 6:
                return "형식: /flight search CJJ TPE 2026-09-18 2026-09-20"
            return await self.search_now(parts[2], parts[3], parts[4], parts[5])

        if action == "add":
            if len(parts) < 7:
                return "형식: /flight add CJJ TPE 2026-09-18 2026-09-20 350000"
            try:
                target = int(parts[6].replace(",", ""))
            except ValueError:
                return "목표가는 숫자로 입력해 주세요. 예: 350000"
            try:
                slot = await self.add_watch(
                    platform,
                    owner_id,
                    parts[2],
                    parts[3],
                    parts[4],
                    parts[5],
                    target,
                )
            except ValueError as exc:
                return str(exc)
            return "감시 슬롯을 추가했습니다.\n" + self.format_slot(slot)

        if action == "list":
            slots = self.db.list_slots(owner_platform=platform, owner_id=owner_id)
            return "등록된 슬롯이 없습니다." if not slots else "\n".join(self.format_slot(slot) for slot in slots)

        if action == "target":
            if len(parts) < 4 or not parts[2].isdigit():
                return "형식: /flight target <슬롯번호> <목표가>"
            slot_id = int(parts[2])
            try:
                price = int(parts[3].replace(",", ""))
            except ValueError:
                return "목표가는 숫자로 입력해 주세요."
            async with self._operation_lock:
                slot = self.db.get_owned_slot(slot_id, platform, owner_id)
                if not slot:
                    return f"슬롯 #{slot_id}을 찾을 수 없거나 이 대화에서 만든 슬롯이 아닙니다."
                try:
                    self.db.set_target(slot_id, price)
                except ValueError as exc:
                    return str(exc)
            return f"슬롯 #{slot_id} 목표가를 {price:,}KRW로 변경했습니다. 목표가 도달 알림 1회를 다시 활성화했습니다."

        if action in {"check", "pause", "resume", "delete"}:
            if len(parts) < 3 or not parts[2].isdigit():
                return f"형식: /flight {action} <슬롯번호>"
            slot_id = int(parts[2])
            if action == "check":
                async with self._operation_lock:
                    slot = self.db.get_owned_slot(slot_id, platform, owner_id)
                    if not slot:
                        return f"슬롯 #{slot_id}을 찾을 수 없거나 이 대화에서 만든 슬롯이 아닙니다."
                    return await self._check_slot_locked(
                        slot_id,
                        notify_target=False,
                        notify_daily_summary=False,
                    )

            async with self._operation_lock:
                slot = self.db.get_owned_slot(slot_id, platform, owner_id)
                if not slot:
                    return f"슬롯 #{slot_id}을 찾을 수 없거나 이 대화에서 만든 슬롯이 아닙니다."
                if action == "pause":
                    self.db.set_enabled(slot_id, False)
                    return f"슬롯 #{slot_id} 감시를 일시정지했습니다. 슬롯은 계속 점유합니다."
                if action == "resume":
                    self.db.set_enabled(slot_id, True)
                    return f"슬롯 #{slot_id} 감시를 재개했습니다."
                self.db.delete_slot(slot_id)
                return f"슬롯 #{slot_id}을 삭제했습니다. 이 번호는 다음 add에서 다시 사용됩니다."
        return HELP
