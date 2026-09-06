from __future__ import annotations

import asyncio
import inspect
import re
from datetime import date

from .config import Settings
from .db import Database, StaleSlotError
from .models import ALERT_ARMED, ALERT_SENDING, ALERTED, FlightOffer, WatchSlot
from .providers import GoogleFlightsPlaywrightProvider, ProviderError


HELP = """항공권 감시봇 명령어
/flight add CJJ TPE 2026-09-18 2026-09-20 350000
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
/help

저장 슬롯은 1/2/3 정확히 3개입니다. pause 상태도 슬롯을 차지합니다.
알림 후보는 Google Flights 왕복 검색의 직항만 사용하며 경유편은 제외합니다.
목표가 이하로 새로 진입했을 때만 한 번 알리고, 가격이 다시 목표가 위로 올라가면 재무장됩니다.
"""

_AIRPORT_RE = re.compile(r"^[A-Z]{3}$")


class FlightService:
    def __init__(self, settings: Settings, db: Database, provider=None):
        self.settings = settings
        self.db = db
        self.provider = provider or GoogleFlightsPlaywrightProvider(settings)
        self.notifier = None
        # One coordinator lock covers the whole slot transaction *and* slot
        # mutations. A search can therefore never finish into a deleted/reused
        # slot in this process.
        self._operation_lock = asyncio.Lock()
        # This boolean is set before the first await in check_all(), making the
        # duplicate-scan claim atomic within one asyncio event loop.
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
            f"#{slot.id} [{state}/{slot.alert_state}] {slot.origin}→{slot.destination} "
            f"{slot.depart_date}~{slot.return_date} / 직항만 / 목표 {slot.target_price:,}{slot.currency}{observed}"
        )

    def format_offer(self, slot: WatchSlot, offer: FlightOffer) -> str:
        """Format one result-page alert with exactly one user-facing URL."""
        rows = list(offer.display_offers or [])[: self.settings.alert_max_offers]
        if not rows:
            rows = [
                {
                    "price": offer.observed_price,
                    "airline": offer.airline,
                    "flight_numbers": offer.outbound_flight,
                    "times": [],
                    "nonstop": offer.nonstop,
                }
            ]

        price_lines: list[str] = []
        for index, row in enumerate(rows, start=1):
            try:
                price = int(row.get("price"))
            except (TypeError, ValueError, AttributeError):
                continue
            details: list[str] = []
            airline = str(row.get("airline") or "").strip()
            if airline:
                details.append(airline)
            times = row.get("times") or []
            if isinstance(times, list) and len(times) >= 2:
                details.append(f"{times[0]} → {times[1]}")
            flight_numbers = str(row.get("flight_numbers") or "").strip()
            if flight_numbers:
                details.append(flight_numbers)
            suffix = f" · {' / '.join(details)}" if details else ""
            price_lines.append(f"{index}. {price:,}{offer.currency}{suffix}")

        if not price_lines:
            price_lines.append(f"1. {offer.observed_price:,}{offer.currency}")

        result_url = offer.google_flights_url or "링크 확인 불가"
        return (
            f"✈️ {slot.origin} → {slot.destination} 왕복\n"
            f"{slot.depart_date} ~ {slot.return_date}\n"
            f"Google Flights 직항 왕복가\n"
            + "\n".join(price_lines)
            + f"\n목표가: {slot.target_price:,}{slot.currency}"
            + f"\n위탁수하물: {offer.checked_baggage or '정보 확인 불가'}"
            + f"\nGoogle Flights 검색결과: {result_url}"
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
    def _same_owner(slot: WatchSlot, platform: str, owner_id: str) -> bool:
        return slot.owner_platform == platform and slot.owner_id == owner_id

    async def close(self) -> None:
        close = getattr(self.provider, "close", None)
        if close is None:
            return
        result = close()
        if inspect.isawaitable(result):
            await result

    async def check_slot(self, slot_id: int, *, notify_target: bool = False) -> str:
        async with self._operation_lock:
            return await self._check_slot_locked(slot_id, notify_target=notify_target)

    async def _check_slot_locked(self, slot_id: int, *, notify_target: bool) -> str:
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

        effective_price = offer.verified_price if offer.price_verified and offer.verified_price is not None else offer.observed_price
        below_target = effective_price <= slot.target_price
        alert_eligible = provider_alert_capable and (
            offer.price_verified or not self.settings.require_verified_alerts
        )

        if below_target:
            if (
                notify_target
                and slot.alert_state == ALERT_ARMED
                and alert_eligible
                and self.notifier
            ):
                # Mark SENDING before the external side effect. If the process
                # dies after delivery but before the DB finalization, restart
                # will not resend the same below-target interval. This is an
                # intentional at-most-once crash policy.
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
                except Exception:
                    # Do not re-arm after the external send succeeded. Leaving
                    # SENDING is safer than risking a duplicate after restart.
                    return self.format_offer(slot, offer) + "\n알림은 전송됐지만 상태 저장을 확인하지 못했습니다. 중복 방지를 위해 SENDING 상태를 유지합니다."
        elif slot.alert_state in {ALERTED, ALERT_SENDING}:
            self.db.set_alert_state(slot.id, ALERT_ARMED)
        return self.format_offer(slot, offer)

    async def check_all(self) -> bool:
        if self._scan_active:
            return False
        self._scan_active = True
        try:
            for slot in self.db.list_slots(enabled_only=True):
                await self.check_slot(slot.id, notify_target=True)
            return True
        finally:
            self._scan_active = False

    async def command(self, platform: str, owner_id: str, text: str) -> str:
        text = (text or "").strip()
        if text in {"/help", "help", "도움말", "시작", "/start"}:
            return HELP
        if not text.startswith("/flight"):
            return "현재는 명시적 /flight 명령을 지원합니다.\n\n" + HELP
        parts = text.split()
        if len(parts) < 2:
            return HELP
        action = parts[1].lower()

        if action == "add":
            if len(parts) < 7:
                return "형식: /flight add CJJ TPE 2026-09-18 2026-09-20 350000"
            origin = parts[2].upper()
            destination = parts[3].upper()
            if not (self._valid_airport(origin) and self._valid_airport(destination)):
                return "공항 코드는 영문 3자리 IATA 코드로 입력해 주세요. 예: CJJ TPE"
            if origin == destination:
                return "출발지와 도착지는 서로 달라야 합니다."
            if not (self._valid_date(parts[4]) and self._valid_date(parts[5])):
                return "날짜 형식은 YYYY-MM-DD 입니다."
            if date.fromisoformat(parts[5]) < date.fromisoformat(parts[4]):
                return "귀국일은 출발일보다 빠를 수 없습니다."
            try:
                target = int(parts[6].replace(",", ""))
            except ValueError:
                return "목표가는 숫자로 입력해 주세요. 예: 350000"
            async with self._operation_lock:
                try:
                    slot = self.db.add_slot(
                        platform=platform,
                        owner_id=owner_id,
                        origin=origin,
                        destination=destination,
                        depart_date=parts[4],
                        return_date=parts[5],
                        target_price=target,
                        nonstop=True,
                        checked_bag=0,
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
            return f"슬롯 #{slot_id} 목표가를 {price:,}KRW로 변경하고 알림을 재무장했습니다."

        if action in {"check", "pause", "resume", "delete"}:
            if len(parts) < 3 or not parts[2].isdigit():
                return f"형식: /flight {action} <슬롯번호>"
            slot_id = int(parts[2])
            if action == "check":
                async with self._operation_lock:
                    slot = self.db.get_owned_slot(slot_id, platform, owner_id)
                    if not slot:
                        return f"슬롯 #{slot_id}을 찾을 수 없거나 이 대화에서 만든 슬롯이 아닙니다."
                    return await self._check_slot_locked(slot_id, notify_target=False)

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
