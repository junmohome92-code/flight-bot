from __future__ import annotations

from dataclasses import asdict

from .config import Settings
from .db import Database
from .models import FlightOffer, WatchSlot
from .providers import ProviderError, SerpApiProvider


HELP = """항공권 감시봇 명령어
/flight add CJJ TPE 2026-10-21 2026-10-25 [nonstop]
/flight list
/flight check 1
/flight pause 1
/flight resume 1
/flight delete 1
/help

예: /flight add CJJ TPE 2026-10-21 2026-10-25 nonstop
"""


class FlightService:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db
        self.provider = SerpApiProvider(settings)
        self.notifier = None

    def set_notifier(self, notifier) -> None:
        self.notifier = notifier

    @staticmethod
    def format_slot(slot: WatchSlot) -> str:
        state = "ON" if slot.enabled else "PAUSED"
        direct = "직항" if slot.nonstop else "경유 허용"
        price = f" / 최근 검증가 {slot.last_verified_price:,}{slot.currency}" if slot.last_verified_price else ""
        return f"#{slot.id} [{state}] {slot.origin}→{slot.destination} {slot.depart_date}~{slot.return_date} / {direct}{price}"

    @staticmethod
    def format_offer(slot: WatchSlot, offer: FlightOffer) -> str:
        verified = "✅ 검증 가격" if offer.price_verified else "⚠️ 미검증"
        return (
            f"✈️ {slot.origin} → {slot.destination}\n"
            f"{slot.depart_date} ~ {slot.return_date}\n"
            f"{verified}: {offer.total_price:,}{offer.currency}\n"
            f"항공사: {offer.airline or '확인 필요'}\n"
            f"편명: {offer.outbound_flight or '확인 필요'}\n"
            f"판매처: {offer.booking_provider or '확인 필요'}\n"
            f"기내수하물: {offer.carry_on or '정보 확인 필요'}\n"
            f"위탁수하물: {offer.checked_baggage or '정보 확인 필요'}\n"
            f"구매링크: {offer.booking_url or 'Booking Options에서 확인'}"
        )

    async def check_slot(self, slot_id: int, *, notify_drop: bool = False) -> str:
        slot = self.db.get_slot(slot_id)
        if not slot:
            return f"슬롯 #{slot_id}을 찾을 수 없습니다."
        previous = slot.last_verified_price
        try:
            offer = await self.provider.search(slot)
        except ProviderError as exc:
            return f"조회 실패: {exc}"
        self.db.save_offer(slot.id, offer)
        text = self.format_offer(slot, offer)
        if notify_drop and offer.price_verified and self.notifier and (previous is None or offer.total_price < previous):
            prefix = "🔥 새 최저가 발견\n" if previous is not None else "🔔 최초 검증 가격\n"
            await self.notifier.send(slot.owner_platform, slot.owner_id, prefix + text)
            self.db.record_alert(slot, offer)
        return text

    async def check_all(self) -> None:
        for slot in self.db.list_slots(enabled_only=True):
            await self.check_slot(slot.id, notify_drop=True)

    async def command(self, platform: str, owner_id: str, text: str) -> str:
        text = (text or "").strip()
        if text in {"/help", "help", "도움말", "시작", "/start"}:
            return HELP
        if not text.startswith("/flight"):
            return "현재는 명시적 /flight 명령을 지원합니다. 자연어 AI 파서는 다음 단계에서 연결할 수 있습니다.\n\n" + HELP

        parts = text.split()
        if len(parts) < 2:
            return HELP
        action = parts[1].lower()

        if action == "add":
            if len(parts) < 6:
                return "형식: /flight add CJJ TPE 2026-10-21 2026-10-25 [nonstop]"
            nonstop = len(parts) >= 7 and parts[6].lower() in {"nonstop", "direct", "직항"}
            try:
                slot = self.db.add_slot(
                    platform=platform, owner_id=owner_id,
                    origin=parts[2], destination=parts[3], depart_date=parts[4], return_date=parts[5],
                    nonstop=nonstop, checked_bag=0, max_slots=self.settings.max_slots,
                )
            except ValueError as exc:
                return str(exc)
            return "감시 슬롯을 추가했습니다.\n" + self.format_slot(slot)

        if action == "list":
            slots = self.db.list_slots()
            return "등록된 슬롯이 없습니다." if not slots else "\n".join(self.format_slot(s) for s in slots)

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
                return f"슬롯 #{slot_id} 감시를 일시정지했습니다."
            if action == "resume":
                self.db.set_enabled(slot_id, True)
                return f"슬롯 #{slot_id} 감시를 재개했습니다."
            self.db.delete_slot(slot_id)
            return f"슬롯 #{slot_id}을 삭제했습니다."

        return HELP
