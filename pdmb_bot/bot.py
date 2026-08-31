# -*- coding: utf-8 -*-

import asyncio
import html
import logging
import os
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import requests
import urllib3
from aiogram import Bot, Dispatcher, F, types
from aiogram.enums import ChatType
from aiogram.exceptions import TelegramForbiddenError
from aiogram.filters import Command, CommandStart
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from training_data import build_training_questions


BASE_DIR = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(BASE_DIR, ".env"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID_RAW = os.getenv("CHAT_ID")
TRAINING_URL = os.getenv("TRAINING_URL")
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
SPORT_URL = "https://findquiz.ru/category/sport"

if not BOT_TOKEN:
    raise ValueError("Не найдена переменная BOT_TOKEN")
if not CHAT_ID_RAW:
    raise ValueError("Не найдена переменная CHAT_ID")
if not TRAINING_URL or not TRAINING_URL.startswith("https://"):
    raise ValueError("TRAINING_URL должен быть публичным адресом https://")

try:
    CHAT_ID = int(CHAT_ID_RAW)
except ValueError as error:
    raise ValueError("CHAT_ID должен быть числом") from error

bot = Bot(token=BOT_TOKEN)
dispatcher = Dispatcher()
training_sessions: dict[int, dict] = {}

WEEKDAY_MAP = {
    "ПН": "понедельник",
    "ВТ": "вторник",
    "СР": "среда",
    "ЧТ": "четверг",
    "ПТ": "пятница",
    "СБ": "суббота",
    "ВС": "воскресенье",
}

MONTH_MAP = {
    "янв": 1,
    "январь": 1,
    "января": 1,
    "фев": 2,
    "февраль": 2,
    "февраля": 2,
    "мар": 3,
    "март": 3,
    "марта": 3,
    "апр": 4,
    "апрель": 4,
    "апреля": 4,
    "май": 5,
    "мая": 5,
    "июн": 6,
    "июнь": 6,
    "июня": 6,
    "июл": 7,
    "июль": 7,
    "июля": 7,
    "авг": 8,
    "август": 8,
    "августа": 8,
    "сен": 9,
    "сент": 9,
    "сентябрь": 9,
    "сентября": 9,
    "окт": 10,
    "октябрь": 10,
    "октября": 10,
    "ноя": 11,
    "ноябрь": 11,
    "ноября": 11,
    "дек": 12,
    "декабрь": 12,
    "декабря": 12,
}


async def training_deep_link() -> str:
    me = await bot.get_me()
    return f"https://t.me/{me.username}?start=training"


async def training_keyboard(private: bool = False) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()

    if private:
        keyboard.add(
            InlineKeyboardButton(
                text="🧠 Тренировка в Telegram",
                callback_data="training:start",
            )
        )
    else:
        keyboard.add(
            InlineKeyboardButton(
                text="🧠 Тренировка в Telegram",
                url=await training_deep_link(),
            )
        )

    keyboard.add(
        InlineKeyboardButton(
            text="⚽ Открыть командный тренажёр",
            url=TRAINING_URL,
        )
    )
    return keyboard.as_markup()


def question_keyboard(question: dict) -> InlineKeyboardMarkup:
    keyboard = InlineKeyboardBuilder()
    for index, option in enumerate(question["options"]):
        keyboard.add(
            InlineKeyboardButton(
                text=f"{index + 1}. {option}",
                callback_data=f"training:answer:{index}",
            )
        )
    keyboard.adjust(1)
    return keyboard.as_markup()


def question_text(number: int, total: int, question: dict) -> str:
    return f"🧠 <b>Вопрос {number}/{total}</b>\n\n{html.escape(question['question'])}"


async def send_training_question(chat_id: int, user_id: int) -> None:
    session = training_sessions[user_id]
    question = session["questions"][session["index"]]
    await bot.send_message(
        chat_id=chat_id,
        text=question_text(session["index"] + 1, len(session["questions"]), question),
        parse_mode="HTML",
        reply_markup=question_keyboard(question),
    )


async def start_training(chat_id: int, user_id: int) -> None:
    training_sessions[user_id] = {
        "index": 0,
        "score": 0,
        "questions": build_training_questions(),
    }
    await bot.send_message(
        chat_id=chat_id,
        text=(
            "🧠 <b>Смешанная тренировка «Симпл Квиз»</b>\n"
            "Вопросы случайно собраны из всех разделов тренажёра. "
            "Выберите правильный ответ — в конце бот покажет результат."
        ),
        parse_mode="HTML",
    )
    await send_training_question(chat_id, user_id)


def request_headers() -> dict:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/128.0.0.0 Safari/537.36"
        ),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "ru,en;q=0.9",
        "Accept-Encoding": "gzip, deflate",
        "Connection": "keep-alive",
    }


