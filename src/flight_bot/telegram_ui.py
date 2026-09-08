from __future__ import annotations

from dataclasses import dataclass

from telegram import ForceReply, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import CallbackContext

from .locations import LocationOption, display_location, exact_location_options, resolve_code_token, suggest_locations
from .service import HELP, FlightService


MAIN_KEYBOARD = ReplyKeyboardMarkup(
    [
        [KeyboardButton("➕ 감시 등록"), KeyboardButton("🔎 바로 검색")],
        [KeyboardButton("📋 내 슬롯"), KeyboardButton("❓ 도움말")],
    ],
    resize_keyboard=True,
    is_persistent=True,
)


def _location_markup(options: list[LocationOption], *, include_retry: bool = True) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    for option in options[:6]:
        name = option.name if len(option.name) <= 24 else option.name[:23] + "…"
        kind = "전체" if option.location_type == "city" else "공항"
        rows.append(
            [
                InlineKeyboardButton(
                    f"{name} {option.code} · {kind}",
                    callback_data=f"loc:{option.location_type}:{option.code}",
                )
            ]
        )
    tail: list[InlineKeyboardButton] = []
    if include_retry:
        tail.append(InlineKeyboardButton("↩️ 다시 입력", callback_data="flow:retryloc"))
    tail.append(InlineKeyboardButton("❌ 취소", callback_data="flow:cancel"))
    rows.append(tail)
    return InlineKeyboardMarkup(rows)


TARGET_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("20만원", callback_data="target:200000"), InlineKeyboardButton("30만원", callback_data="target:300000")],
        [InlineKeyboardButton("40만원", callback_data="target:400000"), InlineKeyboardButton("50만원", callback_data="target:500000")],
        [InlineKeyboardButton("⌨️ 직접 입력", callback_data="flow:targetinput"), InlineKeyboardButton("❌ 취소", callback_data="flow:cancel")],
    ]
)


@dataclass
class Flow:
    mode: str
    step: str
    data: dict[str, str]
    slot_id: int | None = None


def _flow_key(owner_id: str) -> str:
    # python-telegram-bot user_data is shared by the same human across chats.
    # Keying by chat id keeps simultaneous group-A/group-B flows independent.
    return f"flight_flow:{owner_id}"


def _put_flow(context: CallbackContext, owner_id: str, flow: Flow | None) -> None:
    key = _flow_key(owner_id)
    if flow is None:
        context.user_data.pop(key, None)
    else:
        context.user_data[key] = {
            "mode": flow.mode,
            "step": flow.step,
            "data": dict(flow.data),
            "slot_id": flow.slot_id,
        }


def _get_flow(context: CallbackContext, owner_id: str) -> Flow | None:
    raw = context.user_data.get(_flow_key(owner_id))
    if not isinstance(raw, dict):
        return None
    return Flow(
        mode=str(raw.get("mode") or ""),
        step=str(raw.get("step") or ""),
        data=dict(raw.get("data") or {}),
        slot_id=raw.get("slot_id"),
    )


def clear_flow(context: CallbackContext, owner_id: str) -> None:
    _put_flow(context, owner_id, None)


def slot_list_keyboard(service: FlightService, platform: str, owner_id: str) -> InlineKeyboardMarkup:
    slots = service.db.list_slots(owner_platform=platform, owner_id=owner_id)
    buttons: list[InlineKeyboardButton] = []
    for slot in slots:
        state = "🟢" if slot.enabled else "⏸"
        price = f" {slot.last_observed_price // 1000}k" if slot.last_observed_price else ""
        buttons.append(
            InlineKeyboardButton(
                f"{state} #{service.slot_number(slot)} {slot.origin}→{slot.destination}{price}",
                callback_data=f"slot:{slot.id}",
            )
        )
    rows = [buttons[index : index + 2] for index in range(0, len(buttons), 2)]
    rows.append(
        [
            InlineKeyboardButton("➕ 새 감시", callback_data="menu:add"),
            InlineKeyboardButton("🔎 바로 검색", callback_data="menu:search"),
        ]
    )
    return InlineKeyboardMarkup(rows)


