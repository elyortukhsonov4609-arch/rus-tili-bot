"""Guruh bilan ishlash: avtomatik savollar, admin tanlagan testni guruhga yuborish, guruh reytingi."""
import asyncio
import html
import json
import logging
import random
import time
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramForbiddenError
from aiogram.filters import Command
from aiogram.types import CallbackQuery, ChatMemberUpdated, Message, PollAnswer

import db
from common import esc, fmt_dur, is_admin, kb
from config import ADMIN_IDS, TZ
from quiz import quiz

log = logging.getLogger(__name__)
router = Router(name="group")
GROUP_TYPES = {"group", "supergroup"}


# ======================= Guruh test sessiyasi =======================
@dataclass
class GroupTest:
    chat_id: int
    test_id: str
    title: str
    total: int
    seconds: int
    thread_id: Optional[int] = None
    cancelled: bool = False
    polls: dict = field(default_factory=dict)      # poll_id -> (to'g'ri indeks, yuborilgan vaqt)
    scores: dict = field(default_factory=dict)     # user_id -> [ism, to'g'ri, javoblar, sarflangan vaqt]
    task: Optional[asyncio.Task] = None


running: dict[int, GroupTest] = {}   # chat_id -> faol test
poll_session: dict[str, GroupTest] = {}


# ---------------- javoblar (shaxsiy test ham, guruh ham) ----------------
@router.poll_answer()
async def on_poll_answer(pa: PollAnswer):
    if not pa.user:
        return
    if await quiz.on_answer(pa.poll_id, pa.user.id, pa.option_ids):
        return
    gp = await db.fetchone("SELECT * FROM group_polls WHERE poll_id=?", (pa.poll_id,))
    if not gp or not pa.option_ids:
        return
    ok = int(pa.option_ids[0] == gp["correct"])
    name = pa.user.full_name
    u = await db.get_user(pa.user.id)
    if u:
        name = u["full_name"]
    await db.execute(
        "INSERT INTO group_scores(chat_id, user_id, name, correct, answered) VALUES(?,?,?,?,1) "
        "ON CONFLICT(chat_id, user_id) DO UPDATE SET correct=group_scores.correct+excluded.correct, answered=group_scores.answered+1, "
        "name=excluded.name", (gp["chat_id"], pa.user.id, name, ok))
    await db.execute("INSERT INTO group_answers(poll_id, chat_id, user_id, question_id, ok) VALUES(?,?,?,?,?) "
                     "ON CONFLICT DO NOTHING",
                     (pa.poll_id, gp["chat_id"], pa.user.id, gp["question_id"], ok))
    s = poll_session.get(pa.poll_id)
    if s:
        _, sent = s.polls[pa.poll_id]
        rec = s.scores.setdefault(pa.user.id, [name, 0, 0, 0.0])
        rec[1] += ok
        rec[2] += 1
        rec[3] += time.time() - sent


# ---------------- bot guruhga qo'shilganda ----------------
@router.my_chat_member(F.chat.type.in_(GROUP_TYPES))
async def on_my_member(ev: ChatMemberUpdated, bot: Bot):
    status = ev.new_chat_member.status
    chat = ev.chat
    if status in ("left", "kicked"):
        await db.execute("UPDATE groups SET active=0 WHERE chat_id=?", (chat.id,))
        return
    exists = await db.fetchone("SELECT * FROM groups WHERE chat_id=?", (chat.id,))
    by_admin = ev.from_user and is_admin(ev.from_user.id)
    if not exists:
        await db.execute("INSERT INTO groups(chat_id, title, active, added_at) VALUES(?,?,?,?)",
                         (chat.id, chat.title, 1 if by_admin else 0, int(time.time())))
    else:
        await db.execute("UPDATE groups SET title=? WHERE chat_id=?", (chat.title, chat.id))
        if by_admin:
            await db.execute("UPDATE groups SET active=1 WHERE chat_id=?", (chat.id,))
    kick_scheduler()
    if by_admin:
        try:
            await bot.send_message(chat.id, "👋 Salom! Men shu guruhga vaqti-vaqti bilan test savollari va "
                                            "qiziqarli savollar tashlab turaman.\n"
                                            "To'g'ri javob bergan har bir savol uchun 1 ball olasiz. "
                                            "Reytingni ko'rish: /reyting")
        except TelegramAPIError:
            pass
    else:
        for a in ADMIN_IDS:
            try:
                await bot.send_message(
                    a, f"👥 Bot «{html.escape(chat.title or str(chat.id))}» guruhiga qo'shildi.\n"
                       "Bu guruhga test yuborishni yoqasizmi?",
                    reply_markup=kb([[("✅ Yoqish", f"adm:gon:{chat.id}"), ("❌ Yo'q", f"adm:goff:{chat.id}")]]))
            except TelegramAPIError:
                pass


