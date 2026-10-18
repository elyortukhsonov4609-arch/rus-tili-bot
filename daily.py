"""Kunlik vazifa: har kuni har bir o'quvchiga shaxsiy savollar, seriya (🔥 ketma-ket kunlar) va eslatma.

Vazifa ikki yo'l bilan bajarilgan hisoblanadi:
  • botdagi «📅 Bugungi vazifa»ni oxirigacha ishlasa;
  • guruhdagi savollarning kamida N tasiga javob bersa (N — sozlamada, standart 5).
"""
import asyncio
import html
import logging
import random
import time
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.types import CallbackQuery, Message

import db
from common import BTN_DAILY, Approved, PrivateChat, kb
from config import TZ
from quiz import quiz

log = logging.getLogger(__name__)
router = Router(name="daily")
router.message.filter(PrivateChat(), Approved())
router.callback_query.filter(PrivateChat(), Approved())

MILESTONES = {3: "🎉 3 kun ketma-ket!", 7: "🏅 Bir hafta ketma-ket!", 14: "🥇 Ikki hafta ketma-ket!",
              30: "🏆 Bir oy ketma-ket! Siz haqiqiy chempionsiz!"}


def today() -> str:
    return datetime.now(TZ).date().isoformat()


def day_start_ts() -> float:
    return datetime.now(TZ).replace(hour=0, minute=0, second=0, microsecond=0).timestamp()


async def done_today(uid: int) -> bool:
    return bool(await db.fetchone("SELECT 1 FROM daily_log WHERE user_id=? AND day=?", (uid, today())))


async def streak(uid: int) -> int:
    rows = await db.fetchall("SELECT day FROM daily_log WHERE user_id=? ORDER BY day DESC LIMIT 400", (uid,))
    days = {r["day"] for r in rows}
    d = datetime.now(TZ).date()
    if d.isoformat() not in days:
        d -= timedelta(days=1)          # bugun hali bajarmagan bo'lsa — kechagi kundan sanaladi
    n = 0
    while d.isoformat() in days:
        n += 1
        d -= timedelta(days=1)
    return n


