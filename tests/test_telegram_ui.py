from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.service import HELP, FlightService
from flight_bot.telegram_ui import MAIN_KEYBOARD, slot_detail_keyboard, slot_list_keyboard


def _button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def _callback_values(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


def test_main_keyboard_exposes_core_user_actions():
    texts = [button.text for row in MAIN_KEYBOARD.keyboard for button in row]
    assert "➕ 감시 등록" in texts
    assert "🔎 바로 검색" in texts
    assert "📋 내 슬롯" in texts
    assert "❓ 도움말" in texts
    assert "/?" in HELP


def test_slot_list_and_detail_have_direct_management_buttons(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    slot = db.add_slot(
        platform="telegram",
        owner_id="123",
        origin="CJJ",
        destination="TPE",
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=True,
        checked_bag=0,
    )
    service = FlightService(Settings(_env_file=None), db, provider=object())

    listing = slot_list_keyboard(service, "telegram", "123")
    detail = slot_detail_keyboard(slot.id, slot.enabled)

    assert f"slot:{slot.id}" in _callback_values(listing)
    assert "➕ 새 감시" in _button_texts(listing)
    assert "🔎 바로 검색" in _button_texts(listing)
    assert f"slotcheck:{slot.id}" in _callback_values(detail)
    assert f"slottarget:{slot.id}" in _callback_values(detail)
    assert f"slottoggle:{slot.id}" in _callback_values(detail)
    assert f"slotdeleteconfirm:{slot.id}" in _callback_values(detail)