def from_admin(msg: Message) -> bool:
    """Xabar admindan keldimi. Guruhga «anonim admin» bo'lib yozilgan xabarlar ham hisoblanadi
    (bunda Telegram yozuvchini emas, guruhning o'zini ko'rsatadi)."""
    if msg.from_user and is_admin(msg.from_user.id):
        return True
    return bool(msg.sender_chat and msg.sender_chat.id == msg.chat.id)


async def _remember_group(msg: Message):
    """Guruhni ro'yxatga oladi va admin buyruq yozgan mavzuni (topic) eslab qoladi."""
    thread = msg.message_thread_id if msg.is_topic_message else None
    g = await db.fetchone("SELECT * FROM groups WHERE chat_id=?", (msg.chat.id,))
    if not g:
        await db.execute("INSERT INTO groups(chat_id, title, active, added_at, thread_id) VALUES(?,?,1,?,?)",
                         (msg.chat.id, msg.chat.title, int(time.time()), thread))
    else:
        await db.execute("UPDATE groups SET thread_id=?, title=? WHERE chat_id=?", (thread, msg.chat.title, msg.chat.id))
    kick_scheduler()
    return thread


# ---------------- guruh buyruqlari ----------------
async def group_top_text(chat_id: int, limit: int = 10) -> str:
    rows = await db.fetchall("SELECT * FROM group_scores WHERE chat_id=? ORDER BY correct DESC, answered ASC LIMIT ?",
                             (chat_id, limit))
    if not rows:
        return "🏆 Guruh reytingi hozircha bo'sh. Savollarga javob bering!"
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = ["🏆 <b>Guruh reytingi</b>\n"]
    for i, r in enumerate(rows, 1):
        lines.append(f"{medals.get(i, f'{i}.')} {html.escape(r['name'] or '—')} — <b>{r['correct']}</b> ball "
                     f"({r['answered']} ta javob)")
    return "\n".join(lines)


@router.message(Command("reyting", "top"), F.chat.type.in_(GROUP_TYPES))
async def cmd_group_top(msg: Message):
    await msg.answer(await group_top_text(msg.chat.id))


@router.message(Command("savol"), F.chat.type.in_(GROUP_TYPES))
async def cmd_group_now(msg: Message, bot: Bot):
    if not from_admin(msg):
        return
    await _remember_group(msg)
    await post_question(bot, msg.chat.id)


@router.message(Command("test"), F.chat.type.in_(GROUP_TYPES))
async def cmd_group_test(msg: Message):
    if not from_admin(msg):
        return
    await _remember_group(msg)
    tests = await db.fetchall("SELECT t.id, t.title, (SELECT COUNT(*) FROM questions q WHERE q.test_id=t.id) AS n "
                              "FROM tests t ORDER BY t.sort")
    rows = [[(f"{t['title']} [{t['n']}]", f"gt:pick:{t['id']}")] for t in tests if t["n"]]
    rows.append([("❌ Yopish", "gt:close")])
    await msg.answer("📝 Guruhga qaysi testni yuboray? (faqat admin tanlay oladi)", reply_markup=kb(rows))


@router.message(Command("stoptest"), F.chat.type.in_(GROUP_TYPES))
async def cmd_group_stop(msg: Message):
    if not from_admin(msg):
        return
    if not stop_group_test(msg.chat.id):
        await msg.answer("Hozir guruhda test ketmayapti.")


def count_buttons(prefix: str, n_total: int):
    opts = [n for n in (10, 20, 30) if n < n_total] + [n_total]
    return [[(f"{n} ta" if n != n_total else f"Hammasi ({n})", f"{prefix}:{n}") for n in opts]]