def slot_detail_keyboard(slot_id: int, enabled: bool) -> InlineKeyboardMarkup:
    # Callback values use the internal DB id; user-visible slot numbers are
    # conversation-local and rendered from the loaded WatchSlot.
    toggle_label = "⏸ 일시정지" if enabled else "▶️ 다시 시작"
    return InlineKeyboardMarkup(
        [
            [InlineKeyboardButton("🔎 지금 검색", callback_data=f"slotcheck:{slot_id}")],
            [
                InlineKeyboardButton("🎯 목표가 변경", callback_data=f"slottarget:{slot_id}"),
                InlineKeyboardButton(toggle_label, callback_data=f"slottoggle:{slot_id}"),
            ],
            [
                InlineKeyboardButton("🗑 삭제", callback_data=f"slotdeleteconfirm:{slot_id}"),
                InlineKeyboardButton("⬅️ 목록", callback_data="menu:list"),
            ],
        ]
    )


def delete_confirm_keyboard(slot_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ 삭제", callback_data=f"slotdelete:{slot_id}"),
                InlineKeyboardButton("↩️ 취소", callback_data=f"slot:{slot_id}"),
            ]
        ]
    )


def add_confirm_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("✅ 감시 등록", callback_data="flow:confirmadd"),
                InlineKeyboardButton("❌ 취소", callback_data="flow:cancel"),
            ]
        ]
    )


def _text_reply(placeholder: str) -> ForceReply:
    # ForceReply keeps free-text flows usable in Telegram groups even when bot
    # privacy mode is enabled, because the user replies directly to the bot.
    return ForceReply(selective=True, input_field_placeholder=placeholder)


def _flow_prompt(flow: Flow):
    if flow.step == "origin":
        return (
            "🌍 출발 도시 또는 공항을 입력해 주세요.\n"
            "한글 · 영어 · IATA 모두 가능합니다.\n"
            "예: 히로시마 / Hiroshima / HIJ",
            _text_reply("출발 도시·공항"),
        )
    if flow.step == "destination":
        return (
            "🌍 도착 도시 또는 공항을 입력해 주세요.\n"
            "한글 · 영어 · IATA 모두 가능합니다.\n"
            "예: 도쿄 / Tokyo / TYO",
            _text_reply("도착 도시·공항"),
        )
    if flow.step == "depart":
        return "출발일을 입력해 주세요.\n예: 2026-09-18", _text_reply("YYYY-MM-DD")
    if flow.step == "return":
        return "귀국일을 입력해 주세요.\n예: 2026-09-20", _text_reply("YYYY-MM-DD")
    if flow.step == "target":
        return "목표가를 선택해 주세요. 다른 금액은 '직접 입력'을 누르면 됩니다.", TARGET_BUTTONS
    return "입력을 계속해 주세요.", None


async def start_flow(update: Update, context: CallbackContext, mode: str, owner_id: str) -> None:
    flow = Flow(mode=mode, step="origin", data={})
    _put_flow(context, owner_id, flow)
    text, markup = _flow_prompt(flow)
    prefix = "➕ 감시 등록\n" if mode == "add" else "🔎 바로 검색\n"
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(prefix + text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(prefix + text, reply_markup=markup)


async def show_slots(update: Update, service: FlightService, owner_id: str) -> None:
    slots = service.db.list_slots(owner_platform="telegram", owner_id=owner_id)
    used = len(slots)
    text = f"📋 이 채팅방 감시 슬롯 {used}/{service.settings.slot_active_limit}"
    if not slots:
        text += "\n등록된 슬롯이 없습니다."
    markup = slot_list_keyboard(service, "telegram", owner_id)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=markup)
    elif update.effective_message:
        await update.effective_message.reply_text(text, reply_markup=markup)


async def show_slot(update: Update, service: FlightService, owner_id: str, slot_id: int) -> None:
    slot = service.db.get_owned_slot(slot_id, "telegram", owner_id)
    if not slot:
        text = "슬롯을 찾을 수 없습니다."
        markup = slot_list_keyboard(service, "telegram", owner_id)
    else:
        text = service.format_slot(slot)
        markup = slot_detail_keyboard(slot.id, slot.enabled)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=markup)


def _save_location(flow: Flow, option: LocationOption) -> None:
    step = flow.step
    flow.data[step] = option.code.upper()
    flow.data[f"{step}_type"] = option.location_type
    flow.step = "destination" if step == "origin" else "depart"


