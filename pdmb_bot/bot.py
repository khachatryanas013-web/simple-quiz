# -*- coding: utf-8 -*-

import asyncio
import html
import logging
import os
from datetime import datetime
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


def parse_quiz_schedule() -> str:
    try:
        headers = {
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
        response = requests.get(
            "https://findquiz.ru/category/sport",
            headers=headers,
            timeout=20,
            verify=False,
        )
        response.raise_for_status()
        response.encoding = "utf-8"

        soup = BeautifulSoup(response.text, "html.parser")
        quiz_items = soup.find_all("li", class_="top")
        if not quiz_items:
            return "❌ На сайте не найдено ни одного квиза."

        weekday_map = {
            "ПН": "понедельник",
            "ВТ": "вторник",
            "СР": "среда",
            "ЧТ": "четверг",
            "ПТ": "пятница",
            "СБ": "суббота",
            "ВС": "воскресенье",
        }
        result = "🗓 <b>Расписание спортивных квизов</b>\n\n"
        count = 0

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
                    day_text = day_span.get_text(strip=True)
                    day_digits = "".join(char for char in day_text if char.isdigit())
                    day = day_digits or "?"
                    weekday_letters = "".join(
                        char for char in day_text if char.isalpha()
                    ).upper()
                    weekday = weekday_map.get(
                        weekday_letters,
                        weekday_letters.lower(),
                    )

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

            formatted_date = (
                f"{day} {month}, {weekday}, {time_text}"
                if weekday
                else f"{day} {month}, {time_text}"
            )
            location_link = item.find("a", class_="location-href")
            location = (
                location_link.get_text(strip=True)
                if location_link
                else "Место не указано"
            )
            price_text = "Цена не указана"
            for paragraph in desc_list:
                paragraph_text = paragraph.get_text(" ", strip=True)
                if "Цена" not in paragraph_text and "руб" not in paragraph_text:
                    continue
                price_span = paragraph.find("span", class_="info-text")
                if price_span:
                    price_text = price_span.get_text(strip=True)
                break

            count += 1
            result += f"<b>{count}. {name}</b>\n"
            result += f"🏢 Организатор: {org}\n"
            result += f"📅 {formatted_date}\n"
            result += f"📍 {location}\n"
            result += f"💰 {price_text}\n\n"
            if count >= 10:
                break

        if count == 0:
            return "❌ Не найдено ни одного спортивного квиза."
        return result + "⚽ Готов к спортивной баталии?"

    except requests.RequestException as error:
        logging.exception("Ошибка запроса к findquiz.ru")
        return f"❌ Ошибка при подключении к сайту: {error}"
    except Exception as error:
        logging.exception("Ошибка при парсинге расписания")
        return f"❌ Ошибка при парсинге: {error}"


async def send_quiz_schedule(chat_id: int = CHAT_ID, private: bool = False) -> None:
    message = await asyncio.to_thread(parse_quiz_schedule)
    await bot.send_message(
        chat_id=chat_id,
        text=message,
        parse_mode="HTML",
        reply_markup=await training_keyboard(private=private),
    )
    logging.info("Расписание отправлено в чат %s", chat_id)


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
                await send_quiz_schedule()
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
            types.BotCommand(command="help", description="Справка"),
        ]
    )
    logging.info("PDMB-бот запущен")


async def main() -> None:
    dispatcher.startup.register(on_startup)
    await dispatcher.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