@router.callback_query(F.data.startswith("gt:"))
async def group_test_cb(cb: CallbackQuery, bot: Bot):
    if not is_admin(cb.from_user.id):
        await cb.answer("Testni faqat o'qituvchi tanlaydi 🙂", show_alert=True)
        return
    parts = cb.data.split(":")
    chat_id = cb.message.chat.id
    if parts[1] == "close":
        await cb.message.delete()
        return await cb.answer()
    tid = parts[2]
    t = await db.fetchone("SELECT * FROM tests WHERE id=?", (tid,))
    n = (await db.fetchone("SELECT COUNT(*) AS n FROM questions WHERE test_id=?", (tid,)))["n"]
    if parts[1] == "pick":
        await cb.message.edit_text(f"📝 <b>{html.escape(t['title'])}</b>\nNechta savol yuborilsin?",
                                   reply_markup=kb(count_buttons(f"gt:go:{tid}", n) + [[("❌ Yopish", "gt:close")]]))
        return await cb.answer()
    if parts[1] == "go":
        try:
            await cb.message.delete()
        except TelegramAPIError:
            pass
        err = await start_group_test(bot, chat_id, tid, int(parts[3]))
        await cb.answer(err or "Test boshlandi!", show_alert=bool(err))


# ---------------- savol yuborish ----------------
async def _group_thread(chat_id: int) -> Optional[int]:
    g = await db.fetchone("SELECT thread_id FROM groups WHERE chat_id=?", (chat_id,))
    return g["thread_id"] if g else None


async def _send_group_poll(bot: Bot, chat_id: int, row, prefix: str, qid, fun_id, seconds: int):
    """Bitta quiz savolni guruhga yuboradi. Muvaffaqiyatli bo'lsa (poll_id, to'g'ri indeks) qaytaradi."""
    options = json.loads(row["options"])
    perm = list(range(len(options)))
    random.shuffle(perm)
    correct = perm.index(row["correct"])
    try:
        msg = await bot.send_poll(chat_id, question=esc((prefix + row["q"])[:300]),
                                  options=[esc(options[i]) for i in perm], type="quiz",
                                  correct_option_id=correct, is_anonymous=False, open_period=seconds,
                                  explanation=esc((row["explanation"] or "")[:200]) or None,
                                  message_thread_id=await _group_thread(chat_id))
    except TelegramForbiddenError:
        await db.execute("UPDATE groups SET active=0 WHERE chat_id=?", (chat_id,))
        log.warning("Guruhga yozish taqiqlangan, o'chirildi: %s", chat_id)
        return None
    except TelegramAPIError as e:
        log.warning("Guruhga savol yuborilmadi %s: %s", chat_id, e)
        return None
    await db.execute("INSERT INTO group_polls(poll_id, chat_id, question_id, fun_id, correct, sent_at) "
                     "VALUES(?,?,?,?,?,?)", (msg.poll.id, chat_id, qid, fun_id, correct, time.time()))
    return msg.poll.id, correct


async def question_weights(chat_id: int | None, rows) -> list[float]:
    """Aqlli tanlash: har bir savolga «muhimlik» vazni beradi.

    Vazn oshadi, agar:
      • savolda bolalar ko'p xato qilsa (shaxsiy testlar + guruh javoblari);
      • savol tegishli testni o'quvchilarning kam qismi ishlagan bo'lsa;
      • savol bu guruhga hali umuman yuborilmagan bo'lsa.
    Yaqinda yuborilgan savollarning vazni keskin kamayadi (takrorlanmasligi uchun).
    """
    priv = {r["question_id"]: (r["n"], r["c"]) for r in await db.fetchall(
        "SELECT question_id, COUNT(*) AS n, SUM(is_correct) AS c FROM answers GROUP BY question_id")}
    grp, asked, recent = {}, set(), set()
    if chat_id is not None:
        grp = {r["question_id"]: (r["n"], r["c"]) for r in await db.fetchall(
            "SELECT question_id, COUNT(*) AS n, SUM(ok) AS c FROM group_answers WHERE chat_id=? "
            "AND question_id IS NOT NULL GROUP BY question_id", (chat_id,))}
        asked = {r["question_id"] for r in await db.fetchall(
            "SELECT DISTINCT question_id FROM group_polls WHERE chat_id=? AND question_id IS NOT NULL", (chat_id,))}
        recent = {r["question_id"] for r in await db.fetchall(
            "SELECT question_id FROM group_polls WHERE chat_id=? AND question_id IS NOT NULL "
            "ORDER BY sent_at DESC LIMIT 150", (chat_id,))}
    students = max(1, (await db.fetchone("SELECT COUNT(*) AS n FROM users WHERE status='approved'"))["n"])
    done = {r["test_id"]: r["n"] for r in await db.fetchall(
        "SELECT test_id, COUNT(DISTINCT user_id) AS n FROM attempts WHERE status='done' GROUP BY test_id")}
    weights = []
    for r in rows:
        pn, pc = priv.get(r["id"], (0, 0))
        gn, gc = grp.get(r["id"], (0, 0))
        n, c = pn + gn, (pc or 0) + (gc or 0)
        err = (n - c + 1) / (n + 2)                       # xato ulushi (ma'lumot kam bo'lsa ~50%)
        not_done = 1 - min(1.0, done.get(r["test_id"], 0) / students)
        w = 1 + 4 * err + 2 * not_done + (2 if r["id"] not in asked else 0)
        if r["id"] in recent:
            w *= 0.05
        weights.append(w)
    return weights


