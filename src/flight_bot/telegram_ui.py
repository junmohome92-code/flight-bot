from __future__ import annotations

from dataclasses import dataclass

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, ReplyKeyboardMarkup, Update
from telegram.ext import CallbackContext

from .locations import LocationOption, display_location, exact_location_options, suggest_locations
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
        rows.append([InlineKeyboardButton(f"{name} {option.code} · {kind}", callback_data=f"loc:{option.code}")])
    tail: list[InlineKeyboardButton] = []
    if include_retry:
        tail.append(InlineKeyboardButton("↩️ 다시 입력", callback_data="flow:retryloc"))
    tail.append(InlineKeyboardButton("❌ 취소", callback_data="flow:cancel"))
    rows.append(tail)
    return InlineKeyboardMarkup(rows)


ORIGIN_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("청주 CJJ", callback_data="loc:CJJ"), InlineKeyboardButton("서울 전체 SEL", callback_data="loc:SEL")],
        [InlineKeyboardButton("인천 ICN", callback_data="loc:ICN"), InlineKeyboardButton("부산/김해 PUS", callback_data="loc:PUS")],
        [InlineKeyboardButton("❌ 취소", callback_data="flow:cancel")],
    ]
)

DEST_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("도쿄 전체 TYO", callback_data="loc:TYO"), InlineKeyboardButton("타오위안 TPE", callback_data="loc:TPE")],
        [InlineKeyboardButton("오사카 전체 OSA", callback_data="loc:OSA"), InlineKeyboardButton("후쿠오카 FUK", callback_data="loc:FUK")],
        [InlineKeyboardButton("❌ 취소", callback_data="flow:cancel")],
    ]
)

TARGET_BUTTONS = InlineKeyboardMarkup(
    [
        [InlineKeyboardButton("20만원", callback_data="target:200000"), InlineKeyboardButton("30만원", callback_data="target:300000")],
        [InlineKeyboardButton("40만원", callback_data="target:400000"), InlineKeyboardButton("50만원", callback_data="target:500000")],
        [InlineKeyboardButton("❌ 취소", callback_data="flow:cancel")],
    ]
)


@dataclass
class Flow:
    mode: str
    step: str
    data: dict[str, str]
    slot_id: int | None = None


def _put_flow(context: CallbackContext, flow: Flow | None) -> None:
    if flow is None:
        context.user_data.pop("flight_flow", None)
    else:
        context.user_data["flight_flow"] = {
            "mode": flow.mode,
            "step": flow.step,
            "data": dict(flow.data),
            "slot_id": flow.slot_id,
        }


def _get_flow(context: CallbackContext) -> Flow | None:
    raw = context.user_data.get("flight_flow")
    if not isinstance(raw, dict):
        return None
    return Flow(
        mode=str(raw.get("mode") or ""),
        step=str(raw.get("step") or ""),
        data=dict(raw.get("data") or {}),
        slot_id=raw.get("slot_id"),
    )


