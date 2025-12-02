# bot.py
import asyncio
import os
import io
import zipfile
import json
import logging
from datetime import datetime
from functools import partial
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, BufferedInputFile
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
import aiosqlite
import google.generativeai as genai

# === ENV ===
load_dotenv()
TOKEN = os.getenv("TELEGRAM_TOKEN")
GEMINI_KEY = os.getenv("GEMINI_API_KEY")
ADMIN_GROUP_ID = int(os.getenv("ADMIN_GROUP_ID"))
DB_PATH = "support.db"

genai.configure(api_key=GEMINI_KEY)
model = genai.GenerativeModel(
    "gemini-1.5-flash",
    generation_config={"temperature": 0.2, "max_output_tokens": 2048}
)

logging.basicConfig(level=logging.INFO)
bot = Bot(token=TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
storage = MemoryStorage()
dp = Dispatcher(storage=storage)
router = Router()
dp.include_router(router)

# === DB ===
async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("PRAGMA journal_mode=WAL;")
        await db.execute("PRAGMA foreign_keys=ON;")
        
        await db.executescript("""
        CREATE TABLE IF NOT EXISTS users (tg_id INTEGER PRIMARY KEY, lang TEXT DEFAULT 'ru');
        CREATE TABLE IF NOT EXISTS tickets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ticket_number INTEGER UNIQUE,
            user_id INTEGER,
            status TEXT DEFAULT 'open',
            group_chat_id INTEGER,
            thread_id INTEGER,
            company TEXT,
            created_at TEXT,
            closed_at TEXT
        );
        CREATE TABLE IF NOT EXISTS steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE, 
            step_idx INTEGER, 
            text TEXT, 
            file_id TEXT, 
            file_type TEXT
        );
        CREATE TABLE IF NOT EXISTS logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT, 
            ticket_id INTEGER REFERENCES tickets(id) ON DELETE CASCADE, 
            from_type TEXT, 
            from_id INTEGER, 
            from_name TEXT, 
            text TEXT, 
            file_id TEXT, 
            msg_id INTEGER, 
            ts TEXT
        );
        """)
        await db.commit()

# === HELPERS ===
def fmt(num: int) -> str:
    return str(num).zfill(12)

async def get_ticket_number():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT MAX(ticket_number) FROM tickets") as cur:
            row = await cur.fetchone()
            next_num = (row[0] or 0) + 1
            if next_num > 999999999999:
                logging.warning("Ticket number overflow, resetting to 1")
                return 1
            return next_num

async def log_msg(ticket_id, from_type, from_id, from_name, text, file_id=None, msg_id=None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO logs (ticket_id, from_type, from_id, from_name, text, file_id, msg_id, ts) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                         (ticket_id, from_type, from_id, from_name, text, file_id, msg_id, datetime.now().isoformat()))
        await db.commit()

async def get_user_lang(user_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT lang FROM users WHERE tg_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "ru"

# === TRANSLATIONS ===
TRANSLATIONS = {
    "ru": {
        "choose_lang": "Выберите язык:",
        "manufacturer": "Введите название чита:",
        "step": "Шаг {idx}/7",
        "back": "Назад",
        "next": "Далее",
        "cancel": "Отмена",
        "edit": "Редактировать",
        "submit": "Отправить",
        "ticket_sent": "Тикет <b>#{num}</b> отправлен в поддержку!",
        "canceled": "Создание тикета отменено.",
        "existing_ticket": "У вас уже есть активный тикет <b>#{num}</b>. \nВы не можете создать новый, пока этот не будет закрыт поддержкой.",
        "ticket_closed_user_msg": "Ваш тикет <b>#{num}</b> был закрыт поддержкой.",
        "ticket_closed_admin_msg": "Тикет #{num} закрыт. Лог отправлен в General Chat.",
        "user_blocked": "Пользователь заблокировал бота. Тикет закрыт.",
        "ai_usage": "Использование: /ai <вопрос>",
        "no_ticket": "Нет активного тикета.",
        "ai_response_prefix": "<b>Ответ от ИИ:</b>\n\n",
        "ai_error": "Ошибка AI. Убедитесь, что ваш GEMINI_API_KEY действителен.",
        "help_feedback_sent": "Ваше сообщение отправлено администрации. Спасибо за обращение!",
        "help_usage": "Использование: /help <ваше сообщение>\n(Отправляет отзыв или вопрос администрации)",
        "export_manual_usage": "Использование: /export_ticket <номер тикета>",
        "export_not_found": "Тикет с таким номером не найден.",
        "export_log_caption": "Лог-файл для тикета #{num}",
        "general_closed_msg": "✅ Тикет <b>#{num}</b> закрыт администратором @{admin_username} (ID: {admin_id}).\nЛог-файл прикреплен."
    },
    "en": {
        "choose_lang": "Choose language:",
        "manufacturer": "Enter cheat name:",
        "step": "Step {idx}/7",
        "back": "Back",
        "next": "Next",
        "cancel": "Cancel",
        "edit": "Edit",
        "submit": "Submit",
        "ticket_sent": "Ticket <b>#{num}</b> sent to support!",
        "canceled": "Ticket creation canceled.",
        "existing_ticket": "You already have an active ticket <b>#{num}</b>. \nYou cannot create a new one until support closes this one.",
        "ticket_closed_user_msg": "Your ticket <b>#{num}</b> has been closed by support.",
        "ticket_closed_admin_msg": "Ticket #{num} closed. Log sent to General Chat.",
        "user_blocked": "User blocked the bot. Ticket closed.",
        "ai_usage": "Usage: /ai <question>",
        "no_ticket": "No active ticket.",
        "ai_response_prefix": "<b>AI Response:</b>\n\n",
        "ai_error": "AI error. Ensure your GEMINI_API_KEY is valid.",
        "help_feedback_sent": "Your message has been sent to the administration. Thank you!",
        "help_usage": "Usage: /help <your message>\n(Sends feedback or a question to the administration)",
        "export_manual_usage": "Usage: /export_ticket <ticket_number>",
        "export_not_found": "Ticket with this number not found.",
        "export_log_caption": "Log file for ticket #{num}",
        "general_closed_msg": "✅ Ticket <b>#{num}</b> closed by administrator @{admin_username} (ID: {admin_id}).\nLog file attached."
    },
    "another": {
        "choose_lang": "Choose language:",
        "manufacturer": "Enter manufacturer:",
        "step": "Step {idx}/7",
        "back": "Back",
        "next": "Next",
        "cancel": "Cancel",
        "edit": "Edit",
        "submit": "Submit",
        "ticket_sent": "Ticket <b>#{num}</b> sent to support!",
        "canceled": "Ticket creation canceled.",
        "existing_ticket": "You already have an active ticket <b>#{num}</b>. \nYou cannot create a new one until support closes this one.",
        "ticket_closed_user_msg": "Your ticket <b>#{num}</b> has been closed by support.",
        "ticket_closed_admin_msg": "Ticket #{num} closed. Log sent to General Chat.",
        "user_blocked": "User blocked the bot. Ticket closed.",
        "ai_usage": "Usage: /ai <question>",
        "no_ticket": "No active ticket.",
        "ai_response_prefix": "<b>AI Response:</b>\n\n",
        "ai_error": "AI error. Ensure your GEMINI_API_KEY is valid.",
        "help_feedback_sent": "Your message has been sent to the administration. Thank you!",
        "help_usage": "Usage: /help <your message>\n(Sends feedback or a question to the administration)",
        "export_manual_usage": "Usage: /export_ticket <ticket_number>",
        "export_not_found": "Ticket with this number not found.",
        "export_log_caption": "Log file for ticket #{num}",
        "general_closed_msg": "✅ Ticket <b>#{num}</b> closed by administrator @{admin_username} (ID: {admin_id}).\nLog file attached."
    }
}
STEPS = [
    ("О каком продукте идет речь?", "which product?", False),
    ("Игра", "Game", False),
    ("Версия Windows: пример - Windows 10 22h2 ", "Windows version, Ex: Windows 10 22h2 ", False),
    ("Опишите пожалуйста максимально детально вашу проблему", "Describe please your problem in details", False),
    ("Фото - ошибки/проблемы,msinfo32 и winver", "Photo - of error/problem, msinfo32 and winver", True),
    ("Видео проблемы - если проблема того требует", "Video of ur problem if needed", True),
    ("Вам ответят как можно скорее, если вы пишете с 7 утра до 9ти вечера по МСК", "You are gonna be answered as soon as it possible.", True),
]

# === FSM ===
class TicketForm(StatesGroup):
    choosing_lang = State()
    entering_company = State()
    filling_step = State()
    confirming = State()

# === HANDLERS ===
@router.message(Command("start"))
async def start(m: types.Message):
    await m.answer("""Добро пожаловать в ULTIMATE - место где ваша проблема важна и будет решена, если есть какие то вопросы или нужна помощь - откройте тикет /newticket .  
Время ожидания для получения помощи -  (если ночь в москве могут быть задержки с ответами)
Время в которое вам точно помогут: с 7 по москве до 9 по москве, если нужна помощь позже или раньше этого времени просто оставьте тикет - первый возможный админ вам ответит.
Если есть какие то проблемы или  подключиться к программе(стать партнером)  напишите мне в личные сообщения - контакты в описании

 Welcome to ULTIMATE - place where your problem important and will be solved, if u have any questions - open ticket by comand /newticket 
 .
Time to get help: as soon as possible (there may be delays in responses during the night in Moscow)
The time when you will definitely receive help: from 7 a.m. to 9 p.m. Moscow time. If you need help before or after this time, just leave a ticket and the first available admin will respond to you.
If you have any problems or want become a partner,  write to me in private messages, contacts in discription of the bot
""")



@router.message(Command("help"))
async def help_cmd(m: types.Message):
    user_lang = await get_user_lang(m.from_user.id)
    text = " ".join(m.text.split()[1:])
    
    if not text:
        return await m.answer(TRANSLATIONS[user_lang]["help_usage"])
    
    try:
        await bot.send_message(
            ADMIN_GROUP_ID, 
            f"<b>Новый фидбэк от @{m.from_user.username} (ID: {m.from_user.id})</b>\n\n{text}"
        )
        await m.answer(TRANSLATIONS[user_lang]["help_feedback_sent"])
    except Exception as e:
        logging.error(f"Could not send feedback: {e}")
        await m.answer("Ошибка отправки сообщения.")


@router.message(Command("newticket"))
async def newticket(m: types.Message, state: FSMContext):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT ticket_number FROM tickets WHERE user_id = ? AND status = 'open'", (m.from_user.id,)) as cur:
            row = await cur.fetchone()
            if row:
                user_lang = await get_user_lang(m.from_user.id)
                return await m.answer(TRANSLATIONS[user_lang]["existing_ticket"].format(num=fmt(row[0])))
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Русский 🇷🇺", callback_data="lang_ru")],
        [InlineKeyboardButton(text="English 🇬🇧", callback_data="lang_en")],
        [InlineKeyboardButton(text="Another / Другой", callback_data="lang_another")]
    ])
    await m.answer("Выберите язык / Choose language:", reply_markup=kb)
    await state.set_state(TicketForm.choosing_lang)

