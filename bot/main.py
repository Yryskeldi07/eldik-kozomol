import asyncio
import os
import html
from typing import Any

import httpx
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, F
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "").strip()
API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

if not TOKEN:
    raise RuntimeError("BOT_TOKEN не найден. Проверьте переменную окружения BOT_TOKEN.")


# ============================================================
# TEXTS
# ============================================================

BRAND = "<b>ЭЛДИК КӨЗӨМӨЛ</b>"

LEGAL_WARNING = (
    "<b>⚖️ ПРАВОВОЕ ПРЕДУПРЕЖДЕНИЕ</b>\n\n"
    "В соответствии со статьями 363–365 Уголовного кодекса Кыргызской Республики "
    "за предусмотренные законом заведомо ложные сообщения и показания, а также "
    "отдельные случаи отказа или уклонения от дачи показаний может наступать "
    "уголовная ответственность. Закон предусматривает исключения, в том числе "
    "право не свидетельствовать против себя, супруга(и) и близких родственников.\n\n"
    "Сообщайте только известные вам факты. Отделяйте то, что вы лично видели, "
    "от предположений. Не создавайте доказательства и не обвиняйте людей без оснований.\n\n"
    "Это информационное предупреждение, а не юридическая консультация."
)

DISCLAIMER = (
    "<b>О проекте</b>\n\n"
    "«Элдик Көзөмөл» — независимый технический канал для направления сообщений "
    "о предполагаемых правонарушениях. Он не является официальной государственной "
    "приёмной и не гарантирует передачу сообщения государственному органу.\n\n"
    "<b>Важно об анонимности:</b> Telegram не гарантирует полной анонимности. "
    "Не указывайте имя, телефон, адрес и другие персональные данные, если не хотите "
    "их раскрывать. Не отправляйте пароли и коды подтверждения.\n\n"
    "Если человеку прямо сейчас угрожает опасность, обратитесь в экстренные службы."
)