def slot_list_keyboard(service: FlightService, platform: str, owner_id: str) -> InlineKeyboardMarkup:
    slots = service.db.list_slots(owner_platform=platform, owner_id=owner_id)
    buttons: list[InlineKeyboardButton] = []
    for slot in slots:
        state = "🟢" if slot.enabled else "⏸"
        price = f" {slot.last_observed_price // 1000}k" if slot.last_observed_price else ""
        buttons.append(
            InlineKeyboardButton(
                f"{state} #{slot.id} {slot.origin}→{slot.destination}{price}",
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


def _flow_prompt(flow: Flow) -> tuple[str, InlineKeyboardMarkup | None]:
    if flow.step == "origin":
        return (
            "출발지를 선택하거나 공항/도시 이름 또는 IATA 코드를 입력해 주세요.\n"
            "예: 청주, 서울, CJJ, SEL",
            ORIGIN_BUTTONS,
        )
    if flow.step == "destination":
        return (
            "도착지를 선택하거나 공항/도시 이름 또는 IATA 코드를 입력해 주세요.\n"
            "예: 도쿄, 나리타, TYO, NRT",
            DEST_BUTTONS,
        )
    if flow.step == "depart":
        return "출발일을 입력해 주세요.\n예: 2026-09-18", None
    if flow.step == "return":
        return "귀국일을 입력해 주세요.\n예: 2026-09-20", None
    if flow.step == "target":
        return "목표가를 선택하거나 원 단위 숫자로 입력해 주세요.\n예: 350000", TARGET_BUTTONS
    return "입력을 계속해 주세요.", None


async def start_flow(update: Update, context: CallbackContext, mode: str) -> None:
    flow = Flow(mode=mode, step="origin", data={})
    _put_flow(context, flow)
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
    text = f"📋 내 감시 슬롯 {used}/{service.settings.slot_active_limit}"
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
        text = f"슬롯 #{slot_id}을 찾을 수 없습니다."
        markup = slot_list_keyboard(service, "telegram", owner_id)
    else:
        text = service.format_slot(slot)
        markup = slot_detail_keyboard(slot.id, slot.enabled)
    if update.callback_query:
        await update.callback_query.answer()
        await update.callback_query.message.reply_text(text, reply_markup=markup)


def _save_location(flow: Flow, code: str) -> None:
    flow.data[flow.step] = code.upper()
    flow.step = "destination" if flow.step == "origin" else "depart"


async def _handle_location_text(update: Update, context: CallbackContext, flow: Flow, value: str) -> bool:
    exact = exact_location_options(value, limit=6)
    if len(exact) == 1:
        _save_location(flow, exact[0].code)
        _put_flow(context, flow)
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
            f"❌ '{value}' 위치를 찾을 수 없습니다.\n혹시 아래 공항/도시를 말씀하셨나요?",
            reply_markup=_location_markup(suggestions),
        )
    else:
        prompt, markup = _flow_prompt(flow)
        await update.effective_message.reply_text(
            f"❌ '{value}' 위치를 찾을 수 없습니다.\n실제 공항/도시 이름 또는 IATA 코드를 다시 입력해 주세요.\n\n{prompt}",
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
    flow = _get_flow(context)
    if not flow:
        return False
    value = text.strip()

    if flow.mode == "target":
        try:
            price = int(value.replace(",", ""))
        except ValueError:
            await update.effective_message.reply_text(
                "목표가는 숫자로 입력해 주세요. 예: 350000", reply_markup=TARGET_BUTTONS
            )
            return True
        return await _apply_target(update, context, service, owner_id, flow, price)

    if flow.step in {"origin", "destination"}:
        return await _handle_location_text(update, context, flow, value)

    if flow.step == "depart":
        if not service._valid_date(value):
            await update.effective_message.reply_text("날짜 형식은 YYYY-MM-DD 입니다. 예: 2026-09-18")
            return True
        flow.data["depart"] = value
        flow.step = "return"
    elif flow.step == "return":
        error = service.validate_trip(flow.data["origin"], flow.data["destination"], flow.data["depart"], value)
        if error:
            await update.effective_message.reply_text(error)
            return True
        flow.data["return"] = value
        if flow.mode == "search":
            _put_flow(context, None)
            await update.effective_message.reply_text("🔎 네이버 항공권을 검색 중입니다...")
            result = await service.search_now(
                flow.data["origin"], flow.data["destination"], flow.data["depart"], flow.data["return"]
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
                "목표가는 숫자로 입력해 주세요. 예: 350000", reply_markup=TARGET_BUTTONS
            )
            return True
        flow.data["target"] = str(price)
        _put_flow(context, flow)
        await _show_add_confirmation(update, flow)
        return True

    _put_flow(context, flow)
    prompt, markup = _flow_prompt(flow)
    await update.effective_message.reply_text(prompt, reply_markup=markup)
    return True


async def _show_add_confirmation(update: Update, flow: Flow) -> None:
    text = (
        "다음 조건으로 감시를 등록할까요?\n\n"
        f"✈️ {display_location(flow.data['origin'])} → {display_location(flow.data['destination'])} 왕복\n"
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
        _put_flow(context, None)
        await update.effective_message.reply_text("해당 슬롯을 찾을 수 없습니다.", reply_markup=MAIN_KEYBOARD)
        return True
    try:
        service.db.set_target(slot.id, price)
    except ValueError as exc:
        await update.effective_message.reply_text(str(exc))
        return True
    _put_flow(context, None)
    updated = service.db.get_slot(slot.id)
    await update.effective_message.reply_text(
        f"🎯 슬롯 #{slot.id} 목표가를 {price:,}원으로 변경했습니다.",
        reply_markup=slot_detail_keyboard(slot.id, updated.enabled),
    )
    return True


async def handle_callback(update: Update, context: CallbackContext, service: FlightService, owner_id: str) -> None:
    query = update.callback_query
    if not query:
        return
    data = query.data or ""

    if data == "menu:add":
        await start_flow(update, context, "add")
        return
    if data == "menu:search":
        await start_flow(update, context, "search")
        return
    if data == "menu:list":
        await show_slots(update, service, owner_id)
        return
    if data == "menu:help":
        await query.answer()
        await query.message.reply_text(HELP, reply_markup=MAIN_KEYBOARD)
        return
    if data == "flow:cancel":
        _put_flow(context, None)
        await query.answer("취소했습니다.")
        await query.message.reply_text("작업을 취소했습니다.", reply_markup=MAIN_KEYBOARD)
        return
    if data == "flow:retryloc":
        flow = _get_flow(context)
        await query.answer()
        if not flow or flow.step not in {"origin", "destination"}:
            await query.message.reply_text("입력 단계가 만료되었습니다.", reply_markup=MAIN_KEYBOARD)
            return
        prompt, markup = _flow_prompt(flow)
        await query.message.reply_text(prompt, reply_markup=markup)
        return

    if data.startswith("loc:"):
        flow = _get_flow(context)
        if not flow or flow.step not in {"origin", "destination"}:
            await query.answer("입력 단계가 만료되었습니다.")
            return
        code = data.split(":", 1)[1].upper()
        # Callback values are generated only from validated location options or
        # hard-coded known locations, so no free-form value is accepted here.
        if not exact_location_options(code):
            await query.answer("유효하지 않은 위치입니다.", show_alert=True)
            return
        _save_location(flow, code)
        _put_flow(context, flow)
        await query.answer(code)
        prompt, markup = _flow_prompt(flow)
        await query.message.reply_text(prompt, reply_markup=markup)
        return

    if data.startswith("target:"):
        flow = _get_flow(context)
        if not flow or flow.step != "target":
            await query.answer("입력 단계가 만료되었습니다.")
            return
        price = int(data.split(":", 1)[1])
        if flow.mode == "target":
            slot = service.db.get_owned_slot(int(flow.slot_id or 0), "telegram", owner_id)
            if not slot:
                _put_flow(context, None)
                await query.answer("슬롯을 찾을 수 없습니다.")
                return
            service.db.set_target(slot.id, price)
            _put_flow(context, None)
            updated = service.db.get_slot(slot.id)
            await query.answer("변경했습니다.")
            await query.message.reply_text(
                f"🎯 슬롯 #{slot.id} 목표가를 {price:,}원으로 변경했습니다.",
                reply_markup=slot_detail_keyboard(slot.id, updated.enabled),
            )
            return
        flow.data["target"] = str(price)
        _put_flow(context, flow)
        await query.answer(f"{price:,}원")
        await _show_add_confirmation(update, flow)
        return

    if data == "flow:confirmadd":
        flow = _get_flow(context)
        if (
            not flow
            or flow.mode != "add"
            or not {"origin", "destination", "depart", "return", "target"} <= flow.data.keys()
        ):
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
            )
        except ValueError as exc:
            await query.answer("등록 실패")
            await query.message.reply_text(str(exc), reply_markup=MAIN_KEYBOARD)
            return
        _put_flow(context, None)
        await query.answer("등록 완료")
        await query.message.reply_text(
            "✅ 감시 슬롯을 등록했습니다.\n" + service.format_slot(slot),
            reply_markup=slot_detail_keyboard(slot.id, slot.enabled),
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

    if data.startswith("slot:"):
        await show_slot(update, service, owner_id, slot_id)
    elif data.startswith("slotcheck:"):
        await query.answer("검색 중...")
        await query.message.reply_text(f"🔎 슬롯 #{slot_id}을 지금 검색합니다...")
        result = await service.check_slot(slot_id, notify_target=False, notify_daily_summary=False)
        updated = service.db.get_slot(slot_id) or slot
        await query.message.reply_text(
            result,
            reply_markup=slot_detail_keyboard(slot.id, updated.enabled),
            disable_web_page_preview=True,
        )
    elif data.startswith("slottarget:"):
        _put_flow(context, Flow(mode="target", step="target", data={}, slot_id=slot_id))
        await query.answer()
        await query.message.reply_text(
            f"🎯 슬롯 #{slot_id} 새 목표가를 선택하거나 입력해 주세요.", reply_markup=TARGET_BUTTONS
        )
    elif data.startswith("slottoggle:"):
        service.db.set_enabled(slot_id, not slot.enabled)
        updated = service.db.get_slot(slot_id)
        await query.answer("변경했습니다.")
        await query.message.reply_text(
            service.format_slot(updated), reply_markup=slot_detail_keyboard(slot_id, updated.enabled)
        )
    elif data.startswith("slotdeleteconfirm:"):
        await query.answer()
        await query.message.reply_text(
            f"슬롯 #{slot_id}을 정말 삭제할까요?", reply_markup=delete_confirm_keyboard(slot_id)
        )
    elif data.startswith("slotdelete:"):
        service.db.delete_slot(slot_id)
        await query.answer("삭제했습니다.")
        await query.message.reply_text(
            f"🗑 슬롯 #{slot_id}을 삭제했습니다.",
            reply_markup=slot_list_keyboard(service, "telegram", owner_id),
        )