@router.callback_query(F.data.startswith("lang_"))
async def set_lang(q: types.CallbackQuery, state: FSMContext):
    lang = q.data.split("_")[1]
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO users (tg_id, lang) VALUES (?, ?) ON CONFLICT(tg_id) DO UPDATE SET lang = excluded.lang",
                         (q.from_user.id, lang))
        await db.commit()
        
    await state.update_data(lang=lang, step=0, data={}, files=[])
    
    display_lang = 'en' if lang == 'another' else lang
    
    await q.message.edit_text(TRANSLATIONS[display_lang]["manufacturer"])
    await state.set_state(TicketForm.entering_company)

@router.message(StateFilter(TicketForm.entering_company))
async def set_company(m: types.Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(company=m.text)
    await show_step(m, state, 0)

async def show_step(m: types.Message | types.CallbackQuery, state: FSMContext, step_idx: int):
    data = await state.get_data()
    lang = data["lang"]
    display_lang = 'en' if lang == 'another' else lang
    
    label = STEPS[step_idx][0 if display_lang == "ru" else 1]

    nav_buttons = []
    if step_idx > 0:
        nav_buttons.append(InlineKeyboardButton(text=TRANSLATIONS[display_lang]["back"], callback_data=f"step_{step_idx-1}"))
    
    nav_buttons.append(InlineKeyboardButton(text=TRANSLATIONS[display_lang]["next"], callback_data=f"step_{step_idx+1 if step_idx < 6 else 'confirm'}"))
    
    cancel_row = [InlineKeyboardButton(text=TRANSLATIONS[display_lang]["cancel"], callback_data="cancel")]
    
    kb = InlineKeyboardMarkup(inline_keyboard=[nav_buttons, cancel_row])

    text = f"{TRANSLATIONS[display_lang]['step'].format(idx=step_idx+1)}\n<b>{label}</b>"
    
    if isinstance(m, types.Message):
        await m.answer(text, reply_markup=kb)
    else:
        if m.message:
            await m.message.edit_text(text, reply_markup=kb)

    await state.update_data(step=step_idx)
    await state.set_state(TicketForm.filling_step)


@router.callback_query(F.data.startswith("step_"))
async def navigate_step(q: types.CallbackQuery, state: FSMContext):
    try:
        target = q.data.split("_")[1]
        if target == "confirm":
            await show_confirm(q, state, q.from_user)
            return
        step_idx = int(target)
        await show_step(q, state, step_idx)
    except: pass

def get_media_info(m: types.Message):
    if m.photo:
        return m.photo[-1].file_id, "photo", m.caption
    if m.video:
        return m.video.file_id, "video", m.caption
    if m.audio:
        return m.audio.file_id, "audio", m.caption
    if m.voice:
        return m.voice.file_id, "voice", m.caption
    if m.video_note:
        return m.video_note.file_id, "video_note", None
    if m.document:
        return m.document.file_id, "document", m.caption
    return None, None, m.text

@router.message(StateFilter(TicketForm.filling_step))
async def save_step(m: types.Message, state: FSMContext):
    data = await state.get_data()
    step_idx = data["step"]
    
    file_id, file_type, text_content = get_media_info(m)
    text = text_content or "[медиа]"
    
    step_data = data.get("step_data", {})
    step_data[step_idx] = {
        "text": text,
        "file_id": file_id,
        "file_type": file_type
    }
    
    await state.update_data(step_data=step_data)

    next_step_idx = step_idx + 1
    if next_step_idx < 7:
        await show_step(m, state, next_step_idx)
    else:
        await send_confirm_message(m, state, m.from_user)

async def get_confirm_payload(state: FSMContext, user: types.User = None):
    data = await state.get_data()
    lang = data["lang"]
    display_lang = 'en' if lang == 'another' else lang
    
    summary = ""
    # ИСПРАВЛЕНИЕ: Добавлена проверка на наличие username
    user_name = user.username if user and user.username else "без ника"
    user_id = user.id if user else "N/A"
    summary += f"<b>Пользователь:</b> @{user_name} (ID: <code>{user_id}</code>)\n"
    # КОНЕЦ ИСПРАВЛЕНИЯ
    summary += f"<b>Тикет:</b>\nФирма: {data['company']}\n\n"
    step_data = data.get("step_data", {})
    
    for i in range(7):
        step_info = step_data.get(i, {"text": "[не заполнено]", "file_id": None})
        text = step_info["text"]
        if step_info["file_id"]:
            text = f"[{step_info['file_type']}] {text}" if text != "[медиа]" else f"[{step_info['file_type']}]"
            
        label = STEPS[i][0 if display_lang == "ru" else 1]
        summary += f"{i+1}. {label}: {text}\n"
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=TRANSLATIONS[display_lang]["edit"], callback_data="edit"),
         InlineKeyboardButton(text=TRANSLATIONS[display_lang]["submit"], callback_data="submit")]
    ])
    return summary, kb

