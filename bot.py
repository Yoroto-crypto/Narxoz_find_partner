"""
Narxoz Team Finder — Telegram-бот для поиска сокомандников
(дипломы, курсовые, хакатоны, стартап-идеи).

Как это работает:
- /start        — выбрать язык интерфейса, затем создать/обновить анкету
- /browse       — листать анкеты других людей (кнопки "дальше")
- /find <тег>   — найти анкеты, где есть совпадение по навыку/направлению/языку
- /myprofile    — посмотреть свою анкету (кнопки статуса и удаления)
- /found        — отметить, что команда уже найдена (анкета скрывается из ленты)
- /reopen       — вернуть анкету в ленту поиска
- /delete       — удалить свою анкету навсегда
- /language     — сменить язык интерфейса бота в любой момент
- /export       — (только для админа) прислать файл базы данных целиком
- /import       — (только для админа) восстановить базу из присланного файла

Хранилище: локальный SQLite-файл (team_finder.db), создаётся автоматически.
Нужен токен бота от @BotFather. Опционально: ADMIN_USER_ID — твой Telegram
user id, чтобы только ты мог выгружать базу через /export (см. README).
"""

import asyncio
import logging
import os
import sqlite3
from contextlib import closing

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    CallbackQuery,
    FSInputFile,
)

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("team_finder")

BOT_TOKEN = os.environ.get("BOT_TOKEN", "PUT_YOUR_TOKEN_HERE")
# DB_DIR можно задать переменной окружения и указать на смонтированный
# постоянный диск (Railway Volume) — иначе при каждом передеплое файл
# базы будет создаваться заново в пустой файловой системе контейнера.
DB_DIR = os.environ.get("DB_DIR", os.path.dirname(__file__))
DB_PATH = os.path.join(DB_DIR, "team_finder.db")
ADMIN_USER_ID = os.environ.get("ADMIN_USER_ID")  # твой Telegram user id, строкой

router = Router()

DEFAULT_UI_LANG = "ru"


# ---------- i18n ----------
# Языки интерфейса бота (кнопки, подписи, подсказки). Отдельно от поля
# "язык общения в команде" в самой анкете — это два разных выбора.

UI_LANG_NAMES = {"ru": "Русский", "kz": "Қазақша", "en": "English"}