async def _pick_test_question(chat_id: int):
    scope = await db.get_setting("group_scope")
    if scope != "all":
        rows = await db.fetchall("SELECT q.* FROM questions q WHERE q.test_id=?", (scope,))
    else:
        rows = await db.fetchall("SELECT q.* FROM questions q JOIN tests t ON t.id=q.test_id WHERE t.is_open=1")
    if not rows:
        return None
    weights = await question_weights(chat_id, rows)
    return random.choices(rows, weights=weights, k=1)[0]


async def post_question(bot: Bot, chat_id: int, force_fun: bool | None = None) -> bool:
    """Avtomatik rejimdagi bitta savol (test savoli yoki qiziqarli savol)."""
    g = await db.fetchone("SELECT * FROM groups WHERE chat_id=?", (chat_id,))
    count = g["post_count"] if g else 0
    use_fun = force_fun
    if use_fun is None:
        every = max(2, await db.get_int("group_fun_every"))
        use_fun = bool(await db.get_int("group_fun")) and count % every == every - 1
    row, fun_id, qid, prefix = None, None, None, "📝 "
    if use_fun:
        recent = {r["fun_id"] for r in await db.fetchall(
            "SELECT fun_id FROM group_polls WHERE chat_id=? AND fun_id IS NOT NULL ORDER BY sent_at DESC LIMIT 25",
            (chat_id,))}
        funs = await db.fetchall("SELECT * FROM fun_questions")
        funs = [f for f in funs if f["id"] not in recent] or funs
        if funs:
            row = random.choice(funs)
            fun_id, prefix = row["id"], "🧠 Qiziqarli savol: "
    if row is None:
        row = await _pick_test_question(chat_id)
        if row is None:
            return False
        qid = row["id"]
    res = await _send_group_poll(bot, chat_id, row, prefix, qid, fun_id, await db.get_int("group_seconds"))
    if not res:
        return False
    await db.execute("UPDATE groups SET last_post_at=?, post_count=post_count+1 WHERE chat_id=?",
                     (time.time(), chat_id))
    return True


# ---------------- admin tanlagan testni guruhga yuborish ----------------
async def start_group_test(bot: Bot, chat_id: int, test_id: str, count: int) -> Optional[str]:
    if chat_id in running:
        return "Bu guruhda test allaqachon ketyapti. To'xtatish: /stoptest"
    t = await db.fetchone("SELECT * FROM tests WHERE id=?", (test_id,))
    if not t:
        return "Test topilmadi."
    qs = await db.fetchall("SELECT * FROM questions WHERE test_id=?", (test_id,))
    if not qs:
        return "Bu testda savol yo'q."
    qs = list(qs)
    if count and count < len(qs):
        # aqlli tanlash: qiyin va kam ishlangan savollar ko'proq chiqadi
        weights = await question_weights(chat_id, qs)
        picked = []
        for _ in range(count):
            i = random.choices(range(len(qs)), weights=weights, k=1)[0]
            picked.append(qs.pop(i))
            weights.pop(i)
        qs = picked
    random.shuffle(qs)
    g = await db.fetchone("SELECT * FROM groups WHERE chat_id=?", (chat_id,))
    if not g:
        await db.execute("INSERT INTO groups(chat_id, title, active, added_at) VALUES(?,?,1,?)",
                         (chat_id, None, int(time.time())))
    s = GroupTest(chat_id, test_id, t["title"], len(qs), await db.get_int("group_seconds"))
    running[chat_id] = s
    s.task = asyncio.create_task(_run_group_test(bot, s, qs))
    return None