def month_number(month_text: str) -> int | None:
    normalized = month_text.strip().lower().replace(".", "")
    if normalized in MONTH_MAP:
        return MONTH_MAP[normalized]

    for alias, number in MONTH_MAP.items():
        if len(alias) >= 3 and normalized.startswith(alias):
            return number
    return None


def resolve_event_date(day_text: str, month_text: str, reference: date | None = None) -> date | None:
    if not day_text.isdigit():
        return None

    month = month_number(month_text)
    if month is None:
        return None

    reference = reference or datetime.now(MOSCOW_TZ).date()
    day = int(day_text)

    try:
        candidate = date(reference.year, month, day)
    except ValueError:
        return None

    if candidate < reference - timedelta(days=180):
        candidate = date(reference.year + 1, month, day)
    elif candidate > reference + timedelta(days=180):
        candidate = date(reference.year - 1, month, day)

    return candidate


def fetch_quiz_events() -> list[dict]:
    response = requests.get(
        SPORT_URL,
        headers=request_headers(),
        timeout=20,
        verify=False,
    )
    response.raise_for_status()
    response.encoding = "utf-8"

    soup = BeautifulSoup(response.text, "html.parser")
    quiz_items = soup.find_all("li", class_="top")
    events: list[dict] = []

    for item in quiz_items:
        title_h2 = item.find("h2", class_="title")
        if not title_h2:
            continue

        name = title_h2.get_text(strip=True)
        org_span = item.find("span", class_="org")
        org = org_span.get_text(strip=True) if org_span else "Не указан"

        day, weekday, month = "?", "", "???"
        date_box = item.find("div", class_="date-small-box")
        if date_box:
            day_span = date_box.find("span", class_="date-small-date")
            if day_span:
                raw_day = day_span.get_text(strip=True)
                digits = "".join(char for char in raw_day if char.isdigit())
                day = digits or "?"
                letters = "".join(char for char in raw_day if char.isalpha()).upper()
                weekday = WEEKDAY_MAP.get(letters, letters.lower())

            month_span = date_box.find("span", class_="date-small-month1")
            if month_span:
                month = month_span.get_text(strip=True).lower()

        desc_list = item.find_all("p", class_="desc")
        time_text = "20:00"
        for paragraph in desc_list:
            if "Начало игры" not in paragraph.get_text(" ", strip=True):
                continue
            time_span = paragraph.find("span", class_="info-text")
            if time_span:
                parsed_time = time_span.get_text(strip=True).split()[0]
                if ":" in parsed_time:
                    time_text = parsed_time
            break

        location_link = item.find("a", class_="location-href")
        location = location_link.get_text(strip=True) if location_link else "Место не указано"

        price_text = "Цена не указана"
        for paragraph in desc_list:
            paragraph_text = paragraph.get_text(" ", strip=True)
            if "Цена" not in paragraph_text and "руб" not in paragraph_text:
                continue
            price_span = paragraph.find("span", class_="info-text")
            if price_span:
                price_text = price_span.get_text(strip=True)
            break

        formatted_date = (
            f"{day} {month}, {weekday}, {time_text}"
            if weekday
            else f"{day} {month}, {time_text}"
        )

        events.append(
            {
                "name": name,
                "org": org,
                "day": day,
                "month": month,
                "weekday": weekday,
                "time": time_text,
                "formatted_date": formatted_date,
                "event_date": resolve_event_date(day, month),
                "location": location,
                "price": price_text,
            }
        )

    return events


def format_quiz_schedule(events: list[dict]) -> str:
    if not events:
        return "❌ На сайте не найдено ни одного квиза."

    result = "🗓 <b>Расписание спортивных квизов</b>\n\n"
    for index, event in enumerate(events[:10], start=1):
        result += f"<b>{index}. {html.escape(event['name'])}</b>\n"
        result += f"🏢 Организатор: {html.escape(event['org'])}\n"
        result += f"📅 {html.escape(event['formatted_date'])}\n"
        result += f"📍 {html.escape(event['location'])}\n"
        result += f"💰 {html.escape(event['price'])}\n\n"

    return result + "⚽ Готов к спортивной баталии?"