TEXT = {
    "ru": {
        "choose_ui_lang": "🌐 Выберите язык бота / Тілді таңдаңыз / Choose bot language:",
        "intro": (
            "Привет! Это Narxoz Team Finder — площадка для поиска сокомандников "
            "(дипломы, курсовые, хакатоны, стартап-идеи).\n\n"
            "Заполните короткую анкету — 5 вопросов.\n\n"
            "Как вас зовут и какой курс?"
        ),
        "ask_major": "Специальность/направление?",
        "ask_topic": (
            "Тема диплома/курсовой/проекта, под который ищете команду "
            "(или просто область интересов, если темы пока нет)?"
        ),
        "ask_skills": "Какие у вас навыки? (через запятую: python, sql, дизайн, аналитика...)",
        "ask_looking_for": "Кого ищете в команду? (роли/навыки, которых не хватает)",
        "ask_comm_lang": "На каком языке вам удобнее общаться в команде?",
        "not_important": "Не принципиально",
        "saved_intro": "Готово! Ваша анкета опубликована:",
        "commands_hint": (
            "Команды: /browse — смотреть другие анкеты, /find <слово> — поиск по навыку/языку, "
            "/myprofile — своя анкета (там же кнопки статуса), /found — отметить, что нашли команду, "
            "/reopen — вернуться в поиск, /delete — удалить анкету, /language — сменить язык бота."
        ),
        "browse_empty": "Пока анкет нет. Будьте первым, кто позовёт друзей 🙂",
        "browse_none_left": "Анкет больше нет.",
        "browse_header": "Анкета {i}/{n}",
        "find_usage": "Использование: /find <слово>, например /find python",
        "find_none": "По запросу «{tag}» никого не нашлось.",
        "find_header": "Найдено анкет: {n} по запросу «{tag}»",
        "no_profile": "У вас ещё нет анкеты. Наберите /start, чтобы создать.",
        "no_profile_short": "У вас ещё нет анкеты.",
        "profile_deleted": "Анкета удалена. Можете создать новую через /start.",
        "found_toast": "Анкета скрыта из ленты. Удачи с командой!",
        "found_msg": "Отмечено: анкета скрыта из ленты. Вернуть — /reopen. Удачи с командой! 🎉",
        "reopen_toast": "Анкета снова видна в ленте.",
        "reopen_msg": "Готово: анкета снова видна в ленте.",
        "found_status_line": "✅ Уже нашёл(-ла) команду\n",
        "btn_mark_found": "✅ Нашёл(-ла) команду",
        "btn_reopen": "🔄 Снова в поиске",
        "btn_delete": "🗑 Удалить анкету",
        "btn_back": "◀️ Назад",
        "btn_next": "Дальше ▶️",
        "lbl_name": "👤",
        "lbl_major": "🎓",
        "lbl_topic": "📌 Тема/проект:",
        "lbl_skills": "🛠 Навыки:",
        "lbl_looking_for": "🔍 Ищет:",
        "lbl_language": "🗣 Язык общения:",
        "lbl_contact": "✉️ Контакт:",
        "no_username": "(нет username, напишите через профиль Telegram)",
        "lang_changed": "Язык бота изменён на Русский.",
        "fallback_hint": "Не совсем понял 🙂 Если ответ не подошёл — наберите /start, чтобы продолжить или начать заново.",
        "export_denied": "Эта команда доступна только администратору бота.",
        "export_caption": "База данных на {time}",
        "ask_contact_method": "Как с вами лучше связаться?",
        "btn_contact_telegram": "Telegram (@username)",
        "btn_contact_phone": "📞 Номер телефона",
        "btn_contact_email": "✉️ Email",
        "no_username_notice": (
            "У вас не задан username в Telegram (Настройки Telegram → Изменить профиль → Имя пользователя). "
            "Выберите другой способ связи:"
        ),
        "ask_phone": "Введите номер телефона:",
        "ask_email": "Введите email:",
        "import_prompt": "Пришлите файл team_finder.db следующим сообщением (как документ), чтобы восстановить базу.",
        "import_denied": "Эта команда доступна только администратору бота.",
        "import_done": "База данных восстановлена из присланного файла.",
        "import_wrong_file": "Нужно прислать именно файл (документ), не фото и не текст.",
    },
    "kz": {
        "choose_ui_lang": "🌐 Выберите язык бота / Тілді таңдаңыз / Choose bot language:",
        "intro": (
            "Сәлем! Бұл Narxoz Team Finder — дипломға, курстық жұмысқа, хакатонға немесе "
            "стартап-идеяға серіктес табуға арналған алаң.\n\n"
            "Қысқа анкета толтырыңыз — 5 сұрақ.\n\n"
            "Атыңыз және курсыңыз қандай?"
        ),
        "ask_major": "Мамандығыңыз/бағытыңыз қандай?",
        "ask_topic": (
            "Команда іздеп жатқан диплом/курстық/жоба тақырыбы "
            "(тақырып әлі жоқ болса — қызығушылық саласын жазыңыз)?"
        ),
        "ask_skills": "Қандай дағдыларыңыз бар? (үтірмен: python, sql, дизайн, аналитика...)",
        "ask_looking_for": "Командаға кімді іздейсіз? (жетіспейтін рөлдер/дағдылар)",
        "ask_comm_lang": "Командада қай тілде сөйлескен ыңғайлы?",
        "not_important": "Бәрібір",
        "saved_intro": "Дайын! Анкетаңыз жарияланды:",
        "commands_hint": (
            "Командалар: /browse — басқа анкеталарды қарау, /find <сөз> — дағды/тіл бойынша іздеу, "
            "/myprofile — өз анкетаңыз (статус батырмалары да сонда), /found — команда табылды деп белгілеу, "
            "/reopen — іздеуге қайту, /delete — анкетаны өшіру, /language — бот тілін ауыстыру."
        ),
        "browse_empty": "Әзірге анкеталар жоқ. Достарыңызды шақырған алғашқы адам болыңыз 🙂",
        "browse_none_left": "Басқа анкета қалмады.",
        "browse_header": "Анкета {i}/{n}",
        "find_usage": "Қолданылуы: /find <сөз>, мысалы /find python",
        "find_none": "«{tag}» бойынша ешкім табылмады.",
        "find_header": "«{tag}» бойынша табылған анкета: {n}",
        "no_profile": "Сізде әлі анкета жоқ. Жасау үшін /start теріңіз.",
        "no_profile_short": "Сізде әлі анкета жоқ.",
        "profile_deleted": "Анкета өшірілді. /start арқылы жаңасын жасай аласыз.",
        "found_toast": "Анкета таспадан жасырылды. Командамен сәттілік!",
        "found_msg": "Белгіленді: анкета таспадан жасырылды. Қайтару — /reopen. Сәттілік! 🎉",
        "reopen_toast": "Анкета таспада қайта көрінеді.",
        "reopen_msg": "Дайын: анкета таспада қайта көрінеді.",
        "found_status_line": "✅ Команда табылды\n",
        "btn_mark_found": "✅ Команда табылды",
        "btn_reopen": "🔄 Қайта іздеуде",
        "btn_delete": "🗑 Анкетаны өшіру",
        "btn_back": "◀️ Артқа",
        "btn_next": "Келесі ▶️",
        "lbl_name": "👤",
        "lbl_major": "🎓",
        "lbl_topic": "📌 Тақырып/жоба:",
        "lbl_skills": "🛠 Дағдылар:",
        "lbl_looking_for": "🔍 Іздейді:",
        "lbl_language": "🗣 Сөйлесу тілі:",
        "lbl_contact": "✉️ Байланыс:",
        "no_username": "(username жоқ, Telegram профилі арқылы жазыңыз)",
        "lang_changed": "Бот тілі қазақшаға ауыстырылды.",
        "fallback_hint": "Түсінбедім 🙂 Жауап сәйкес келмесе — жалғастыру немесе қайта бастау үшін /start теріңіз.",
        "export_denied": "Бұл команда тек бот әкімшісіне қолжетімді.",
        "export_caption": "Дерекқор ({time} бойынша)",
        "ask_contact_method": "Сізбен байланысудың қай тәсілі ыңғайлы?",
        "btn_contact_telegram": "Telegram (@username)",
        "btn_contact_phone": "📞 Телефон нөірі",
        "btn_contact_email": "✉️ Email",
        "no_username_notice": (
            "Telegram-да username орнатылмаған (Telegram баптаулары → Профильді өзгерту → Username). "
            "Басқа байланыс тәсілін таңдаңыз:"
        ),
        "ask_phone": "Телефон нөмірін енгізіңіз:",
        "ask_email": "Email енгізіңіз:",
        "import_prompt": "Дерекқорды қалпына келтіру үшін team_finder.db файлын келесі хабарламада (құжат ретінде) жіберіңіз.",
        "import_denied": "Бұл команда тек бот әкімшісіне қолжетімді.",
        "import_done": "Дерекқор жіберілген файлдан қалпына келтірілді.",
        "import_wrong_file": "Дәл файл (құжат) жіберу керек, фото немесе мәтін емес.",
    },
    "en": {
        "choose_ui_lang": "🌐 Выберите язык бота / Тілді таңдаңыз / Choose bot language:",
        "intro": (
            "Hi! This is Narxoz Team Finder — a place to find teammates "
            "(thesis, coursework, hackathons, startup ideas).\n\n"
            "Fill in a short profile — 5 questions.\n\n"
            "What's your name and year of study?"
        ),
        "ask_major": "What's your major/field of study?",
        "ask_topic": (
            "The thesis/coursework/project topic you're looking for teammates for "
            "(or just your area of interest, if there's no topic yet)?"
        ),
        "ask_skills": "What are your skills? (comma-separated: python, sql, design, analytics...)",
        "ask_looking_for": "Who are you looking for on the team? (missing roles/skills)",
        "ask_comm_lang": "Which language are you most comfortable communicating in?",
        "not_important": "Doesn't matter",
        "saved_intro": "Done! Your profile is now published:",
        "commands_hint": (
            "Commands: /browse — see other profiles, /find <word> — search by skill/language, "
            "/myprofile — your profile (status buttons are there too), /found — mark team found, "
            "/reopen — back to searching, /delete — delete your profile, /language — change bot language."
        ),
        "browse_empty": "No profiles yet. Be the first to invite your friends 🙂",
        "browse_none_left": "No more profiles.",
        "browse_header": "Profile {i}/{n}",
        "find_usage": "Usage: /find <word>, e.g. /find python",
        "find_none": "No one found for «{tag}».",
        "find_header": "Found {n} profile(s) for «{tag}»",
        "no_profile": "You don't have a profile yet. Type /start to create one.",
        "no_profile_short": "You don't have a profile yet.",
        "profile_deleted": "Profile deleted. You can create a new one with /start.",
        "found_toast": "Profile hidden from the feed. Good luck with the team!",
        "found_msg": "Marked: your profile is hidden from the feed. To undo — /reopen. Good luck! 🎉",
        "reopen_toast": "Profile is visible in the feed again.",
        "reopen_msg": "Done: your profile is visible in the feed again.",
        "found_status_line": "✅ Already found a team\n",
        "btn_mark_found": "✅ Found a team",
        "btn_reopen": "🔄 Searching again",
        "btn_delete": "🗑 Delete profile",
        "btn_back": "◀️ Back",
        "btn_next": "Next ▶️",
        "lbl_name": "👤",
        "lbl_major": "🎓",
        "lbl_topic": "📌 Topic/project:",
        "lbl_skills": "🛠 Skills:",
        "lbl_looking_for": "🔍 Looking for:",
        "lbl_language": "🗣 Communication language:",
        "lbl_contact": "✉️ Contact:",
        "no_username": "(no username, message via their Telegram profile)",
        "lang_changed": "Bot language changed to English.",
        "fallback_hint": "Didn't quite catch that 🙂 If your answer didn't fit, type /start to continue or restart.",
        "export_denied": "This command is only available to the bot admin.",
        "export_caption": "Database as of {time}",
        "ask_contact_method": "What's the best way to reach you?",
        "btn_contact_telegram": "Telegram (@username)",
        "btn_contact_phone": "📞 Phone number",
        "btn_contact_email": "✉️ Email",
        "no_username_notice": (
            "You don't have a Telegram username set (Telegram Settings → Edit Profile → Username). "
            "Choose another way to be contacted:"
        ),
        "ask_phone": "Enter your phone number:",
        "ask_email": "Enter your email:",
        "import_prompt": "Send the team_finder.db file as a document in your next message to restore the database.",
        "import_denied": "This command is only available to the bot admin.",
        "import_done": "Database restored from the file you sent.",
        "import_wrong_file": "Please send an actual file (document), not a photo or text.",
    },
}