TEXT: dict[str, dict[str, str]] = {
    "ru": {
        "welcome": "<b>ЭЛДИК КӨЗӨМӨЛ</b>\nОбщественный контроль и канал сообщений\n\nВыберите действие в меню ниже.",
        "choose_language": "🌐 <b>Выберите язык / Тилди тандаңыз</b>",
        "menu": "<b>Главное меню</b>\nВыберите нужный раздел:",
        "new_report": "📝 Подать обращение",
        "status": "🔎 Проверить статус",
        "about": "🛡️ О проекте и безопасности",
        "language": "🌐 Сменить язык",
        "home": "🏠 Главное меню",
        "cancel": "✖️ Отменить",
        "choose_category": "🗂 <b>Шаг 1 из 4. Категория</b>\nВыберите тему обращения:",
        "region": "📍 <b>Шаг 2 из 4. Регион</b>\nУкажите область или город. Если не знаете или не хотите указывать — нажмите «Пропустить».",
        "district": "📍 <b>Шаг 3 из 4. Район</b>\nУкажите район или нажмите «Пропустить».",
        "skip": "Пропустить",
        "description": "📝 <b>Шаг 4 из 4. Описание</b>\n\nОпишите, что произошло. Минимум 30 символов. Укажите известные факты, даты и обстоятельства. Не добавляйте предположения как доказанные факты.",
        "too_short": "Пожалуйста, добавьте подробности. Минимальная длина описания — 30 символов.",
        "sending": "⏳ Отправляем обращение на сервер…",
        "connection_error": "Не удалось подключиться к серверу. Попробуйте позже. Обращение не подтверждено как зарегистрированное.",
        "server_error": "Сервер не принял обращение. Попробуйте позже. Обращение не подтверждено как зарегистрированное.",
        "bad_response": "Сервер вернул некорректный ответ. Не удалось подтвердить регистрацию обращения.",
        "registered": "✅ <b>Обращение зарегистрировано</b>\n\n<b>Номер:</b> <code>{code}</code>\n\nЕсли у вас есть доказательства, прикрепите фотографии, видео или документы — отправляйте их по одному. Если материалов нет или вы не хотите их отправлять, нажмите «Пропустить».\n\nСохраните номер — он понадобится для проверки статуса.",
        "file_added": "📎 Файл <b>{name}</b> прикреплён к обращению <code>{code}</code>.",
        "file_help": "📎 <b>Материалы и доказательства (необязательно)</b>\n\nПри наличии отправьте фото, видео или документ. Можно отправлять несколько файлов по одному.\nПоддерживаются JPG, PNG, WEBP, PDF, DOC, DOCX, MP4 и WEBM.\n\nЕсли доказательств нет — нажмите «Пропустить».",
        "file_type": "Этот формат не поддерживается. Разрешены JPG, PNG, WEBP, PDF, DOC, DOCX, MP4 и WEBM.",
        "file_error": "Не удалось загрузить файл. Проверьте формат и размер, затем попробуйте ещё раз.",
        "file_server_error": "Сервер отклонил файл: {detail}",
        "done": "✅ <b>Приём файлов завершён</b>\n\nНомер обращения: <code>{code}</code>\nСохраните его для проверки статуса.",
        "ask_code": "Введите номер обращения в формате <code>EK-XXXXXXXXXX</code>.",
        "bad_code": "Неверный формат. Введите номер, начинающийся с <code>EK-</code>.",
        "not_found": "Обращение с таким номером не найдено. Проверьте номер и попробуйте ещё раз.",
        "status_result": "🔎 <b>Информация об обращении</b>\n\n<b>Номер:</b> <code>{code}</code>\n<b>Статус:</b> {status}",
        "service_error": "Сервис временно недоступен. Попробуйте позже.",
        "cancelled": "Действие отменено. Вы вернулись в главное меню.",
        "choose_button": "Пожалуйста, воспользуйтесь кнопками меню.",
        "finish": "Пропустить / Завершить",
        "status_names": {"new": "Новое", "review": "На рассмотрении", "referred": "Направлено", "need_info": "Требуется информация", "closed": "Закрыто"},
        "categories": [("Коррупция", "corruption"), ("Преступление", "crime"), ("Злоупотребление", "abuse"), ("Киберпреступление", "cybercrime"), ("Другое", "other")],
    },
    "ky": {
        "welcome": "<b>ЭЛДИК КӨЗӨМӨЛ</b>\nКоомдук көзөмөл жана билдирүү каналы\n\nТөмөнкү менюдан керектүү бөлүмдү тандаңыз.",
        "choose_language": "🌐 <b>Выберите язык / Тилди тандаңыз</b>",
        "menu": "<b>Башкы меню</b>\nКеректүү бөлүмдү тандаңыз:",
        "new_report": "📝 Кайрылуу жөнөтүү",
        "status": "🔎 Кайрылуунун статусу",
        "about": "🛡️ Долбоор жана коопсуздук",
        "language": "🌐 Тилди өзгөртүү",
        "home": "🏠 Башкы меню",
        "cancel": "✖️ Жокко чыгаруу",
        "choose_category": "🗂 <b>1/4-кадам. Категория</b>\nКайрылуунун темасын тандаңыз:",
        "region": "📍 <b>2/4-кадам. Облус</b>\nОблусту же шаарды көрсөтүңүз. Билбесеңиз же көрсөткүңүз келбесе, «Өткөрүп жиберүү» баскычын басыңыз.",
        "district": "📍 <b>3/4-кадам. Район</b>\nРайонду көрсөтүңүз же «Өткөрүп жиберүү» баскычын басыңыз.",
        "skip": "Өткөрүп жиберүү",
        "description": "📝 <b>4/4-кадам. Окуянын сүрөттөлүшү</b>\n\nОкуяны толук сүрөттөп бериңиз. Кеминде 30 белги. Белгилүү фактыларды, даталарды жана жагдайларды көрсөтүңүз.",
        "too_short": "Көбүрөөк маалымат бериңиз. Сүрөттөмө кеминде 30 белгиден турушу керек.",
        "sending": "⏳ Кайрылуу серверге жөнөтүлүүдө…",
        "connection_error": "Серверге туташуу мүмкүн болгон жок. Кийинчерээк аракет кылыңыз. Кайрылуунун катталганы ырасталган жок.",
        "server_error": "Сервер кайрылууну кабыл алган жок. Кийинчерээк аракет кылыңыз.",
        "bad_response": "Сервер туура эмес жооп берди. Кайрылуунун катталганы ырасталган жок.",
        "registered": "✅ <b>Кайрылуу катталды</b>\n\n<b>Номери:</b> <code>{code}</code>\n\nДалилдериңиз болсо, сүрөттөрдү, видеолорду же документтерди бирден жөнөтүңүз. Эгер материал жок болсо же жөнөткүңүз келбесе, «Өткөрүп жиберүү» баскычын басыңыз.\n\nНомерди сактап коюңуз — статусун текшерүү үчүн керек болот.",
        "file_added": "📎 <b>{name}</b> файлы <code>{code}</code> кайрылуусуна тиркелди.",
        "file_help": "📎 <b>Материалдар жана далилдер (милдеттүү эмес)</b>\n\nМүмкүн болсо сүрөт, видео же документ жөнөтүңүз. Бир нече файлды бирден жөнөтсөңүз болот.\nJPG, PNG, WEBP, PDF, DOC, DOCX, MP4 жана WEBM форматтары колдоого алынат.\n\nДалил жок болсо — «Өткөрүп жиберүү» баскычын басыңыз.",
        "file_type": "Бул формат колдоого алынбайт. JPG, PNG, WEBP, PDF, DOC, DOCX, MP4 жана WEBM жөнөтүңүз.",
        "file_error": "Файл жүктөлгөн жок. Форматын жана өлчөмүн текшерип, кайра аракет кылыңыз.",
        "file_server_error": "Сервер файлды кабыл алган жок: {detail}",
        "done": "✅ <b>Файлдарды кабыл алуу аяктады</b>\n\nКайрылуунун номери: <code>{code}</code>\nСтатусту текшерүү үчүн номерди сактаңыз.",
        "ask_code": "Кайрылуунун номерин <code>EK-XXXXXXXXXX</code> форматында киргизиңиз.",
        "bad_code": "Номер туура эмес. <code>EK-</code> менен башталган номерди киргизиңиз.",
        "not_found": "Мындай номердеги кайрылуу табылган жок. Номерди текшериңиз.",
        "status_result": "🔎 <b>Кайрылуу жөнүндө маалымат</b>\n\n<b>Номери:</b> <code>{code}</code>\n<b>Статусу:</b> {status}",
        "service_error": "Кызмат убактылуу жеткиликсиз. Кийинчерээк аракет кылыңыз.",
        "cancelled": "Аракет жокко чыгарылды. Башкы менюга кайттыңыз.",
        "choose_button": "Сураныч, менюдагы баскычтарды колдонуңуз.",
        "finish": "Өткөрүп жиберүү / Аяктоо",
        "status_names": {"new": "Жаңы", "review": "Каралууда", "referred": "Жөнөтүлдү", "need_info": "Кошумча маалымат керек", "closed": "Жабылды"},
        "categories": [("Коррупция", "corruption"), ("Кылмыш", "crime"), ("Кызмат абалынан кыянаттык", "abuse"), ("Киберкылмыштуулук", "cybercrime"), ("Башка", "other")],
    },
}