def parse_quiz_schedule() -> str:
    try:
        return format_quiz_schedule(fetch_quiz_events())
    except requests.RequestException as error:
        logging.exception("Ошибка запроса к findquiz.ru")
        return f"❌ Ошибка при подключении к сайту: {html.escape(str(error))}"
    except Exception as error:
        logging.exception("Ошибка при парсинге расписания")
        return f"❌ Ошибка при парсинге: {html.escape(str(error))}"


def weekly_events(events: list[dict], reference: date | None = None) -> list[dict]:
    reference = reference or datetime.now(MOSCOW_TZ).date()
    week_start = reference - timedelta(days=reference.weekday())
    week_end = week_start + timedelta(days=6)

    result = [
        event
        for event in events
        if event.get("event_date") is not None
        and week_start <= event["event_date"] <= week_end
    ]

    return sorted(
        result,
        key=lambda event: (event["event_date"], event.get("time", "23:59"), event["name"]),
    )


def poll_option_text(event: dict) -> str:
    option = f"{event['event_date'].strftime('%d.%m')} {event['time']} — {event['name']}"
    if len(option) > 100:
        return option[:97].rstrip() + "..."
    return option


async def send_weekly_poll(
    events: list[dict],
    chat_id: int = CHAT_ID,
    reference: date | None = None,
) -> None:
    selected_events = weekly_events(events, reference=reference)
    if not selected_events:
        logging.info("На текущую неделю нет событий для опроса")
        return

    chunks = [selected_events[index:index + 11] for index in range(0, len(selected_events), 11)]
    total_parts = len(chunks)

    for part_number, chunk in enumerate(chunks, start=1):
        options = [poll_option_text(event) for event in chunk]
        options.append("❌ На этой неделе не иду" if total_parts == 1 else "❌ Ничего из этой части")

        question = "⚽ Кто куда идёт на квиз на этой неделе?"
        if total_parts > 1:
            question += f" Часть {part_number}/{total_parts}"

        await bot.send_poll(
            chat_id=chat_id,
            question=question,
            options=options,
            is_anonymous=False,
            allows_multiple_answers=True,
        )

    logging.info(
        "Опрос по посещению отправлен в чат %s: %s событий",
        chat_id,
        len(selected_events),
    )


async def send_quiz_schedule(
    chat_id: int = CHAT_ID,
    private: bool = False,
    events: list[dict] | None = None,
) -> list[dict]:
    if events is None:
        try:
            events = await asyncio.to_thread(fetch_quiz_events)
            message = format_quiz_schedule(events)
        except requests.RequestException as error:
            logging.exception("Ошибка запроса к findquiz.ru")
            events = []
            message = f"❌ Ошибка при подключении к сайту: {html.escape(str(error))}"
        except Exception as error:
            logging.exception("Ошибка при парсинге расписания")
            events = []
            message = f"❌ Ошибка при парсинге: {html.escape(str(error))}"
    else:
        message = format_quiz_schedule(events)

    await bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML",
        reply_markup=await training_keyboard(private=private),
    )
    logging.info("Расписание отправлено в чат %s", chat_id)
    return events


async def send_weekly_package() -> None:
    events = await asyncio.to_thread(fetch_quiz_events)
    await send_quiz_schedule(chat_id=CHAT_ID, private=False, events=events)
    await send_weekly_poll(events, chat_id=CHAT_ID)


@dispatcher.message(CommandStart())
async def handle_start(message: types.Message) -> None:
    if message.chat.type != ChatType.PRIVATE:
        return

    parts = (message.text or "").split(maxsplit=1)
    payload = parts[1].strip().lower() if len(parts) > 1 else ""

    if payload == "training":
        await start_training(message.chat.id, message.from_user.id)
        return

    await message.answer(
        "Бот показывает расписание спортивных квизов и открывает командный "
        "тренажёр.\n\n"
        "/training — открыть тренажёр\n"
        "/schedule — получить расписание",
        reply_markup=await training_keyboard(private=True),
    )


@dispatcher.message(Command("help"))
async def handle_help(message: types.Message) -> None:
    if message.chat.type != ChatType.PRIVATE:
        return

    await message.answer(
        "Бот показывает расписание спортивных квизов и открывает командный "
        "тренажёр.\n\n"
        "/training — открыть тренажёр\n"
        "/schedule — получить расписание",
        reply_markup=await training_keyboard(private=True),
    )