def t(lang: str, key: str, **kwargs) -> str:
    lang = lang if lang in TEXT else DEFAULT_UI_LANG
    template = TEXT[lang].get(key, TEXT[DEFAULT_UI_LANG].get(key, key))
    return template.format(**kwargs) if kwargs else template


LANGUAGE_LABELS = {
    "ru": "Русский",
    "kz": "Қазақша",
    "en": "English",
    "any": None,  # переведено через ключ not_important, см. ниже
}


# ---------- storage ----------

def db_init() -> None:
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS profiles (
                user_id     INTEGER PRIMARY KEY,
                username    TEXT,
                full_name   TEXT,
                major       TEXT,
                topic       TEXT,
                skills      TEXT,
                looking_for TEXT,
                language    TEXT,
                status      TEXT NOT NULL DEFAULT 'active',
                contact_type  TEXT,
                contact_value TEXT
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id INTEGER PRIMARY KEY,
                ui_lang TEXT NOT NULL DEFAULT 'ru'
            )
            """
        )
        # миграция для базы, созданной до появления полей language/status/contact
        cols = [r[1] for r in con.execute("PRAGMA table_info(profiles)").fetchall()]
        if "language" not in cols:
            con.execute("ALTER TABLE profiles ADD COLUMN language TEXT")
        if "status" not in cols:
            con.execute("ALTER TABLE profiles ADD COLUMN status TEXT NOT NULL DEFAULT 'active'")
        if "contact_type" not in cols:
            con.execute("ALTER TABLE profiles ADD COLUMN contact_type TEXT")
        if "contact_value" not in cols:
            con.execute("ALTER TABLE profiles ADD COLUMN contact_value TEXT")
        con.commit()


def db_get_ui_lang(user_id: int) -> str | None:
    with closing(sqlite3.connect(DB_PATH)) as con:
        cur = con.execute("SELECT ui_lang FROM user_settings WHERE user_id=?", (user_id,))
        row = cur.fetchone()
        return row[0] if row else None


def db_set_ui_lang(user_id: int, lang: str) -> None:
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute(
            """
            INSERT INTO user_settings (user_id, ui_lang) VALUES (?, ?)
            ON CONFLICT(user_id) DO UPDATE SET ui_lang=excluded.ui_lang
            """,
            (user_id, lang),
        )
        con.commit()


async def get_lang(user_id: int) -> str:
    return db_get_ui_lang(user_id) or DEFAULT_UI_LANG


def db_upsert_profile(user_id: int, username: str, data: dict) -> None:
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute(
            """
            INSERT INTO profiles
                (user_id, username, full_name, major, topic, skills, looking_for, language,
                 contact_type, contact_value)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                username=excluded.username,
                full_name=excluded.full_name,
                major=excluded.major,
                topic=excluded.topic,
                skills=excluded.skills,
                looking_for=excluded.looking_for,
                language=excluded.language,
                contact_type=excluded.contact_type,
                contact_value=excluded.contact_value
            """,
            (
                user_id,
                username,
                data["full_name"],
                data["major"],
                data["topic"],
                data["skills"],
                data["looking_for"],
                data["language"],
                data["contact_type"],
                data["contact_value"],
            ),
        )
        con.commit()


def db_set_status(user_id: int, status: str) -> None:
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute("UPDATE profiles SET status=? WHERE user_id=?", (status, user_id))
        con.commit()


def db_get_profile(user_id: int) -> sqlite3.Row | None:
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute("SELECT * FROM profiles WHERE user_id=?", (user_id,))
        return cur.fetchone()


def db_delete_profile(user_id: int) -> None:
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.execute("DELETE FROM profiles WHERE user_id=?", (user_id,))
        con.commit()


def db_all_profiles(exclude_user_id: int | None = None):
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        if exclude_user_id is not None:
            cur = con.execute(
                "SELECT * FROM profiles WHERE user_id != ? AND status='active' ORDER BY user_id DESC",
                (exclude_user_id,),
            )
        else:
            cur = con.execute("SELECT * FROM profiles WHERE status='active' ORDER BY user_id DESC")
        return cur.fetchall()


def db_search_by_tag(tag: str, exclude_user_id: int):
    tag = f"%{tag.lower()}%"
    with closing(sqlite3.connect(DB_PATH)) as con:
        con.row_factory = sqlite3.Row
        cur = con.execute(
            """
            SELECT * FROM profiles
            WHERE user_id != ?
              AND status='active'
              AND (lower(skills) LIKE ? OR lower(looking_for) LIKE ? OR lower(topic) LIKE ?
                   OR lower(language) LIKE ?)
            ORDER BY user_id DESC
            """,
            (exclude_user_id, tag, tag, tag, tag),
        )
        return cur.fetchall()


# ---------- registration flow ----------

class Registration(StatesGroup):
    choosing_ui_lang = State()
    full_name = State()
    major = State()
    topic = State()
    skills = State()
    looking_for = State()
    language = State()
    contact_method = State()
    contact_value = State()


class AdminActions(StatesGroup):
    awaiting_import = State()


def ui_language_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Русский", callback_data="uilang:ru"),
                InlineKeyboardButton(text="Қазақша", callback_data="uilang:kz"),
                InlineKeyboardButton(text="English", callback_data="uilang:en"),
            ]
        ]
    )


def comm_language_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="Русский", callback_data="lang:ru"),
                InlineKeyboardButton(text="Қазақша", callback_data="lang:kz"),
            ],
            [
                InlineKeyboardButton(text="English", callback_data="lang:en"),
                InlineKeyboardButton(text=t(lang, "not_important"), callback_data="lang:any"),
            ],
        ]
    )


def comm_language_display(lang: str, comm_lang_key: str | None) -> str:
    if comm_lang_key == "any":
        return t(lang, "not_important")
    return LANGUAGE_LABELS.get(comm_lang_key) or (comm_lang_key or "—")


def contact_method_keyboard(lang: str) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t(lang, "btn_contact_telegram"), callback_data="contact:telegram")],
            [InlineKeyboardButton(text=t(lang, "btn_contact_phone"), callback_data="contact:phone")],
            [InlineKeyboardButton(text=t(lang, "btn_contact_email"), callback_data="contact:email")],
        ]
    )


def contact_display(lang: str, row: sqlite3.Row) -> str:
    contact_type = row["contact_type"] if "contact_type" in row.keys() else None
    contact_value = row["contact_value"] if "contact_value" in row.keys() else None
    if contact_type and contact_value:
        return contact_value
    # старые анкеты (до появления выбора контакта) — раньше показывали username напрямую
    uname = row["username"] if "username" in row.keys() else None
    return f"@{uname}" if uname else t(lang, "no_username")


def profile_text(lang: str, row: sqlite3.Row) -> str:
    contact = contact_display(lang, row)
    comm_lang = comm_language_display(lang, row["language"] if "language" in row.keys() else None)
    status = row["status"] if "status" in row.keys() else "active"
    status_line = t(lang, "found_status_line") if status == "found" else ""
    return (
        f"{status_line}"
        f"{t(lang, 'lbl_name')} {row['full_name']}\n"
        f"{t(lang, 'lbl_major')} {row['major']}\n"
        f"{t(lang, 'lbl_topic')} {row['topic']}\n"
        f"{t(lang, 'lbl_skills')} {row['skills']}\n"
        f"{t(lang, 'lbl_looking_for')} {row['looking_for']}\n"
        f"{t(lang, 'lbl_language')} {comm_lang}\n"
        f"{t(lang, 'lbl_contact')} {contact}"
    )


def myprofile_keyboard(lang: str, status: str) -> InlineKeyboardMarkup:
    if status == "found":
        toggle = InlineKeyboardButton(text=t(lang, "btn_reopen"), callback_data="status:active")
    else:
        toggle = InlineKeyboardButton(text=t(lang, "btn_mark_found"), callback_data="status:found")
    return InlineKeyboardMarkup(
        inline_keyboard=[[toggle], [InlineKeyboardButton(text=t(lang, "btn_delete"), callback_data="status:delete")]]
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    existing_lang = db_get_ui_lang(message.from_user.id)
    if existing_lang:
        await message.answer(t(existing_lang, "intro"))
        await state.set_state(Registration.full_name)
        return
    await message.answer(TEXT[DEFAULT_UI_LANG]["choose_ui_lang"], reply_markup=ui_language_keyboard())
    await state.set_state(Registration.choosing_ui_lang)


@router.callback_query(Registration.choosing_ui_lang, F.data.startswith("uilang:"))
async def choose_ui_lang(callback: CallbackQuery, state: FSMContext) -> None:
    lang = callback.data.split(":")[1]
    db_set_ui_lang(callback.from_user.id, lang)
    await callback.message.edit_text(t(lang, "choose_ui_lang") + f"\n\n✅ {UI_LANG_NAMES[lang]}")
    await callback.message.answer(t(lang, "intro"))
    await state.set_state(Registration.full_name)
    await callback.answer()


@router.message(Command("language"))
async def cmd_language(message: Message) -> None:
    await message.answer(TEXT[DEFAULT_UI_LANG]["choose_ui_lang"], reply_markup=ui_language_keyboard())


@router.callback_query(F.data.startswith("uilang:"))
async def change_ui_lang_anytime(callback: CallbackQuery) -> None:
    # ловит смену языка через /language (вне состояния Registration.choosing_ui_lang)
    lang = callback.data.split(":")[1]
    db_set_ui_lang(callback.from_user.id, lang)
    await callback.message.edit_text(t(lang, "lang_changed"))
    await callback.answer()


@router.message(Registration.full_name)
async def reg_full_name(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    await state.update_data(full_name=message.text.strip())
    await message.answer(t(lang, "ask_major"))
    await state.set_state(Registration.major)


@router.message(Registration.major)
async def reg_major(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    await state.update_data(major=message.text.strip())
    await message.answer(t(lang, "ask_topic"))
    await state.set_state(Registration.topic)


@router.message(Registration.topic)
async def reg_topic(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    await state.update_data(topic=message.text.strip())
    await message.answer(t(lang, "ask_skills"))
    await state.set_state(Registration.skills)


@router.message(Registration.skills)
async def reg_skills(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    await state.update_data(skills=message.text.strip())
    await message.answer(t(lang, "ask_looking_for"))
    await state.set_state(Registration.looking_for)


@router.message(Registration.looking_for)
async def reg_looking_for(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    await state.update_data(looking_for=message.text.strip())
    await message.answer(t(lang, "ask_comm_lang"), reply_markup=comm_language_keyboard(lang))
    await state.set_state(Registration.language)


@router.callback_query(Registration.language, F.data.startswith("lang:"))
async def reg_language(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await get_lang(callback.from_user.id)
    comm_lang_key = callback.data.split(":")[1]
    await state.update_data(language=comm_lang_key)
    await callback.message.edit_text(t(lang, "ask_contact_method"), reply_markup=contact_method_keyboard(lang))
    await state.set_state(Registration.contact_method)
    await callback.answer()


async def finish_registration(user_id: int, username: str, state: FSMContext, lang: str) -> sqlite3.Row:
    data = await state.get_data()
    db_upsert_profile(user_id, username, data)
    await state.clear()
    return db_get_profile(user_id)


@router.callback_query(Registration.contact_method, F.data.startswith("contact:"))
async def reg_contact_method(callback: CallbackQuery, state: FSMContext) -> None:
    lang = await get_lang(callback.from_user.id)
    method = callback.data.split(":")[1]

    if method == "telegram":
        username = callback.from_user.username
        if username:
            await state.update_data(contact_type="telegram", contact_value=f"@{username}")
            row = await finish_registration(callback.from_user.id, username or "", state, lang)
            await callback.message.edit_text(
                t(lang, "saved_intro") + "\n\n" + profile_text(lang, row) + "\n\n" + t(lang, "commands_hint")
            )
            await callback.answer()
            return
        await callback.message.edit_text(
            t(lang, "no_username_notice"), reply_markup=contact_method_keyboard(lang)
        )
        await callback.answer()
        return

    # phone или email — просим ввести значение следующим сообщением
    prompt_key = "ask_phone" if method == "phone" else "ask_email"
    await state.update_data(contact_type=method)
    await callback.message.edit_text(t(lang, prompt_key))
    await state.set_state(Registration.contact_value)
    await callback.answer()


@router.message(Registration.contact_value)
async def reg_contact_value(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    await state.update_data(contact_value=message.text.strip())
    row = await finish_registration(message.from_user.id, message.from_user.username or "", state, lang)
    await message.answer(
        t(lang, "saved_intro") + "\n\n" + profile_text(lang, row) + "\n\n" + t(lang, "commands_hint")
    )


# ---------- browse / search ----------

def browse_keyboard(lang: str, idx: int, total: int) -> InlineKeyboardMarkup:
    buttons = []
    if total > 1:
        buttons.append(
            InlineKeyboardButton(text=t(lang, "btn_back"), callback_data=f"browse:{(idx - 1) % total}")
        )
        buttons.append(
            InlineKeyboardButton(text=t(lang, "btn_next"), callback_data=f"browse:{(idx + 1) % total}")
        )
    return InlineKeyboardMarkup(inline_keyboard=[buttons] if buttons else [])


@router.message(Command("browse"))
async def cmd_browse(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    profiles = db_all_profiles(exclude_user_id=message.from_user.id)
    if not profiles:
        await message.answer(t(lang, "browse_empty"))
        return
    row = profiles[0]
    await message.answer(
        t(lang, "browse_header", i=1, n=len(profiles)) + "\n\n" + profile_text(lang, row),
        reply_markup=browse_keyboard(lang, 0, len(profiles)),
    )


@router.callback_query(F.data.startswith("browse:"))
async def cb_browse(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    idx = int(callback.data.split(":")[1])
    profiles = db_all_profiles(exclude_user_id=callback.from_user.id)
    if not profiles:
        await callback.answer(t(lang, "browse_none_left"))
        return
    idx = idx % len(profiles)
    row = profiles[idx]
    await callback.message.edit_text(
        t(lang, "browse_header", i=idx + 1, n=len(profiles)) + "\n\n" + profile_text(lang, row),
        reply_markup=browse_keyboard(lang, idx, len(profiles)),
    )
    await callback.answer()


@router.message(Command("find"))
async def cmd_find(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(t(lang, "find_usage"))
        return
    tag = parts[1].strip()
    results = db_search_by_tag(tag, exclude_user_id=message.from_user.id)
    if not results:
        await message.answer(t(lang, "find_none", tag=tag))
        return
    text = t(lang, "find_header", n=len(results), tag=tag) + "\n\n"
    text += "\n\n---\n\n".join(profile_text(lang, r) for r in results[:5])
    await message.answer(text)


@router.message(Command("myprofile"))
async def cmd_myprofile(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    row = db_get_profile(message.from_user.id)
    if not row:
        await message.answer(t(lang, "no_profile"))
        return
    await message.answer(profile_text(lang, row), reply_markup=myprofile_keyboard(lang, row["status"]))


@router.callback_query(F.data == "status:found")
async def cb_status_found(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    db_set_status(callback.from_user.id, "found")
    row = db_get_profile(callback.from_user.id)
    await callback.message.edit_text(profile_text(lang, row), reply_markup=myprofile_keyboard(lang, row["status"]))
    await callback.answer(t(lang, "found_toast"))


@router.callback_query(F.data == "status:active")
async def cb_status_active(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    db_set_status(callback.from_user.id, "active")
    row = db_get_profile(callback.from_user.id)
    await callback.message.edit_text(profile_text(lang, row), reply_markup=myprofile_keyboard(lang, row["status"]))
    await callback.answer(t(lang, "reopen_toast"))


@router.callback_query(F.data == "status:delete")
async def cb_status_delete(callback: CallbackQuery) -> None:
    lang = await get_lang(callback.from_user.id)
    db_delete_profile(callback.from_user.id)
    await callback.message.edit_text(t(lang, "profile_deleted"))
    await callback.answer()


@router.message(Command("found"))
async def cmd_found(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    row = db_get_profile(message.from_user.id)
    if not row:
        await message.answer(t(lang, "no_profile_short"))
        return
    db_set_status(message.from_user.id, "found")
    await message.answer(t(lang, "found_msg"))


@router.message(Command("reopen"))
async def cmd_reopen(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    row = db_get_profile(message.from_user.id)
    if not row:
        await message.answer(t(lang, "no_profile_short"))
        return
    db_set_status(message.from_user.id, "active")
    await message.answer(t(lang, "reopen_msg"))


@router.message(Command("delete"))
async def cmd_delete(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    db_delete_profile(message.from_user.id)
    await message.answer(t(lang, "profile_deleted"))


@router.message(Command("export"))
async def cmd_export(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    if not ADMIN_USER_ID or str(message.from_user.id) != str(ADMIN_USER_ID):
        await message.answer(t(lang, "export_denied"))
        return
    if not os.path.exists(DB_PATH):
        await message.answer("team_finder.db ещё не создан — анкет пока нет.")
        return
    import datetime

    caption = t(lang, "export_caption", time=datetime.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"))
    await message.answer_document(FSInputFile(DB_PATH), caption=caption)


@router.message(Command("import"))
async def cmd_import(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    if not ADMIN_USER_ID or str(message.from_user.id) != str(ADMIN_USER_ID):
        await message.answer(t(lang, "import_denied"))
        return
    await message.answer(t(lang, "import_prompt"))
    await state.set_state(AdminActions.awaiting_import)


@router.message(AdminActions.awaiting_import, F.document)
async def receive_import_file(message: Message, state: FSMContext) -> None:
    lang = await get_lang(message.from_user.id)
    if not ADMIN_USER_ID or str(message.from_user.id) != str(ADMIN_USER_ID):
        await state.clear()
        await message.answer(t(lang, "import_denied"))
        return
    await message.bot.download(message.document, destination=DB_PATH)
    await state.clear()
    await message.answer(t(lang, "import_done"))


@router.message(AdminActions.awaiting_import)
async def receive_import_wrong_type(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    await message.answer(t(lang, "import_wrong_file"))


# ---------- fallback ----------
# Ловит всё, что не подошло ни под один шаг анкеты или команду — например,
# если состояние FSM сбросилось из-за перезапуска сервера. Без этого
# обработчика бот в такой ситуации молчал бы, и выглядело бы как зависание.

@router.message()
async def fallback(message: Message) -> None:
    lang = await get_lang(message.from_user.id)
    await message.answer(t(lang, "fallback_hint"))


# ---------- entrypoint ----------

async def main() -> None:
    db_init()
    if BOT_TOKEN == "PUT_YOUR_TOKEN_HERE":
        raise SystemExit(
            "Токен бота не задан. Получите токен у @BotFather в Telegram и передайте его "
            "через переменную окружения BOT_TOKEN (см. README.md)."
        )
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())