# ============================================================
# FSM STATES
# ============================================================

class Form(StatesGroup):
    language = State()
    category = State()
    region = State()
    district = State()
    description = State()
    attachments = State()
    status_code = State()


def get_lang(data: dict[str, Any]) -> str:
    return data.get("language", "ru") if data.get("language") in TEXT else "ru"


def tr(lang: str, key: str) -> str:
    return TEXT[get_lang({"language": lang})][key]


# ============================================================
# INLINE KEYBOARDS — NO LARGE REPLY KEYBOARD
# ============================================================

def language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇰🇬 Кыргызча", callback_data="lang:ky")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
    ])


def main_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    t = TEXT[lang]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["new_report"], callback_data="menu:new")],
        [InlineKeyboardButton(text=t["status"], callback_data="menu:status")],
        [InlineKeyboardButton(text=t["about"], callback_data="menu:about")],
        [InlineKeyboardButton(text=t["language"], callback_data="menu:language")],
    ])


def category_keyboard(lang: str) -> InlineKeyboardMarkup:
    rows = []
    for label, value in TEXT[lang]["categories"]:
        rows.append([InlineKeyboardButton(text=label, callback_data=f"category:{value}")])
    rows.append([InlineKeyboardButton(text=TEXT[lang]["cancel"], callback_data="form:cancel")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def skip_keyboard(lang: str, stage: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXT[lang]["skip"], callback_data=f"skip:{stage}")],
        [InlineKeyboardButton(text=TEXT[lang]["cancel"], callback_data="form:cancel")],
    ])


