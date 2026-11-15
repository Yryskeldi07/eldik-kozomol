
import asyncio
import os
import httpx

from dotenv import load_dotenv

from aiogram import Bot, Dispatcher
from aiogram.filters import CommandStart, Command
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.context import FSMContext
from aiogram.fsm.storage.memory import MemoryStorage


# ==========================================
# CONFIGURATION
# ==========================================

load_dotenv()

TOKEN = os.getenv("BOT_TOKEN", "").strip()
API = os.getenv("API_BASE_URL", "http://localhost:8000").rstrip("/")

if not TOKEN:
    raise RuntimeError(
        "BOT_TOKEN не найден. Проверь файл .env в корне проекта."
    )


# ==========================================
# FORM STATES
# ==========================================

class Form(StatesGroup):
    language = State()
    category = State()
    region = State()
    district = State()
    description = State()


# ==========================================
# KEYBOARDS
# ==========================================

def language_keyboard():
    return ReplyKeyboardMarkup(
        keyboard=[
            [
                KeyboardButton(text="Русский"),
                KeyboardButton(text="Кыргызча")
            ]
        ],
        resize_keyboard=True,
        one_time_keyboard=True
    )


def category_keyboard(lang: str):
    if lang == "ky":
        buttons = [
            [KeyboardButton(text="Коррупция"), KeyboardButton(text="Кылмыш")],
            [KeyboardButton(text="Кызмат абалынан кыянаттык"), KeyboardButton(text="Киберкылмыштуулук")],
            [KeyboardButton(text="Башка")]
        ]
    else:
        buttons = [
            [KeyboardButton(text="Коррупция"), KeyboardButton(text="Преступление")],
            [KeyboardButton(text="Злоупотребление"), KeyboardButton(text="Киберпреступление")],
            [KeyboardButton(text="Другое")]
        ]

    return ReplyKeyboardMarkup(
        keyboard=buttons,
        resize_keyboard=True,
        one_time_keyboard=True
    )


# ==========================================
# START COMMAND
# ==========================================

LEGAL_WARNING = (
    "⚖️ ПРЕДУПРЕЖДЕНИЕ ОБ УГОЛОВНОЙ ОТВЕТСТВЕННОСТИ\n\n"
    "В соответствии со статьями 363–365 Уголовного кодекса Кыргызской Республики:\n\n"
    "Статья 363 — за заведомо ложное сообщение о совершении преступления предусмотрена уголовная ответственность.\n\n"
    "Статья 364 — за заведомо ложные показания свидетеля или потерпевшего, ложное заключение/показания эксперта, показания специалиста либо заведомо неправильный перевод в предусмотренных законом производствах предусмотрена уголовная ответственность.\n\n"
    "Статья 365 — за отказ или уклонение свидетеля или потерпевшего от дачи показаний, а эксперта — от дачи заключения или показаний в судебном заседании либо при досудебном производстве предусмотрена ответственность. Закон предусматривает исключения, в том числе право не свидетельствовать против себя, супруга(и) и близких родственников.\n\n"
    "Помните! Сообщайте только известные вам факты, отделяйте личные предположения от того, что вы видели или знаете. Не создавайте доказательства и не обвиняйте человека без фактических оснований.\n\n"
    "Это информационное предупреждение, а не юридическая консультация. Применимость норм зависит от обстоятельств и процессуального статуса лица."
)

async def start(message: Message, state: FSMContext):
    await state.clear()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Понимаю, продолжить", callback_data="warning_accept")],
        [InlineKeyboardButton(text="Отказаться", callback_data="warning_decline")]
    ])
    await message.answer(LEGAL_WARNING, reply_markup=kb)