async def mark_done(uid: int, source: str) -> bool:
    """Bugungi vazifani bajarilgan deb belgilaydi. Yangi belgilangan bo'lsa True."""
    if await done_today(uid):
        return False
    await db.execute("INSERT INTO daily_log(user_id, day, source) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                     (uid, today(), source))
    return True


def streak_line(n: int) -> str:
    if n <= 0:
        return "🔥 Seriya: hali boshlanmagan"
    line = f"🔥 Seriya: <b>{n}</b> kun ketma-ket"
    if n in MILESTONES:
        line += f"\n{MILESTONES[n]}"
    return line


# ---------------- savollarni tanlash ----------------
async def pick_questions(uid: int, n: int) -> list[dict]:
    """O'quvchining o'z guruhidagi ochiq testlardan, uning xatolariga qarab savol tanlaydi."""
    gid = await db.user_group(uid) or 1
    need_read = await db.get_int("require_read")
    tests = await db.fetchall("SELECT id, lesson_id FROM tests WHERE is_open=1 AND group_id=?", (gid,))
    if need_read:
        read = {r["lesson_id"] for r in await db.fetchall(
            "SELECT lesson_id FROM lesson_reads WHERE user_id=?", (uid,))}
        tests = [t for t in tests if t["lesson_id"] is None or t["lesson_id"] in read]
    ids = [t["id"] for t in tests]
    if not ids:
        return []
    marks = ",".join("?" * len(ids))
    rows = await db.fetchall(f"SELECT * FROM questions WHERE test_id IN ({marks})", tuple(ids))
    if not rows:
        return []
    stats = {}
    for r in await db.fetchall(
            "SELECT an.question_id AS q, COUNT(*) AS n, SUM(an.is_correct) AS c FROM answers an "
            "JOIN attempts a ON a.id = an.attempt_id WHERE a.user_id=? GROUP BY an.question_id", (uid,)):
        stats[r["q"]] = [r["n"], r["c"] or 0]
    for r in await db.fetchall(
            "SELECT question_id AS q, COUNT(*) AS n, SUM(ok) AS c FROM group_answers WHERE user_id=? "
            "AND question_id IS NOT NULL GROUP BY question_id", (uid,)):
        s = stats.setdefault(r["q"], [0, 0])
        s[0] += r["n"]
        s[1] += r["c"] or 0
    recent = {r["question_id"] for r in await db.fetchall(
        "SELECT an.question_id FROM answers an JOIN attempts a ON a.id = an.attempt_id "
        "WHERE a.user_id=? AND a.started_at > ?", (uid, time.time() - 2 * 86400))}
    weights = []
    for r in rows:
        cnt, ok = stats.get(r["id"], (0, 0))
        err = (cnt - ok + 1) / (cnt + 2)
        w = 1 + 5 * err + (2 if cnt == 0 else 0)
        if r["id"] in recent:
            w *= 0.2
        weights.append(w)
    rows, picked = list(rows), []
    for _ in range(min(n, len(rows))):
        i = random.choices(range(len(rows)), weights=weights, k=1)[0]
        picked.append(db.q_from_row(rows.pop(i)))
        weights.pop(i)
    return picked


# ---------------- boshlash va yakunlash ----------------
async def start_daily(bot: Bot, uid: int, chat_id: int) -> str | None:
    if await done_today(uid):
        return "✅ Bugungi vazifani allaqachon bajargansiz! Ertaga yangi vazifa keladi."
    qs = await pick_questions(uid, await db.get_int("daily_count"))
    if not qs:
        return "Vazifa uchun savol topilmadi. Avval «📚 Darslar» bo'limida darsni o'qing."
    return await quiz.start_questions(bot, uid, chat_id, "daily", "📅 Bugungi vazifa", qs)


async def _finished(bot: Bot, s, status: str):
    total = len(s.items)
    if status != "done":
        await bot.send_message(s.chat_id, f"⏹ Vazifa to'xtatildi ({s.pos}/{total}).\n"
                                          "Vazifa oxirigacha ishlangandagina bajarilgan hisoblanadi.",
                               reply_markup=kb([[("▶️ Qayta boshlash", "daily:start")]]))
        return
    await mark_done(s.user_id, "bot")
    n = await streak(s.user_id)
    p = round(100 * s.correct / total) if total else 0
    await bot.send_message(
        s.chat_id,
        f"✅ <b>Bugungi vazifa bajarildi!</b>\n\nTo'g'ri javoblar: <b>{s.correct} / {total}</b> ({p}%)\n"
        f"{streak_line(n)}\n\nErtaga ham davom eting, seriya uzilmasin! 💪",
        reply_markup=kb([[("❌ Xatolarni ko'rish", f"tst:wrong:{s.attempt_id}"), ("📚 Darslar", "les:list")]]))


quiz.daily_finisher = _finished


async def on_group_answer(bot: Bot, uid: int):
    """Guruhdagi javobdan keyin chaqiriladi: yetarli javob bo'lsa — kunlik vazifa bajarilgan."""
    u = await db.get_user(uid)
    if not u or u["status"] != "approved" or await done_today(uid):
        return
    need = await db.get_int("daily_group_min")
    cnt = (await db.fetchone("SELECT COUNT(*) AS n FROM group_answers WHERE user_id=? AND answered_at >= ?",
                             (uid, day_start_ts())))["n"]
    if cnt >= need and await mark_done(uid, "group"):
        try:
            await bot.send_message(uid, f"✅ Bugungi vazifa guruhdagi savollar orqali bajarildi!\n"
                                        f"{streak_line(await streak(uid))}")
        except TelegramAPIError:
            pass


# ---------------- hammaga yuborish (rejalashtiruvchi chaqiradi) ----------------
async def _students():
    return await db.fetchall("SELECT id, full_name FROM users WHERE status='approved'")


async def send_daily_all(bot: Bot) -> int:
    n = 0
    count = await db.get_int("daily_count")
    for u in await _students():
        if await done_today(u["id"]):
            continue
        try:
            await bot.send_message(u["id"], f"📅 <b>Bugungi vazifa tayyor!</b>\n{count} ta savol sizni kutmoqda.\n"
                                            f"{streak_line(await streak(u['id']))}",
                                   reply_markup=kb([[("▶️ Boshlash", "daily:start")]]))
            n += 1
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
    return n


async def remind_all(bot: Bot) -> int:
    n = 0
    for u in await _students():
        if await done_today(u["id"]):
            continue
        s = await streak(u["id"])
        text = ("⏰ Bugungi vazifani hali bajarmadingiz!\n" +
                (f"🔥 Seriyangiz <b>{s}</b> kun — uzilib qolmasin!" if s else "Bugun yangi seriyani boshlang! 🔥"))
        try:
            await bot.send_message(u["id"], text, reply_markup=kb([[("▶️ Vazifani boshlash", "daily:start")]]))
            n += 1
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
    return n


# ---------------- o'quvchi tugmalari ----------------
async def _daily_info(uid: int) -> tuple[str, list]:
    s = await streak(uid)
    if await done_today(uid):
        return f"✅ Bugungi vazifa bajarilgan.\n{streak_line(s)}\n\nErtaga yangi vazifa keladi!", []
    count = await db.get_int("daily_count")
    need = await db.get_int("daily_group_min")
    return (f"📅 <b>Bugungi vazifa</b>: {count} ta savol\n{streak_line(s)}\n\n"
            f"<i>Guruhdagi savollarning {need} tasiga javob bersangiz ham vazifa bajarilgan hisoblanadi.</i>",
            [[("▶️ Boshlash", "daily:start")]])


@router.message(F.text == BTN_DAILY)
async def daily_button(msg: Message):
    text, rows = await _daily_info(msg.from_user.id)
    await msg.answer(text, reply_markup=kb(rows) if rows else None)


@router.callback_query(F.data == "daily:start")
async def daily_start_cb(cb: CallbackQuery, bot: Bot):
    await cb.answer()
    err = await start_daily(bot, cb.from_user.id, cb.message.chat.id)
    if err:
        await cb.message.answer(err)