def attachment_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXT[lang]["finish"], callback_data="attachments:done")],
        [InlineKeyboardButton(text=TEXT[lang]["cancel"], callback_data="form:cancel")],
    ])


def back_menu_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TEXT[lang]["home"], callback_data="menu:home")]
    ])


# ============================================================
# START / WARNING / LANGUAGE / MENU
# ============================================================

async def start(message: Message, state: FSMContext):
    await state.clear()
    buttons = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Понимаю, продолжить / Түшүндүм, улантуу", callback_data="warning:accept")],
        [InlineKeyboardButton(text="Отказаться / Баш тартуу", callback_data="warning:decline")],
    ])
    await message.answer(LEGAL_WARNING, reply_markup=buttons)


async def warning_accept(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(DISCLAIMER)
    await callback.message.answer(TEXT["ru"]["choose_language"], reply_markup=language_keyboard())
    await state.set_state(Form.language)


async def warning_decline(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Вы отказались продолжить. Чтобы начать заново, отправьте /start.")


async def choose_language(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    lang = callback.data.split(":", 1)[1]
    await state.update_data(language=lang)
    await state.set_state(None)
    await callback.message.edit_text(TEXT[lang]["welcome"], reply_markup=main_menu_keyboard(lang))


async def show_menu(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    await state.set_state(None)
    await message.answer(TEXT[lang]["menu"], reply_markup=main_menu_keyboard(lang))


async def menu_action(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    action = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = get_lang(data)
    t = TEXT[lang]

    if action == "home":
        await state.set_state(None)
        await callback.message.edit_text(t["menu"], reply_markup=main_menu_keyboard(lang))
    elif action == "language":
        await state.set_state(Form.language)
        await callback.message.edit_text(t["choose_language"], reply_markup=language_keyboard())
    elif action == "about":
        await callback.message.edit_text(DISCLAIMER, reply_markup=back_menu_keyboard(lang))
    elif action == "new":
        await state.update_data(category=None, region=None, district=None)
        await state.set_state(Form.category)
        await callback.message.edit_text(t["choose_category"], reply_markup=category_keyboard(lang))
    elif action == "status":
        await state.set_state(Form.status_code)
        await callback.message.answer(t["ask_code"], reply_markup=back_menu_keyboard(lang))


# ============================================================
# REPORT FORM
# ============================================================

async def category_selected(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    category_value = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = get_lang(data)
    allowed = {value for _, value in TEXT[lang]["categories"]}
    if category_value not in allowed:
        await callback.message.answer(TEXT[lang]["choose_button"])
        return
    await state.update_data(category=category_value)
    await state.set_state(Form.region)
    await callback.message.edit_text(TEXT[lang]["region"], reply_markup=skip_keyboard(lang, "region"))


async def skip_location(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    stage = callback.data.split(":", 1)[1]
    data = await state.get_data()
    lang = get_lang(data)
    if stage == "region" and await state.get_state() == Form.region.state:
        await state.update_data(region=None)
        await state.set_state(Form.district)
        await callback.message.edit_text(TEXT[lang]["district"], reply_markup=skip_keyboard(lang, "district"))
    elif stage == "district" and await state.get_state() == Form.district.state:
        await state.update_data(district=None)
        await state.set_state(Form.description)
        await callback.message.edit_text(TEXT[lang]["description"], reply_markup=back_menu_keyboard(lang))
    else:
        await callback.answer(TEXT[lang]["choose_button"], show_alert=False)


async def region(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    value = (message.text or "").strip()
    if not value:
        await message.answer(TEXT[lang]["region"], reply_markup=skip_keyboard(lang, "region"))
        return
    if value.lower() in {"пропустить", "өткөрүп жиберүү"}:
        value = ""
    await state.update_data(region=value[:100] or None)
    await state.set_state(Form.district)
    await message.answer(TEXT[lang]["district"], reply_markup=skip_keyboard(lang, "district"))


async def district(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    value = (message.text or "").strip()
    if not value:
        await message.answer(TEXT[lang]["district"], reply_markup=skip_keyboard(lang, "district"))
        return
    if value.lower() in {"пропустить", "өткөрүп жиберүү"}:
        value = ""
    await state.update_data(district=value[:100] or None)
    await state.set_state(Form.description)
    await message.answer(TEXT[lang]["description"], reply_markup=back_menu_keyboard(lang))


async def description(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    text = (message.text or "").strip()
    if len(text) < 30:
        await message.answer(TEXT[lang]["too_short"])
        return

    payload = {
        "language": lang,
        "category": data.get("category"),
        "region": data.get("region"),
        "district": data.get("district"),
        "description": text[:10000],
    }

    progress = await message.answer(TEXT[lang]["sending"])
    try:
        async with httpx.AsyncClient(timeout=20) as client:
            response = await client.post(f"{API}/api/v1/reports", json=payload)
            response.raise_for_status()
            result = response.json()
    except httpx.RequestError:
        await progress.edit_text(TEXT[lang]["connection_error"])
        await state.clear()
        return
    except httpx.HTTPStatusError:
        await progress.edit_text(TEXT[lang]["server_error"])
        await state.clear()
        return
    except (ValueError, TypeError):
        await progress.edit_text(TEXT[lang]["bad_response"])
        await state.clear()
        return

    public_code = result.get("public_code")
    upload_token = result.get("upload_token")
    if not public_code or not upload_token:
        await progress.edit_text(TEXT[lang]["bad_response"])
        await state.clear()
        return

    await state.update_data(public_code=public_code, upload_token=upload_token, attachment_count=0)
    await state.set_state(Form.attachments)
    await progress.edit_text(TEXT[lang]["registered"].format(code=public_code))
    await message.answer(TEXT[lang]["file_help"], reply_markup=attachment_keyboard(lang))


# ============================================================
# ATTACHMENTS
# ============================================================

async def upload_attachment(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    lang = get_lang(data)
    public_code = data.get("public_code")
    upload_token = data.get("upload_token")

    if not public_code or not upload_token:
        await message.answer(TEXT[lang]["file_error"])
        await state.clear()
        return

    file_id = None
    filename = None
    content_type = None

    file_size = None
    if message.photo:
        photo = message.photo[-1]
        file_size = photo.file_size
        file_id = photo.file_id
        filename = f"telegram_photo_{photo.file_unique_id}.jpg"
        content_type = "image/jpeg"
    elif message.document:
        doc = message.document
        file_id = doc.file_id
        file_size = doc.file_size
        filename = doc.file_name or f"telegram_document_{doc.file_unique_id}"
        content_type = (doc.mime_type or "application/octet-stream").lower().split(";", 1)[0].strip()
    elif message.video:
        video = message.video
        file_id = video.file_id
        file_size = video.file_size
        filename = video.file_name or f"telegram_video_{video.file_unique_id}.mp4"
        content_type = "video/mp4"
    else:
        await message.answer(TEXT[lang]["file_help"], reply_markup=attachment_keyboard(lang))
        return

    # Telegram cloud Bot API обычно позволяет скачать файл ботом размером до 20 МБ.
    if file_size and file_size > 20 * 1024 * 1024:
        size_warning = (
            "Файл больше 20 МБ. Отправьте файл меньшего размера."
            if lang == "ru"
            else "Файл 20 МБдан чоң. Көлөмү азыраак файл жөнөтүңүз."
        )
        await message.answer(size_warning, reply_markup=attachment_keyboard(lang))
        return

    allowed = {
        "image/jpeg", "image/png", "image/webp",
        "application/pdf", "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "video/mp4", "video/webm",
    }
    if content_type not in allowed:
        await message.answer(TEXT[lang]["file_type"], reply_markup=attachment_keyboard(lang))
        return

    try:
        telegram_file = await bot.get_file(file_id)
        downloaded = await bot.download_file(telegram_file.file_path)
        file_bytes = downloaded.getvalue() if hasattr(downloaded, "getvalue") else downloaded.read()
        if not file_bytes:
            raise ValueError("empty file")

        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{API}/api/v1/reports/{public_code}/attachments",
                params={"upload_token": upload_token},
                files={"file": (filename, file_bytes, content_type)},
            )
            response.raise_for_status()

        count = int(data.get("attachment_count", 0)) + 1
        await state.update_data(attachment_count=count)
        await message.answer(
            TEXT[lang]["file_added"].format(name=html.escape(filename), code=html.escape(public_code)),
            reply_markup=attachment_keyboard(lang),
        )
    except httpx.HTTPStatusError as exc:
        detail = "Сервер отклонил файл."
        try:
            body = exc.response.json()
            detail = body.get("detail", detail)
        except Exception:
            pass
        await message.answer(TEXT[lang]["file_server_error"].format(detail=html.escape(str(detail))), reply_markup=attachment_keyboard(lang))
    except Exception:
        await message.answer(TEXT[lang]["file_error"], reply_markup=attachment_keyboard(lang))


async def finish_attachments(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    lang = get_lang(data)
    code = data.get("public_code")
    await state.clear()
    await callback.message.edit_text(
        TEXT[lang]["done"].format(code=code or "—"),
        reply_markup=main_menu_keyboard(lang),
    )


async def finish_attachments_command(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    code = data.get("public_code")
    await state.clear()
    await message.answer(
        TEXT[lang]["done"].format(code=code or "—"),
        reply_markup=main_menu_keyboard(lang),
    )


# ============================================================
# STATUS CHECK
# ============================================================

async def lookup_status(message: Message, state: FSMContext, code: str):
    data = await state.get_data()
    lang = get_lang(data)
    code = code.strip().upper()
    if not code.startswith("EK-") or len(code) < 6:
        await message.answer(TEXT[lang]["bad_code"], reply_markup=back_menu_keyboard(lang))
        return

    try:
        async with httpx.AsyncClient(timeout=12) as client:
            response = await client.get(f"{API}/api/v1/reports/{code}")
        if response.status_code == 404:
            await message.answer(TEXT[lang]["not_found"], reply_markup=main_menu_keyboard(lang))
            await state.set_state(None)
            return
        response.raise_for_status()
        result = response.json()
        status = str(result.get("status", "—"))
        status = TEXT[lang]["status_names"].get(status, status)
        await message.answer(
            TEXT[lang]["status_result"].format(code=html.escape(str(result.get("public_code", code))), status=html.escape(str(status))),
            reply_markup=main_menu_keyboard(lang),
        )
        await state.set_state(None)
    except (httpx.RequestError, httpx.HTTPStatusError, ValueError):
        await message.answer(TEXT[lang]["service_error"], reply_markup=main_menu_keyboard(lang))
        await state.set_state(None)


async def status_code(message: Message, state: FSMContext):
    await lookup_status(message, state, message.text or "")


# ============================================================
# CANCEL / COMMANDS
# ============================================================

async def cancel(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = get_lang(data)
    await state.clear()
    await message.answer(TEXT[lang]["cancelled"], reply_markup=main_menu_keyboard(lang))


async def status_command(message: Message, state: FSMContext):
    parts = (message.text or "").split(maxsplit=1)
    data = await state.get_data()
    lang = get_lang(data)
    if len(parts) != 2:
        await message.answer(TEXT[lang]["ask_code"])
        await state.set_state(Form.status_code)
        return
    await state.set_state(Form.status_code)
    await lookup_status(message, state, parts[1])


async def cancel_callback(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    data = await state.get_data()
    lang = get_lang(data)
    await state.clear()
    await callback.message.edit_text(TEXT[lang]["cancelled"], reply_markup=main_menu_keyboard(lang))


# ============================================================
# MAIN
# ============================================================

async def main():
    bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())

    # Commands
    dp.message.register(start, CommandStart())
    dp.message.register(cancel, Command("cancel"))
    dp.message.register(show_menu, Command("menu"))
    dp.message.register(finish_attachments_command, Command("done"), Form.attachments)
    dp.message.register(status_command, Command("status"))

    # Callback actions
    dp.callback_query.register(warning_accept, F.data == "warning:accept")
    dp.callback_query.register(warning_decline, F.data == "warning:decline")
    dp.callback_query.register(choose_language, F.data.startswith("lang:"))
    dp.callback_query.register(menu_action, F.data.startswith("menu:"))
    dp.callback_query.register(category_selected, F.data.startswith("category:"))
    dp.callback_query.register(skip_location, F.data.startswith("skip:"))
    dp.callback_query.register(finish_attachments, F.data == "attachments:done")
    dp.callback_query.register(cancel_callback, F.data == "form:cancel")

    # State-bound messages
    dp.message.register(status_code, Form.status_code)
    dp.message.register(region, Form.region)
    dp.message.register(district, Form.district)
    dp.message.register(description, Form.description)
    dp.message.register(upload_attachment, Form.attachments)

    print("Элдик Көзөмөл: Telegram-бот запущен.")
    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