async def warning_accept(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.answer(
        "Элдик Көзөмөл — независимый технический канал для сообщений о предполагаемых правонарушениях. Он не является официальной государственной приёмной и не гарантирует передачу сообщения государственному органу.\n\n"
        "Если человеку прямо сейчас угрожает опасность, обратитесь в экстренные службы.\n\n"
        "Важно: Telegram не гарантирует полной анонимности. Не указывайте имя, телефон, адрес и иные персональные данные, если раскрытие не требуется и вы не хотите их сообщать. Не отправляйте пароли и коды подтверждения.\n\n"
        "Выберите язык:", reply_markup=language_keyboard())
    await state.set_state(Form.language)

async def warning_decline(callback: CallbackQuery, state: FSMContext):
    await callback.answer()
    await state.clear()
    await callback.message.edit_text("Вы отказались продолжить. Чтобы начать заново, отправьте /start.")


# ==========================================
# LANGUAGE SELECTION
# ==========================================

async def language(message: Message, state: FSMContext):
    if message.text not in ["Русский", "Кыргызча"]:
        await message.answer("Выберите язык кнопкой.")
        return

    lang = "ky" if message.text == "Кыргызча" else "ru"

    await state.update_data(language=lang)

    if lang == "ky":
        await message.answer(
            "Кайрылуунун категориясын тандаңыз:",
            reply_markup=category_keyboard(lang)
        )
    else:
        await message.answer(
            "Выберите категорию обращения:",
            reply_markup=category_keyboard(lang)
        )

    await state.set_state(Form.category)


# ==========================================
# CATEGORY SELECTION
# ==========================================

async def category(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("language", "ru")

    if lang == "ky":
        mapping = {
            "Коррупция": "corruption",
            "Кылмыш": "crime",
            "Кызмат абалынан кыянаттык": "abuse",
            "Киберкылмыштуулук": "cybercrime",
            "Башка": "other"
        }
    else:
        mapping = {
            "Коррупция": "corruption",
            "Преступление": "crime",
            "Злоупотребление": "abuse",
            "Киберпреступление": "cybercrime",
            "Другое": "other"
        }

    if message.text not in mapping:
        await message.answer("Пожалуйста, выберите категорию кнопкой.")
        return

    await state.update_data(category=mapping[message.text])

    if lang == "ky":
        await message.answer(
            "Облус же шаарды көрсөтүңүз. Билбесеңиз, «Өткөрүп жиберүү» деп жазыңыз."
        )
    else:
        await message.answer(
            "Укажите область или город. Если не знаете, напишите «Пропустить»."
        )

    await state.set_state(Form.region)


# ==========================================
# REGION
# ==========================================

async def region(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("language", "ru")

    skip_words = ["пропустить", "өткөрүп жиберүү"]

    value = message.text.strip()

    if value.lower() in skip_words:
        value = None
    else:
        value = value[:100]

    await state.update_data(region=value)

    if lang == "ky":
        await message.answer(
            "Районду көрсөтүңүз же «Өткөрүп жиберүү» деп жазыңыз."
        )
    else:
        await message.answer(
            "Укажите район или напишите «Пропустить»."
        )

    await state.set_state(Form.district)


# ==========================================
# DISTRICT
# ==========================================

async def district(message: Message, state: FSMContext):
    data = await state.get_data()
    lang = data.get("language", "ru")

    skip_words = ["пропустить", "өткөрүп жиберүү"]

    value = message.text.strip()

    if value.lower() in skip_words:
        value = None
    else:
        value = value[:100]

    await state.update_data(district=value)

    if lang == "ky":
        await message.answer(
            "Окуяны толук сүрөттөп бериңиз. "
            "Кеминде 30 символ жазыңыз. "
            "Белгилүү фактыларды гана көрсөтүңүз."
        )
    else:
        await message.answer(
            "Опишите, что произошло. Минимум 30 символов. "
            "Сообщайте известные вам факты, не делая предположений о виновности."
        )

    await state.set_state(Form.description)


# ==========================================
# SUBMIT REPORT
# ==========================================

async def description(message: Message, state: FSMContext):
    if not message.text or len(message.text.strip()) < 30:
        await message.answer(
            "Добавьте подробности. Минимальная длина — 30 символов."
        )
        return

    data = await state.get_data()

    payload = {
        "language": data.get("language", "ru"),
        "category": data.get("category"),
        "region": data.get("region"),
        "district": data.get("district"),
        "description": message.text.strip()[:10000]
    }

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.post(
                f"{API}/api/v1/reports",
                json=payload
            )

            response.raise_for_status()
            result = response.json()

    except httpx.RequestError:
        await message.answer(
            "Не удалось подключиться к серверу. "
            "Попробуйте позже. Обращение не подтверждено как зарегистрированное."
        )
        await state.clear()
        return

    except httpx.HTTPStatusError:
        await message.answer(
            "Сервер не принял обращение. "
            "Попробуйте позже. Обращение не подтверждено как зарегистрированное."
        )
        await state.clear()
        return

    except (ValueError, KeyError):
        await message.answer(
            "Получен некорректный ответ сервера. "
            "Не удалось подтвердить регистрацию обращения."
        )
        await state.clear()
        return

    public_code = result.get("public_code")

    if not public_code:
        await message.answer(
            "Сервер не вернул номер обращения. "
            "Проверьте регистрацию через администратора."
        )
        await state.clear()
        return

    await message.answer(
        "Обращение зарегистрировано.\n\n"
        f"Номер: {public_code}\n\n"
        "Сохраните этот номер. Он понадобится для проверки статуса:\n"
        f"/status {public_code}"
    )

    await state.clear()


# ==========================================
# STATUS COMMAND
# ==========================================

async def check_status(message: Message):
    parts = (message.text or "").split(maxsplit=1)

    if len(parts) != 2:
        await message.answer(
            "Для проверки статуса используйте формат:\n"
            "/status EK-XXXXXXXXXX"
        )
        return

    public_code = parts[1].strip()

    if not public_code.startswith("EK-"):
        await message.answer("Неверный формат номера обращения.")
        return

    try:
        async with httpx.AsyncClient(timeout=10) as client:
            response = await client.get(
                f"{API}/api/v1/reports/{public_code}"
            )

        if response.status_code == 404:
            await message.answer("Обращение с таким номером не найдено.")

        elif response.is_success:
            result = response.json()

            await message.answer(
                f"Номер: {result.get('public_code')}\n"
                f"Статус: {result.get('status')}"
            )

        else:
            await message.answer("Сервис временно недоступен.")

    except httpx.RequestError:
        await message.answer(
            "Не удалось подключиться к серверу. Попробуйте позже."
        )


# ==========================================
# MAIN
# ==========================================

async def main():
    bot = Bot(token=TOKEN)

    dp = Dispatcher(storage=MemoryStorage())

    dp.message.register(start, CommandStart())
    dp.callback_query.register(warning_accept, lambda c: c.data == "warning_accept")
    dp.callback_query.register(warning_decline, lambda c: c.data == "warning_decline")
    dp.message.register(check_status, Command("status"))

    dp.message.register(language, Form.language)
    dp.message.register(category, Form.category)
    dp.message.register(region, Form.region)
    dp.message.register(district, Form.district)
    dp.message.register(description, Form.description)

    print("Элдик Көзөмөл: Telegram-бот запущен.")

    try:
        await dp.start_polling(bot)
    finally:
        await bot.session.close()


# ==========================================
# ENTRY POINT
# ==========================================

if __name__ == "__main__":
    asyncio.run(main())
