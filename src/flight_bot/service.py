from __future__ import annotations

from datetime import date

from .config import Settings
from .db import Database
from .models import ALERT_ARMED, ALERTED, FlightOffer, WatchSlot
from .providers import GoogleFlightsPlaywrightProvider, ProviderError


HELP = """항공권 감시봇 명령어
/flight add CJJ TPE 2026-09-18 2026-09-20 350000 [nonstop]
/flight list
/flight check 1
/flight target 1 330000
/flight pause 1
/flight resume 1
/flight delete 1
/help

저장 슬롯은 1/2/3 정확히 3개입니다. pause 상태도 슬롯을 차지합니다.
목표가 이하로 새로 진입했을 때만 한 번 알리고, 가격이 다시 목표가 위로 올라가면 재무장됩니다.
"""


class FlightService:
    def __init__(self, settings: Settings, db: Database, provider=None):
        self.settings = settings
        self.db = db
        self.provider = provider or GoogleFlightsPlaywrightProvider(settings)
        self.notifier = None

    def set_notifier(self, notifier) -> None:
        self.notifier = notifier

    @staticmethod
    def format_slot(slot: WatchSlot) -> str:
        state = "ON" if slot.enabled else "PAUSED"
        direct = "직항" if slot.nonstop else "경유/혼합 허용"
        observed = f" / 최근 {slot.last_observed_price:,}{slot.currency}" if slot.last_observed_price else ""
        return (f"#{slot.id} [{state}/{slot.alert_state}] {slot.origin}→{slot.destination} "
                f"{slot.depart_date}~{slot.return_date} / {direct} / 목표 {slot.target_price:,}{slot.currency}{observed}")

    @staticmethod
    def format_offer(slot: WatchSlot, offer: FlightOffer) -> str:
        verified = "✅ Booking 검증가" if offer.price_verified else "🔎 Google 표시가"
        ticket = " / 별도티켓·셀프트랜스퍼" if offer.separate_ticket else ""
        return (
            f"✈️ {slot.origin} → {slot.destination}\n{slot.depart_date} ~ {slot.return_date}\n"
            f"{verified}: {offer.total_price:,}{offer.currency}{ticket}\n목표가: {slot.target_price:,}{slot.currency}\n"
            f"항공사: {offer.airline or '확인 필요'}\n편명: {offer.outbound_flight or '확인 필요'}\n"
            f"위탁수하물: {offer.checked_baggage or '정보 확인 불가'}\nGoogle Flights: {offer.booking_url or '링크 확인 불가'}"
        )

    @staticmethod
    def _valid_date(value: str) -> bool:
        try:
            date.fromisoformat(value)
            return True
        except ValueError:
            return False

    async def check_slot(self, slot_id: int, *, notify_target: bool = False) -> str:
        slot = self.db.get_slot(slot_id)
        if not slot:
            return f"슬롯 #{slot_id}을 찾을 수 없습니다."
        verify_threshold = slot.target_price if slot.alert_state == ALERT_ARMED else None
        run_id = self.db.start_search(slot.id, self.provider.name)
        try:
            offer = await self.provider.search(slot, verify_below_price=verify_threshold)
        except ProviderError as exc:
            self.db.finish_search(run_id, status="failed", message=str(exc)[:500])
            return f"조회 실패: {exc}"
        self.db.save_offer(slot.id, offer)
        self.db.finish_search(run_id, status="success", message=f"price={offer.total_price}; verified={offer.price_verified}")

        effective_price = offer.total_price
        below_target = effective_price <= slot.target_price
        alert_eligible = offer.price_verified or not self.settings.require_verified_alerts
        if below_target:
            if notify_target and slot.alert_state == ALERT_ARMED and alert_eligible and self.notifier:
                await self.notifier.send(slot.owner_platform, slot.owner_id, "🔥 목표가 도달\n" + self.format_offer(slot, offer))
                self.db.record_alert(slot, offer)
                self.db.set_alert_state(slot.id, ALERTED, alerted_price=effective_price)
        elif slot.alert_state == ALERTED:
            self.db.set_alert_state(slot.id, ALERT_ARMED)
        return self.format_offer(slot, offer)

    async def check_all(self) -> None:
        for slot in self.db.list_slots(enabled_only=True):
            await self.check_slot(slot.id, notify_target=True)

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
                return "형식: /flight add CJJ TPE 2026-09-18 2026-09-20 350000 [nonstop]"
            if not (self._valid_date(parts[4]) and self._valid_date(parts[5])):
                return "날짜 형식은 YYYY-MM-DD 입니다."
            try:
                target = int(parts[6].replace(",", ""))
            except ValueError:
                return "목표가는 숫자로 입력해 주세요. 예: 350000"
            nonstop = len(parts) >= 8 and parts[7].lower() in {"nonstop", "direct", "직항"}
            try:
                slot = self.db.add_slot(platform=platform, owner_id=owner_id, origin=parts[2], destination=parts[3],
                                        depart_date=parts[4], return_date=parts[5], target_price=target,
                                        nonstop=nonstop, checked_bag=0)
            except ValueError as exc:
                return str(exc)
            return "감시 슬롯을 추가했습니다.\n" + self.format_slot(slot)

        if action == "list":
            slots = self.db.list_slots()
            return "등록된 슬롯이 없습니다." if not slots else "\n".join(self.format_slot(slot) for slot in slots)

        if action == "target":
            if len(parts) < 4 or not parts[2].isdigit():
                return "형식: /flight target <슬롯번호> <목표가>"
            try:
                price = int(parts[3].replace(",", ""))
                self.db.set_target(int(parts[2]), price)
            except ValueError as exc:
                return str(exc)
            return f"슬롯 #{parts[2]} 목표가를 {price:,}KRW로 변경하고 알림을 재무장했습니다."

        if action in {"check", "pause", "resume", "delete"}:
            if len(parts) < 3 or not parts[2].isdigit():
                return f"형식: /flight {action} <슬롯번호>"
            slot_id = int(parts[2])
            if action == "check":
                return await self.check_slot(slot_id)
            if not self.db.get_slot(slot_id):
                return f"슬롯 #{slot_id}을 찾을 수 없습니다."
            if action == "pause":
                self.db.set_enabled(slot_id, False)
                return f"슬롯 #{slot_id} 감시를 일시정지했습니다. 슬롯은 계속 점유합니다."
            if action == "resume":
                self.db.set_enabled(slot_id, True)
                return f"슬롯 #{slot_id} 감시를 재개했습니다."
            self.db.delete_slot(slot_id)
            return f"슬롯 #{slot_id}을 삭제했습니다. 이 번호는 다음 add에서 다시 사용됩니다."
        return HELP