async def send_confirm_message(m: types.Message, state: FSMContext, user: types.User):
    summary, kb = await get_confirm_payload(state, user)
    await m.answer(summary, reply_markup=kb)
    await state.set_state(TicketForm.confirming)

async def show_confirm(q: types.CallbackQuery, state: FSMContext, user: types.User):
    summary, kb = await get_confirm_payload(state, user)
    await q.message.edit_text(summary, reply_markup=kb)
    await state.set_state(TicketForm.confirming)


@router.callback_query(F.data == "edit")
async def edit(q: types.CallbackQuery, state: FSMContext):
    await q.message.answer("Начинаем заново...")
    await newticket(q.message, state)
    try:
        await q.message.delete()
    except: pass

@router.callback_query(F.data == "submit")
async def submit(q: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    lang = data["lang"]
    display_lang = 'en' if lang == 'another' else lang
    
    number = await get_ticket_number()
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("INSERT INTO tickets (ticket_number, user_id, company, created_at, status) VALUES (?, ?, ?, ?, 'open')",
                         (number, q.from_user.id, data["company"], datetime.now().isoformat()))
        await db.commit()
        async with db.execute("SELECT last_insert_rowid()") as cur:
            ticket_id = (await cur.fetchone())[0]

        step_data = data.get("step_data", {})
        for i, step_info in step_data.items():
            await db.execute("INSERT INTO steps (ticket_id, step_idx, text, file_id, file_type) VALUES (?, ?, ?, ?, ?)",
                             (ticket_id, i, step_info["text"], step_info["file_id"], step_info["file_type"]))
        await db.commit()

    topic = await bot.create_forum_topic(ADMIN_GROUP_ID, name=f"#{fmt(number)} | {data['company']}")
    
    summary, _ = await get_confirm_payload(state, q.from_user) 
    
    await bot.send_message(ADMIN_GROUP_ID, summary, message_thread_id=topic.message_thread_id, parse_mode=ParseMode.HTML)
    
    step_data = data.get("step_data", {})
    for i, step_info in step_data.items():
        if step_info["file_id"]:
            label = STEPS[i][0 if display_lang == "ru" else 1]
            caption = f"Шаг {i+1}: {label}"
            file_id = step_info["file_id"]
            file_type = step_info["file_type"]
            
            try:
                sender = getattr(bot, f"send_{file_type}", None)
                if sender:
                    if file_type == "video_note":
                        await sender(ADMIN_GROUP_ID, file_id, message_thread_id=topic.message_thread_id)
                    else:
                        await sender(ADMIN_GROUP_ID, file_id, caption=caption, message_thread_id=topic.message_thread_id)
            except Exception as e:
                logging.error(f"Failed to send step media to topic: {e}")
                await bot.send_message(ADMIN_GROUP_ID, f"Не удалось отправить медиа (Шаг {i+1}): {e}", message_thread_id=topic.message_thread_id)


    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE tickets SET group_chat_id = ?, thread_id = ? WHERE id = ?", (ADMIN_GROUP_ID, topic.message_thread_id, ticket_id))
        await db.commit()
    
    await q.message.edit_text(TRANSLATIONS[display_lang]["ticket_sent"].format(num=fmt(number)))
    await state.clear()

@router.callback_query(F.data == "cancel")
async def cancel(q: types.CallbackQuery, state: FSMContext):
    lang = (await state.get_data()).get("lang", "ru")
    display_lang = 'en' if lang == 'another' else lang
    await state.clear()
    await q.message.edit_text(TRANSLATIONS[display_lang]["canceled"])


# === EXPORT (HELPER) ===
async def generate_export_file(ticket_id: int) -> tuple[io.BytesIO, str] | tuple[None, None]:
    """Собирает все данные тикета в читаемый текстовый лог."""
    
    export_data = {
        "ticket_info": None,
        "steps": [],
        "logs": []
    }
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        
        async with db.execute("SELECT * FROM tickets WHERE id = ?", (ticket_id,)) as cur:
            ticket_info = await cur.fetchone()
            if not ticket_info:
                return None, None
            export_data["ticket_info"] = dict(ticket_info)
            ticket_number = ticket_info["ticket_number"]

        async with db.execute("SELECT * FROM steps WHERE ticket_id = ? ORDER BY step_idx ASC", (ticket_id,)) as cur:
            export_data["steps"] = [dict(row) async for row in cur]
            
        async with db.execute("SELECT * FROM logs WHERE ticket_id = ? ORDER BY ts ASC", (ticket_id,)) as cur:
            export_data["logs"] = [dict(row) async for row in cur]

    # --- ИЗМЕНЕНИЕ: Формат лога на TXT ---
    try:
        log_content = io.StringIO()
        log_content.write(f"========= TICKET LOG #{fmt(ticket_number)} =========\n")
        
        info = export_data["ticket_info"]
        log_content.write(f"ID: {info['id']}\n")
        log_content.write(f"User ID: {info['user_id']}\n")
        log_content.write(f"Company/Cheat: {info['company']}\n")
        log_content.write(f"Created At: {info['created_at']}\n")
        log_content.write(f"Closed At: {info['closed_at'] or 'N/A'}\n")
        log_content.write("----------------------------------------\n")
        log_content.write("--- INITIAL STEPS ---\n")
        
        for i, step in enumerate(export_data["steps"]):
            label = STEPS[i][0] # RU label for log file
            media = f" [Media: {step['file_type']}]" if step['file_id'] else ""
            log_content.write(f"STEP {i+1} ({label}): {step['text']}{media}\n")
            
        log_content.write("----------------------------------------\n")
        log_content.write("--- CHAT LOG ---\n")
        
        for log in export_data["logs"]:
            time_str = datetime.fromisoformat(log['ts']).strftime("%Y-%m-%d %H:%M:%S")
            media_info = f" [File: {log['file_type']}]" if log['file_id'] else ""
            log_content.write(f"[{time_str}] ({log['from_type'].upper()} {log['from_name']}): {log['text']}{media_info}\n")

        file_io = io.BytesIO(log_content.getvalue().encode('utf-8'))
        filename = f"ticket_{fmt(ticket_number)}_log.txt"
        
        return file_io, filename
        
    except Exception as e:
        logging.error(f"Failed to create TXT log for ticket {ticket_id}: {e}")
        return None, None
    # --- КОНЕЦ ИЗМЕНЕНИЯ ---


# === COMMAND HANDLERS ===

@router.message(Command("close"), F.chat.type == "supergroup", F.message_thread_id)
async def close_ticket(m: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, ticket_number, user_id FROM tickets WHERE thread_id = ? AND status = 'open'", (m.message_thread_id,)) as cur:
            row = await cur.fetchone()
            if not row: 
                return await m.answer("Ticket not found or already closed.")
            tid, number, user_id = row
            
        await log_msg(tid, "system", m.from_user.id, m.from_user.full_name, f"Ticket closed by support user {m.from_user.full_name}", msg_id=m.message_id)

        # --- ИЗМЕНЕНИЕ: ОТПРАВКА В GENERAL CHAT ---
        file_io, filename = await generate_export_file(tid)
        
        admin_username = m.from_user.username or f"ID {m.from_user.id}"
        general_closed_msg = TRANSLATIONS["ru"]["general_closed_msg"].format(
            num=fmt(number), 
            admin_username=admin_username,
            admin_id=m.from_user.id
        )

        if file_io and filename:
            try:
                # Отправляем лог и уведомление в General Chat (message_thread_id=None)
                await bot.send_document(
                    ADMIN_GROUP_ID,
                    BufferedInputFile(file_io.getvalue(), filename=filename),
                    caption=general_closed_msg,
                    message_thread_id=None 
                )
            except Exception as e:
                logging.error(f"Failed to send log file to General Chat for ticket {number}: {e}")
                # Отправляем в тему, если не получилось в General Chat
                await m.answer(f"Warning: Failed to send log file to General Chat: {e}. Sending log to current topic.")
                if file_io:
                    await bot.send_document(
                        ADMIN_GROUP_ID,
                        BufferedInputFile(file_io.getvalue(), filename=filename),
                        caption=TRANSLATIONS['ru']['export_log_caption'].format(num=fmt(number)),
                        message_thread_id=m.message_thread_id
                    )
        else:
            await bot.send_message(ADMIN_GROUP_ID, general_closed_msg + "\n(Warning: Could not generate log file.)", message_thread_id=None)
        # --- КОНЕЦ ИЗМЕНЕНИЯ ---

        await db.execute("UPDATE tickets SET status = 'closed', closed_at = ? WHERE id = ?", (datetime.now().isoformat(), tid))
        await db.commit()
    
    # Уведомление в теме о том, что тикет закрыт
    await m.answer(TRANSLATIONS["ru"]["ticket_closed_admin_msg"].format(num=fmt(number)))
    
    try:
        bilingual_message = (
            f"{TRANSLATIONS['ru']['ticket_closed_user_msg'].format(num=fmt(number))}\n"
            "---"
            f"\n{TRANSLATIONS['en']['ticket_closed_user_msg'].format(num=fmt(number))}"
        )
        await bot.send_message(user_id, bilingual_message)
    except TelegramForbiddenError:
        pass 
    except Exception as e:
        logging.warning(f"Couldn't send close message to user {user_id}: {e}")
        
    try:
        # Удаляем тему после всех действий
        await bot.delete_forum_topic(ADMIN_GROUP_ID, m.message_thread_id)
    except TelegramBadRequest as e:
        logging.error(f"Could not delete forum topic {m.message_thread_id}: {e}")
        await m.answer(f"Не удалось удалить тему (возможно, уже удалена): {e}")


@router.message(Command("ai"))
async def ai_cmd(m: types.Message):
    question = " ".join(m.text.split()[1:])
    user_lang = await get_user_lang(m.from_user.id)
    
    if not question:
        return await m.answer(TRANSLATIONS[user_lang]["ai_usage"])

    ticket_id, company, number, thread_id, user_id = None, None, None, None, None
    
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        row = None
        
        if m.chat.type == "supergroup" and m.message_thread_id:
            async with db.execute("SELECT id, user_id, company, ticket_number, thread_id FROM tickets WHERE thread_id = ?", (m.message_thread_id,)) as cur:
                row = await cur.fetchone()
        
        elif m.chat.type == "private":
            async with db.execute("SELECT id, user_id, company, ticket_number, thread_id FROM tickets WHERE user_id = ? AND status = 'open'", (m.from_user.id,)) as cur:
                row = await cur.fetchone()
        
        if not row:
            return await m.answer(TRANSLATIONS[user_lang]["no_ticket"])
        
        row_dict = dict(row)
        ticket_id = row_dict["id"]
        company = row_dict["company"]
        number = row_dict["ticket_number"]
        thread_id = row_dict["thread_id"]
        user_id = row_dict["user_id"]
        
        chat_history = []
        # Получаем шаги тикета для первоначального контекста
        async with db.execute("SELECT step_idx, text, file_type FROM steps WHERE ticket_id = ? ORDER BY step_idx ASC", (ticket_id,)) as step_cur:
            async for step_row in step_cur:
                label = STEPS[step_row[0]][0] # RU label
                media_info = f" [Медиа: {step_row[2]}]" if step_row[2] else ""
                chat_history.append(f"INITIAL STEP ({label}): {step_row[1]}{media_info}")
        
        # Получаем историю чата
        async with db.execute("SELECT from_type, from_name, text FROM logs WHERE ticket_id = ? ORDER BY ts DESC LIMIT 15", (ticket_id,)) as log_cur:
            async for log_row in log_cur:
                # Меняем 'support' и 'system' на 'Support'
                role = "User" if log_row[0] == "user" else "Support"
                chat_history.append(f"{role} ({log_row[1]}): {log_row[2]}")
    
    history_context = "\n".join(reversed(chat_history))

    # --- ИСПРАВЛЕНИЕ / AI ERROR: Улучшенный промпт ---
    prompt = (
        f"Ты - агент поддержки, использующий Gemini. Тикет #{fmt(number)} по продукту/читу '{company}'. "
        "Твоя задача — дать точный и детальный ответ на последний вопрос, используя всю предоставленную историю. "
        "Сохраняй нейтральный и профессиональный тон, отвечай на том же языке, что и вопрос. "
        "================================================\n"
        "ТЕКУЩИЙ ВОПРОС: {question}\n"
        "================================================\n"
        "ИСТОРИЯ ТИКЕТА:\n{history_context}\n"
    ).format(question=question, history_context=history_context)
    # --- КОНЕЦ ИСПРАВЛЕНИЯ / AI ERROR ---
    
    try:
        response = await model.generate_content_async(prompt)
        ai_response_text = response.text
        
        # Логирование происходит в любом случае (private или supergroup)
        log_username = m.from_user.full_name
        log_from_type = "system"
        
        # Отправка ответа пользователю (в чат или в топик)
        if m.chat.type == "supergroup":
            await m.answer(TRANSLATIONS['ru']["ai_response_prefix"] + ai_response_text)
            log_username = f"AI (via {m.from_user.full_name})"

        elif m.chat.type == "private":
            await m.answer(TRANSLATIONS[user_lang]["ai_response_prefix"] + ai_response_text)
            log_username = "AI (via User)"
            
            # Отправка лога в топик для администраторов
            if thread_id:
                user_name = m.from_user.username or "без ника"
                await bot.send_message(
                    ADMIN_GROUP_ID,
                    f"<b>Пользователь @{user_name} (ID: {m.from_user.id}) использовал /ai.</b>\n\n"
                    f"<b>Вопрос:</b> {question}\n"
                    f"<b>Ответ ИИ (отправлен пользователю):</b>\n{ai_response_text}",
                    message_thread_id=thread_id
                )

        # Логируем ответ AI
        await log_msg(ticket_id, log_from_type, m.from_user.id, log_username, ai_response_text, msg_id=m.message_id)

    except Exception as e:
        logging.error(f"AI Error: {e}")
        await m.answer(TRANSLATIONS[user_lang]["ai_error"])


@router.message(Command("export_ticket"), F.chat.type == "supergroup", F.message_thread_id)
async def export_manual(m: types.Message):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, ticket_number FROM tickets WHERE thread_id = ?", (m.message_thread_id,)) as cur:
            row = await cur.fetchone()
            if not row:
                return await m.answer(TRANSLATIONS['ru']["export_not_found"])
            tid, number = row

    file_io, filename = await generate_export_file(tid)
    
    if file_io and filename:
        try:
            # Ручной экспорт всегда идет в текущую тему
            await bot.send_document(
                ADMIN_GROUP_ID,
                BufferedInputFile(file_io.getvalue(), filename=filename),
                caption=TRANSLATIONS['ru']['export_log_caption'].format(num=fmt(number)),
                message_thread_id=m.message_thread_id
            )
        except Exception as e:
            logging.error(f"Failed to send manual log file for ticket {number}: {e}")
            await m.answer(f"Warning: Failed to send log file: {e}")
    else:
        await m.answer("Warning: Could not generate log file.")


# === GENERAL MESSAGE HANDLERS ===
# (ОНИ ДОЛЖНЫ БЫТЬ В САМОМ КОНЦЕ, ПОСЛЕ КОМАНД)

@router.message(F.chat.type == "supergroup", F.message_thread_id)
async def group_to_user(m: types.Message):
    # Игнорируем команды в топике, чтобы они не пересылались юзеру
    if m.text and m.text.startswith("/"):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, user_id FROM tickets WHERE thread_id = ? AND status = 'open'", (m.message_thread_id,)) as cur:
            row = await cur.fetchone()
            if not row: return
            ticket_id, user_id = row
    
    try:
        file_id, file_type, text_content = get_media_info(m)
        caption = f"<b>Support:</b> {text_content or ''}"
        
        sender = getattr(bot, f"send_{file_type}", None)
        if sender:
            if file_type == "video_note":
                await sender(user_id, file_id)
            else:
                await sender(user_id, file_id, caption=caption)
        elif m.text:
            await bot.send_message(user_id, f"<b>Support:</b> {m.text}")
        
        log_text = text_content or "[медиа]"
        await log_msg(ticket_id, "support", m.from_user.id, m.from_user.full_name, log_text, file_id, m.message_id)

    except TelegramForbiddenError:
        user_lang = await get_user_lang(user_id)
        display_lang = 'en' if user_lang == 'another' else user_lang
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute("UPDATE tickets SET status = 'user_blocked', closed_at = ? WHERE id = ?", (datetime.now().isoformat(), ticket_id))
            await db.commit()
        
        await bot.send_message(ADMIN_GROUP_ID, TRANSLATIONS[display_lang]["user_blocked"], message_thread_id=m.message_thread_id)
        await log_msg(ticket_id, "system", bot.id, "Bot", "User blocked the bot. Ticket closed automatically.", msg_id=m.message_id)
    except Exception as e:
        logging.error(f"Error in group_to_user: {e}")

@router.message(F.chat.type == "private", ~StateFilter(TicketForm.filling_step, TicketForm.entering_company))
async def user_to_group(m: types.Message):
    # Игнорируем команды, они обрабатываются отдельно
    if m.text and m.text.startswith("/"):
        return

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT id, thread_id FROM tickets WHERE user_id = ? AND status = 'open'", (m.from_user.id,)) as cur:
            row = await cur.fetchone()
            if not row: 
                return
            ticket_id, thread_id = row
    
    try:
        file_id, file_type, text_content = get_media_info(m)
        caption = f"<b>User:</b> {text_content or ''}"

        sender = getattr(bot, f"send_{file_type}", None)
        if sender:
            if file_type == "video_note":
                await sender(ADMIN_GROUP_ID, file_id, message_thread_id=thread_id)
            else:
                await sender(ADMIN_GROUP_ID, file_id, caption=caption, message_thread_id=thread_id)
        elif m.text:
            await bot.send_message(ADMIN_GROUP_ID, f"<b>User:</b> {m.text}", message_thread_id=thread_id)
        
        log_text = text_content or "[медиа]"
        await log_msg(ticket_id, "user", m.from_user.id, m.from_user.full_name, log_text, file_id, m.message_id)
        
    except Exception as e:
        logging.error(f"Error in user_to_group: {e}")
        await m.answer("Не удалось доставить сообщение. Возможно, тикет был закрыт.")


# === MAIN ===
async def main():
    await init_db()
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())