async def _handle_location_text(
    update: Update,
    context: CallbackContext,
    owner_id: str,
    flow: Flow,
    value: str,
) -> bool:
    exact = exact_location_options(value, limit=6)
    if len(exact) == 1:
        _save_location(flow, exact[0])
        _put_flow(context, owner_id, flow)
        prompt, markup = _flow_prompt(flow)
        await update.effective_message.reply_text(prompt, reply_markup=markup)
        return True

    if len(exact) > 1:
        await update.effective_message.reply_text(
            f"'{value}'에는 여러 선택지가 있습니다. 원하는 항목을 선택해 주세요.",
            reply_markup=_location_markup(exact),
        )
        return True

    suggestions = suggest_locations(value, limit=6)
    if suggestions:
        await update.effective_message.reply_text(
            f"🔎 '{value}' 검색 결과입니다. 원하는 공항/도시를 선택해 주세요.",
            reply_markup=_location_markup(suggestions),
        )
    else:
        prompt, markup = _flow_prompt(flow)
        await update.effective_message.reply_text(
            f"❌ '{value}' 위치를 찾을 수 없습니다.\n\n{prompt}",
            reply_markup=markup,
        )
    return True


async def handle_flow_text(
    update: Update,
    context: CallbackContext,
    service: FlightService,
    owner_id: str,
    text: str,
) -> bool:
    flow = _get_flow(context, owner_id)
    if not flow:
        return False
    value = text.strip()

    if flow.mode == "target":
        try:
            price = int(value.replace(",", ""))
        except ValueError:
            await update.effective_message.reply_text(
                "목표가는 숫자로 입력해 주세요. 예: 350000", reply_markup=_text_reply("예: 350000")
            )
            return True
        return await _apply_target(update, context, service, owner_id, flow, price)

    if flow.step in {"origin", "destination"}:
        return await _handle_location_text(update, context, owner_id, flow, value)

    if flow.step == "depart":
        if not service._valid_date(value):
            await update.effective_message.reply_text(
                "날짜 형식은 YYYY-MM-DD 입니다. 예: 2026-09-18",
                reply_markup=_text_reply("YYYY-MM-DD"),
            )
            return True
        flow.data["depart"] = value
        flow.step = "return"
    elif flow.step == "return":
        error = service.validate_trip(
            flow.data["origin"],
            flow.data["destination"],
            flow.data["depart"],
            value,
            origin_type=flow.data.get("origin_type"),
            destination_type=flow.data.get("destination_type"),
        )
        if error:
            await update.effective_message.reply_text(error, reply_markup=_text_reply("YYYY-MM-DD"))
            return True
        flow.data["return"] = value
        if flow.mode == "search":
            _put_flow(context, owner_id, None)
            await update.effective_message.reply_text("🔎 네이버 항공권을 검색 중입니다...")
            result = await service.search_now(
                flow.data["origin"],
                flow.data["destination"],
                flow.data["depart"],
                flow.data["return"],
                origin_type=flow.data.get("origin_type"),
                destination_type=flow.data.get("destination_type"),
            )
            await update.effective_message.reply_text(
                result, reply_markup=MAIN_KEYBOARD, disable_web_page_preview=True
            )
            return True
        flow.step = "target"
    elif flow.step == "target":
        try:
            price = int(value.replace(",", ""))
        except ValueError:
            await update.effective_message.reply_text(
                "목표가는 숫자로 입력해 주세요. 예: 350000", reply_markup=_text_reply("예: 350000")
            )
            return True
        flow.data["target"] = str(price)
        _put_flow(context, owner_id, flow)
        await _show_add_confirmation(update, flow)
        return True

    _put_flow(context, owner_id, flow)
    prompt, markup = _flow_prompt(flow)
    await update.effective_message.reply_text(prompt, reply_markup=markup)
    return True


async def _show_add_confirmation(update: Update, flow: Flow) -> None:
    text = (
        "다음 조건으로 감시를 등록할까요?\n\n"
        f"✈️ {display_location(flow.data['origin'], flow.data.get('origin_type'))} → "
        f"{display_location(flow.data['destination'], flow.data.get('destination_type'))} 왕복\n"
        f"📅 {flow.data['depart']} ~ {flow.data['return']}\n"
        f"🎯 목표가 {int(flow.data['target']):,}원\n"
        "직항 · 성인 1명 · 이코노미"
    )
    if update.callback_query:
        await update.callback_query.message.reply_text(text, reply_markup=add_confirm_keyboard())
    else:
        await update.effective_message.reply_text(text, reply_markup=add_confirm_keyboard())


