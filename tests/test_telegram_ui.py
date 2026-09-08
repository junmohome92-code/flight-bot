from types import SimpleNamespace

from telegram import ForceReply

from flight_bot.config import Settings
from flight_bot.db import Database
from flight_bot.service import HELP, FlightService
from flight_bot.telegram_ui import (
    MAIN_KEYBOARD,
    Flow,
    _flow_prompt,
    _get_flow,
    _put_flow,
    slot_detail_keyboard,
    slot_list_keyboard,
)


def _button_texts(markup):
    return [button.text for row in markup.inline_keyboard for button in row]


def _callback_values(markup):
    return [button.callback_data for row in markup.inline_keyboard for button in row if button.callback_data]


def _add(db, owner_id, origin="CJJ", destination="TPE"):
    return db.add_slot(
        platform="telegram",
        owner_id=owner_id,
        origin=origin,
        destination=destination,
        depart_date="2026-09-18",
        return_date="2026-09-20",
        target_price=350000,
        nonstop=True,
        checked_bag=0,
    )


def test_main_keyboard_and_help_are_button_first_and_compact():
    texts = [button.text for row in MAIN_KEYBOARD.keyboard for button in row]
    assert "➕ 감시 등록" in texts
    assert "🔎 바로 검색" in texts
    assert "📋 내 슬롯" in texts
    assert "❓ 도움말" in texts
    assert "한글 / 영어 / IATA" in HELP
    assert "채팅방마다" in HELP
    assert "/flight search" not in HELP
    assert "/flight add" not in HELP


def test_location_prompt_does_not_imply_only_four_fixed_routes():
    text, markup = _flow_prompt(Flow(mode="add", step="origin", data={}))
    assert "한글 · 영어 · IATA" in text
    assert "히로시마" in text
    assert isinstance(markup, ForceReply)
    assert "청주 CJJ" not in text


def test_flow_state_is_isolated_by_chat_for_same_user_context():
    context = SimpleNamespace(user_data={})
    _put_flow(context, "group-a", Flow(mode="add", step="origin", data={}))
    _put_flow(context, "group-b", Flow(mode="search", step="destination", data={"origin": "CJJ"}))

    assert _get_flow(context, "group-a").mode == "add"
    assert _get_flow(context, "group-a").step == "origin"
    assert _get_flow(context, "group-b").mode == "search"
    assert _get_flow(context, "group-b").step == "destination"


def test_slot_list_and_detail_use_owner_local_numbers(tmp_path):
    db = Database(str(tmp_path / "db.sqlite"))
    one = _add(db, "group-a")
    two = _add(db, "group-b", origin="ICN", destination="NRT")
    assert one.slot_no == 1
    assert two.slot_no == 1
    assert two.id != one.id

    service = FlightService(Settings(_env_file=None), db, provider=object())
    listing = slot_list_keyboard(service, "telegram", "group-b")
    detail = slot_detail_keyboard(two.id, two.enabled)

    assert f"slot:{two.id}" in _callback_values(listing)
    assert any("#1 ICN→NRT" in text for text in _button_texts(listing))
    assert "➕ 새 감시" in _button_texts(listing)
    assert "🔎 바로 검색" in _button_texts(listing)
    assert f"slotcheck:{two.id}" in _callback_values(detail)
    assert f"slottarget:{two.id}" in _callback_values(detail)
    assert f"slottoggle:{two.id}" in _callback_values(detail)
    assert f"slotdeleteconfirm:{two.id}" in _callback_values(detail)