def stop_group_test(chat_id: int) -> bool:
    s = running.get(chat_id)
    if not s:
        return False
    s.cancelled = True
    return True


async def _run_group_test(bot: Bot, s: GroupTest, qs):
    thread = await _group_thread(s.chat_id)
    try:
        await bot.send_message(
            s.chat_id, f"📝 <b>Test boshlanadi: {html.escape(s.title)}</b>\n\n"
                       f"❓ Savollar: <b>{s.total}</b> ta\n⏱ Har biriga: <b>{s.seconds}</b> soniya\n\n"
                       "Tez va to'g'ri javob bering! Oxirida g'oliblar e'lon qilinadi. 🏆",
            message_thread_id=thread)
        await asyncio.sleep(5)
        sent = 0
        for i, row in enumerate(qs, 1):
            if s.cancelled:
                break
            res = await _send_group_poll(bot, s.chat_id, row, f"[{i}/{s.total}] ", row["id"], None, s.seconds)
            if res is None:
                continue
            sent += 1
            s.polls[res[0]] = (res[1], time.time())
            poll_session[res[0]] = s
            await asyncio.sleep(s.seconds + 3)
        await bot.send_message(s.chat_id, _session_result_text(s, sent), message_thread_id=thread)
        await db.execute("UPDATE groups SET last_post_at=? WHERE chat_id=?", (time.time(), s.chat_id))
    except Exception:  # noqa: BLE001
        log.exception("Guruh testi xatosi")
    finally:
        running.pop(s.chat_id, None)
        for pid in s.polls:
            poll_session.pop(pid, None)


def _session_result_text(s: GroupTest, sent: int) -> str:
    head = f"🏁 <b>{html.escape(s.title)}</b> — " + ("to'xtatildi" if s.cancelled else "yakunlandi!")
    if not s.scores:
        return head + f"\n\nYuborilgan savollar: {sent}\nHech kim javob bermadi 😔"
    ranked = sorted(s.scores.values(), key=lambda r: (-r[1], r[3]))
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [head, f"Savollar: {sent} · Ishtirokchilar: {len(ranked)}\n"]
    for i, (name, ok, ans, spent) in enumerate(ranked[:15], 1):
        lines.append(f"{medals.get(i, f'{i}.')} {html.escape(name)} — <b>{ok}/{sent}</b> · ⏱ {fmt_dur(spent)}")
    lines.append("\n<i>Teng ball bo'lsa, tezroq javob berganlar yuqorida.</i>")
    return "\n".join(lines)


# ---------------- avtomatik rejalashtiruvchi ----------------
_next_due = 0.0


def kick_scheduler():
    """Guruh sozlamalari o'zgarganda rejalashtiruvchini darhol qayta hisoblashga majbur qiladi."""
    global _next_due
    _next_due = 0.0


async def scheduler(bot: Bot):
    """Vaqti kelgan faol guruhlarga savol yuboradi.

    Bazaga faqat navbatdagi savol vaqti kelganda murojaat qiladi — shunda bepul onlayn baza
    qolgan paytda «uxlab» turadi va oylik limit tejaladi.
    """
    global _next_due
    while True:
        try:
            now_ts = time.time()
            if await db.get_int("group_enabled") and now_ts >= _next_due:
                now = datetime.now(TZ)
                start, end = await db.get_int("group_start_hour"), await db.get_int("group_end_hour")
                interval = await db.get_int("group_interval") * 60
                if start <= now.hour < end:
                    groups = await db.fetchall("SELECT * FROM groups WHERE active=1")
                    due_times = []
                    for g in groups:
                        if g["chat_id"] in running:
                            due_times.append(now_ts + 60)
                            continue  # guruhda admin tanlagan test ketyapti
                        if now_ts - g["last_post_at"] >= interval:
                            await post_question(bot, g["chat_id"])
                            due_times.append(time.time() + interval)
                            await asyncio.sleep(1)
                        else:
                            due_times.append(g["last_post_at"] + interval)
                    _next_due = min(due_times) if due_times else now_ts + 1800
                else:
                    _next_due = now_ts + 300  # ish vaqtidan tashqari — 5 daqiqada bir soatni tekshiradi (bazasiz)
        except Exception:  # noqa: BLE001 — rejalashtiruvchi hech qachon to'xtamasligi kerak
            log.exception("Scheduler xatosi")
            _next_due = time.time() + 60
        await asyncio.sleep(30)