async def _apply_target(
    update: Update,
    context: CallbackContext,
    service: FlightService,
    owner_id: str,
    flow: Flow,
    price: int,
) -> bool:
    slot = service.db.get_owned_slot(int(flow.slot_id or 0), "telegram", owner_id)
    if not slot:
        _put_flow(context, owner_id, None)
        await update.effective_message.reply_text("해당 슬롯을 찾을 수 없습니다.", reply_markup=MAIN_KEYBOARD)
        return True
    try:
        service.db.set_target(slot.id, price)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return True
    _put_flow(context, owner_id, None)
    updated = service.db.get_slot(slot.id) or slot
    await update.effective_message.reply_text(
        f"🎯 슬롯 #{service.slot_number(updated)} 목표가를 {price:,}원으로 변경했습니다.",
        reply_markup=slot_detail_keyboard(slot.id, updated.enabled),
    )
    return True


async def handle_callback(update: Update, context: CallbackContext, service: FlightService, owner_id: str) -> None:
    query = update.callback_query
    if not query:
        return
    data = query.data or ""

    if data == "menu:add":
        await start_flow(update, context, "add", owner_id)
        return
    if data == "menu:search":
        await start_flow(update, context, "search", owner_id)
        return
    if data == "menu:list":
        await show_slots(update, service, owner_id)
        return
    if data == "menu:help":
        await query.answer()
        await query.message.reply_text(HELP, reply_markup=MAIN_KEYBOARD)
        return
    if data == "flow:cancel":
        _put_flow(context, owner_id, None)
        await query.answer("취소했습니다.")
        await query.message.reply_text("작업을 취소했습니다.", reply_markup=MAIN_KEYBOARD)
        return
    if data == "flow:retryloc":
        flow = _get_flow(context, owner_id)
        await query.answer()
        if not flow or flow.step not in {"origin", "destination"}:
            await query.message.reply_text("입력 단계가 만료되었습니다.", reply_markup=MAIN_KEYBOARD)
            return
        prompt, markup = _flow_prompt(flow)
        await query.message.reply_text(prompt, reply_markup=markup)
        return
    if data == "flow:targetinput":
        flow = _get_flow(context, owner_id)
        await query.answer()
        if not flow or flow.step != "target":
            await query.message.reply_text("입력 단계가 만료되었습니다.", reply_markup=MAIN_KEYBOARD)
            return
        await query.message.reply_text(
            "목표가를 원 단위 숫자로 입력해 주세요. 예: 350000",
            reply_markup=_text_reply("예: 350000"),
        )
        return

    if data.startswith("loc:"):
        flow = _get_flow(context, owner_id)
        if not flow or flow.step not in {"origin", "destination"}:
            await query.answer("입력 단계가 만료되었습니다.")
            return
        parts = data.split(":")
        option = None
        if len(parts) == 3:
            kind, code = parts[1], parts[2].upper()
            option = next(
                (
                    candidate
                    for candidate in exact_location_options(code, limit=12)
                    if candidate.code == code and candidate.location_type == kind
                ),
                None,
            )
        elif len(parts) == 2:
            # Backward compatibility for old inline buttons still visible in a
            # chat after the bot is upgraded.
            code = parts[1].upper()
            option = resolve_code_token(code)
        if not option:
            await query.answer("유효하지 않은 위치입니다.", show_alert=True)
            return
        _save_location(flow, option)
        _put_flow(context, owner_id, flow)
        await query.answer(option.code)
        prompt, markup = _flow_prompt(flow)
        await query.message.reply_text(prompt, reply_markup=markup)
        return

    if data.startswith("target:"):
        flow = _get_flow(context, owner_id)
        if not flow or flow.step != "target":
            await query.answer("입력 단계가 만료되었습니다.")
            return
        price = int(data.split(":", 1)[1])
        if flow.mode == "target":
            slot = service.db.get_owned_slot(int(flow.slot_id or 0), "telegram", owner_id)
            if not slot:
                _put_flow(context, owner_id, None)
                await query.answer("슬롯을 찾을 수 없습니다.")
                return
            service.db.set_target(slot.id, price)
            _put_flow(context, owner_id, None)
            updated = service.db.get_slot(slot.id) or slot
            await query.answer("변경했습니다.")
            await query.message.reply_text(
                f"🎯 슬롯 #{service.slot_number(updated)} 목표가를 {price:,}원으로 변경했습니다.",
                reply_markup=slot_detail_keyboard(slot.id, updated.enabled),
            )
            return
        flow.data["target"] = str(price)
        _put_flow(context, owner_id, flow)
        await query.answer(f"{price:,}원")
        await _show_add_confirmation(update, flow)
        return

    if data == "flow:confirmadd":
        flow = _get_flow(context, owner_id)
        required = {"origin", "origin_type", "destination", "destination_type", "depart", "return", "target"}
        if not flow or flow.mode != "add" or not required <= flow.data.keys():
            await query.answer("등록 정보가 만료되었습니다.")
            return
        try:
            slot = await service.add_watch(
                "telegram",
                owner_id,
                flow.data["origin"],
                flow.data["destination"],
                flow.data["depart"],
                flow.data["return"],
                int(flow.data["target"]),
                origin_type=flow.data["origin_type"],
                destination_type=flow.data["destination_type"],
            )
        except ValueError as exc:
            await query.answer("등록 실패")
            await query.message.reply_text(str(exc), reply_markup=MAIN_KEYBOARD)
            return
        _put_flow(context, owner_id, None)
        await query.answer("등록 완료")
        await query.message.reply_text(
            "✅ 감시 슬롯을 등록했습니다.\n" + service.format_slot(slot) + "\n\n현재 가격을 한 번 확인합니다.",
        )
        # Registration establishes a baseline only. Even when this first price
        # is below target, the one-shot target alert remains ARMED for the next
        # scheduled scan, matching the intended register -> target-hit -> daily
        # report lifecycle.
        result = await service.check_slot(slot.id, notify_target=False, notify_daily_summary=False)
        updated = service.db.get_slot(slot.id) or slot
        await query.message.reply_text(
            result,
            reply_markup=slot_detail_keyboard(slot.id, updated.enabled),
            disable_web_page_preview=True,
        )
        return

    slot_id = None
    for prefix in ("slot:", "slotcheck:", "slottarget:", "slottoggle:", "slotdeleteconfirm:", "slotdelete:"):
        if data.startswith(prefix):
            try:
                slot_id = int(data.split(":", 1)[1])
            except ValueError:
                await query.answer("잘못된 슬롯입니다.")
                return
            break
    if slot_id is None:
        await query.answer()
        return

    slot = service.db.get_owned_slot(slot_id, "telegram", owner_id)
    if not slot:
        await query.answer("슬롯을 찾을 수 없습니다.")
        return
    number = service.slot_number(slot)

    if data.startswith("slot:"):
        await show_slot(update, service, owner_id, slot_id)
    elif data.startswith("slotcheck:"):
        await query.answer("검색 중...")
        await query.message.reply_text(f"🔎 슬롯 #{number}을 지금 검색합니다...")
        result = await service.check_slot(slot_id, notify_target=False, notify_daily_summary=False)
        updated = service.db.get_slot(slot_id) or slot
        await query.message.reply_text(
            result,
            reply_markup=slot_detail_keyboard(slot.id, updated.enabled),
            disable_web_page_preview=True,
        )
    elif data.startswith("slottarget:"):
        _put_flow(context, owner_id, Flow(mode="target", step="target", data={}, slot_id=slot_id))
        await query.answer()
        await query.message.reply_text(
            f"🎯 슬롯 #{number} 새 목표가를 선택해 주세요.", reply_markup=TARGET_BUTTONS
        )
    elif data.startswith("slottoggle:"):
        service.db.set_enabled(slot_id, not slot.enabled)
        updated = service.db.get_slot(slot_id) or slot
        await query.answer("변경했습니다.")
        await query.message.reply_text(
            service.format_slot(updated), reply_markup=slot_detail_keyboard(slot_id, updated.enabled)
        )
    elif data.startswith("slotdeleteconfirm:"):
        await query.answer()
        await query.message.reply_text(
            f"슬롯 #{number}을 정말 삭제할까요?", reply_markup=delete_confirm_keyboard(slot_id)
        )
    elif data.startswith("slotdelete:"):
        service.db.delete_slot(slot_id)
        await query.answer("삭제했습니다.")
        await query.message.reply_text(
            f"🗑 슬롯 #{number}을 삭제했습니다.",
            reply_markup=slot_list_keyboard(service, "telegram", owner_id),
        )
