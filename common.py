"""Umumiy yordamchi funksiyalar, filtrlar va klaviaturalar."""
import html
import logging
import re

from aiogram.exceptions import TelegramBadRequest
from aiogram.filters import BaseFilter
from aiogram.types import (CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, KeyboardButton, Message,
                           ReplyKeyboardMarkup)

import db
from config import ADMIN_IDS

log = logging.getLogger(__name__)

BTN_LESSONS = "📚 Darslar"
BTN_TESTS = "📝 Testlar"
BTN_RESULTS = "📊 Natijalarim"
BTN_RATING = "🏆 Reyting"
BTN_ADMIN = "⚙️ Admin panel"


def is_admin(uid: int) -> bool:
    return uid in ADMIN_IDS


class IsAdmin(BaseFilter):
    async def __call__(self, event) -> bool:
        return bool(event.from_user) and is_admin(event.from_user.id)


class Approved(BaseFilter):
    """Faqat admin ruxsat bergan o'quvchilar (va adminlar) o'tadi."""

    async def __call__(self, event) -> bool:
        if not event.from_user:
            return False
        if is_admin(event.from_user.id):
            return True
        u = await db.get_user(event.from_user.id)
        return bool(u) and u["status"] == "approved"


class PrivateChat(BaseFilter):
    async def __call__(self, event) -> bool:
        msg = event.message if isinstance(event, CallbackQuery) else event
        return bool(msg) and msg.chat.type == "private"


def main_menu(uid: int) -> ReplyKeyboardMarkup:
    rows = [[KeyboardButton(text=BTN_LESSONS), KeyboardButton(text=BTN_TESTS)],
            [KeyboardButton(text=BTN_RESULTS), KeyboardButton(text=BTN_RATING)]]
    if is_admin(uid):
        rows.append([KeyboardButton(text=BTN_ADMIN)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def kb(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    """[[("Matn", "callback"), ...], ...] -> inline klaviatura. callback 'url:' bilan boshlansa — havola."""
    out = []
    for row in rows:
        if not row:
            continue
        r = []
        for text, data in row:
            if data.startswith("url:"):
                r.append(InlineKeyboardButton(text=text, url=data[4:]))
            else:
                r.append(InlineKeyboardButton(text=text, callback_data=data))
        out.append(r)
    return InlineKeyboardMarkup(inline_keyboard=out)


def fmt_dur(sec: float | None) -> str:
    if sec is None:
        return "—"
    sec = int(round(sec))
    m, s = divmod(sec, 60)
    if m >= 60:
        h, m = divmod(m, 60)
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def pct(correct: int, total: int) -> int:
    return round(100 * correct / total) if total else 0


def esc(s: str) -> str:
    """Bot HTML rejimida ishlaydi — matndagi < > & belgilarini xavfsiz qiladi."""
    return html.escape(s or "", quote=False)


def strip_tags(s: str) -> str:
    return re.sub(r"<[^>]+>", "", s)


async def safe_edit(cb: CallbackQuery, text: str, markup=None):
    """Xabarni tahrirlaydi; imkoni bo'lmasa yangi xabar yuboradi."""
    try:
        await cb.message.edit_text(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "message is not modified" in str(e):
            return
        if "can't parse entities" in str(e):
            await cb.message.answer(strip_tags(text), reply_markup=markup, parse_mode=None)
            return
        await cb.message.answer(text, reply_markup=markup, disable_web_page_preview=True)


async def safe_answer(msg: Message, text: str, markup=None):
    try:
        return await msg.answer(text, reply_markup=markup, disable_web_page_preview=True)
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e):
            return await msg.answer(strip_tags(text), reply_markup=markup, parse_mode=None)
        raise


def chunk_text(text: str, limit: int = 3900) -> list[str]:
    parts, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > limit:
            parts.append(cur)
            cur = ""
        cur += ("\n" if cur else "") + line
    if cur:
        parts.append(cur)
    return parts