@dispatcher.message(Command("training", "trainer"))
async def handle_training(message: types.Message) -> None:
    if message.chat.type != ChatType.PRIVATE:
        try:
            await bot.send_message(
                chat_id=message.from_user.id,
                text=(
                    "Командный тренажёр «Симпл Квиз». Выберите формат:\n\n"
                    "🧠 тренировка прямо в Telegram с подсчётом результата;\n"
                    "⚽ HTML-версия с карточками по всем разделам."
                ),
                reply_markup=await training_keyboard(private=True),
            )
        except TelegramForbiddenError:
            logging.info(
                "Не удалось написать пользователю %s в личку: он ещё не запускал бота",
                message.from_user.id,
            )
        return

    await message.answer(
        "Командный тренажёр «Симпл Квиз». Выберите формат:\n\n"
        "🧠 тренировка прямо в Telegram с подсчётом результата;\n"
        "⚽ HTML-версия с карточками по всем разделам.",
        reply_markup=await training_keyboard(private=True),
    )


@dispatcher.callback_query(F.data == "training:start")
async def handle_training_start(callback: CallbackQuery) -> None:
    if callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer(
            "Тренировка запускается только в личном чате с ботом. Нажмите новую кнопку в расписании.",
            show_alert=True,
        )
        return

    user_id = callback.from_user.id
    await callback.answer("Тренировка началась")
    await start_training(callback.message.chat.id, user_id)


@dispatcher.callback_query(F.data.startswith("training:answer:"))
async def handle_training_answer(callback: CallbackQuery) -> None:
    if callback.message.chat.type != ChatType.PRIVATE:
        await callback.answer(
            "Ответы принимаются только в личном чате с ботом.",
            show_alert=True,
        )
        return

    user_id = callback.from_user.id
    session = training_sessions.get(user_id)
    if not session:
        await callback.answer("Запустите новую тренировку командой /training", show_alert=True)
        return

    selected = int(callback.data.rsplit(":", 1)[1])
    question = session["questions"][session["index"]]
    correct = selected == question["correct"]
    if correct:
        session["score"] += 1

    correct_answer = html.escape(question["options"][question["correct"]])
    result = "✅ Правильно!" if correct else f"❌ Неверно. Правильный ответ: {correct_answer}"
    source_note = (
        f"\n\n📚 Источник: {html.escape(question.get('source', 'не указан'))}"
        f"\nЛицензия: {html.escape(question.get('license', 'не указана'))}"
        f"\nПроверено: {html.escape(question.get('checked_at', 'не указано'))}"
    )
    await callback.answer("Правильно!" if correct else "Неверно")
    await callback.message.edit_text(
        f"{result}\n\n💡 {html.escape(question['explanation'])}{source_note}",
        parse_mode="HTML",
    )

    session["index"] += 1
    if session["index"] >= len(session["questions"]):
        score = session["score"]
        total = len(session["questions"])
        training_sessions.pop(user_id, None)
        await callback.message.answer(
            f"🏁 <b>Тренировка завершена</b>\n\n"
            f"Результат: <b>{score}/{total}</b>\n"
            f"HTML-версия доступна по кнопке ниже.",
            parse_mode="HTML",
            reply_markup=await training_keyboard(private=True),
        )
        return

    await send_training_question(callback.message.chat.id, user_id)


@dispatcher.message(Command("schedule"))
async def handle_schedule(message: types.Message) -> None:
    await send_quiz_schedule(
        message.chat.id,
        private=message.chat.type == ChatType.PRIVATE,
    )


@dispatcher.message(Command("weekpoll"))
async def handle_weekpoll(message: types.Message) -> None:
    try:
        events = await asyncio.to_thread(fetch_quiz_events)
        await send_weekly_poll(events, chat_id=message.chat.id)
    except Exception:
        logging.exception("Не удалось создать недельный опрос")
        await message.answer("❌ Не удалось создать опрос по расписанию.")


async def weekly_schedule_loop() -> None:
    last_sent_date = None
    while True:
        now = datetime.now(MOSCOW_TZ)
        if (
            now.weekday() == 0
            and now.hour == 10
            and now.minute == 0
            and last_sent_date != now.date()
        ):
            try:
                await send_weekly_package()
                last_sent_date = now.date()
            except Exception:
                logging.exception("Не удалось выполнить еженедельную рассылку")
        await asyncio.sleep(30)


async def on_startup() -> None:
    asyncio.create_task(weekly_schedule_loop())
    await bot.set_my_commands(
        [
            types.BotCommand(command="training", description="Открыть командный тренажёр"),
            types.BotCommand(command="schedule", description="Показать расписание квизов"),
            types.BotCommand(command="weekpoll", description="Создать опрос на эту неделю"),
            types.BotCommand(command="help", description="Справка"),
        ]
    )
    logging.info("PDMB-бот запущен")


async def main() -> None:
    dispatcher.startup.register(on_startup)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
