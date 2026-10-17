"""Shaxsiy (bot ichidagi) test: vaqtli savollar, natija, o'rin va foiz."""
import asyncio
import html
import logging
import random
import time
from dataclasses import dataclass, field
from typing import Optional

from aiogram import Bot
from aiogram.exceptions import TelegramAPIError

import db
from common import esc, fmt_dur, kb, pct

log = logging.getLogger(__name__)

NEXT_DELAY = 1.2  # javobdan keyin keyingi savolgacha pauza (soniya)


@dataclass
class Item:
    qid: int
    text: str
    options: list[str]       # aralashtirilgan tartibda
    perm: list[int]          # perm[yangi_indeks] = asl_indeks
    correct_pos: int         # aralashtirilgandan keyingi to'g'ri javob indeksi
    explanation: str


@dataclass
class Session:
    user_id: int
    chat_id: int
    attempt_id: int
    test_id: str
    title: str
    items: list[Item]
    seconds: int
    started: float = field(default_factory=time.time)
    pos: int = 0
    poll_id: Optional[str] = None
    answered: bool = False
    timer: Optional[asyncio.Task] = None
    correct: int = 0


class QuizManager:
    def __init__(self):
        self.sessions: dict[int, Session] = {}
        self.poll_owner: dict[str, int] = {}
        self.bot: Optional[Bot] = None

    def active(self, uid: int) -> Optional[Session]:
        return self.sessions.get(uid)

    async def start(self, bot: Bot, uid: int, chat_id: int, test_id: str) -> Optional[str]:
        """Testni boshlaydi. Xatolik bo'lsa matn qaytaradi."""
        self.bot = bot
        if uid in self.sessions:
            return "Sizda tugallanmagan test bor. Avval uni tugating yoki to'xtating."
        test = await db.fetchone("SELECT * FROM tests WHERE id=?", (test_id,))
        if not test:
            return "Test topilmadi."
        questions = await db.test_questions(test_id)
        if not questions:
            return "Bu testda hali savollar yo'q."
        random.shuffle(questions)
        n = test["per_attempt"] or len(questions)
        questions = questions[:n]
        items = []
        for q in questions:
            perm = list(range(len(q["options"])))
            random.shuffle(perm)
            items.append(Item(q["id"], q["q"], [q["options"][i] for i in perm], perm,
                              perm.index(q["correct"]), q["explanation"]))
        seconds = await db.get_int("private_seconds")
        aid = await db.execute("INSERT INTO attempts(user_id, test_id, started_at, total) VALUES(?,?,?,?)",
                               (uid, test_id, time.time(), len(items)))
        s = Session(uid, chat_id, aid, test_id, test["title"], items, seconds)
        self.sessions[uid] = s
        await bot.send_message(
            chat_id,
            f"🚀 <b>{html.escape(test['title'])}</b>\n"
            f"Savollar: <b>{len(items)}</b> ta · har biriga <b>{seconds}</b> soniya.\nOmad!",
            reply_markup=kb([[("⏹ Testni to'xtatish", "tst:stop")]]))
        await self._send_current(s)
        return None

    async def _send_current(self, s: Session):
        it = s.items[s.pos]
        s.answered = False
        prefix = f"[{s.pos + 1}/{len(s.items)}] "
        try:
            msg = await self.bot.send_poll(
                s.chat_id, question=esc((prefix + it.text)[:300]), options=[esc(o) for o in it.options],
                type="quiz", correct_option_id=it.correct_pos, is_anonymous=False, open_period=s.seconds,
                explanation=esc(it.explanation[:200]) or None)
        except TelegramAPIError as e:
            log.warning("Poll yuborilmadi (%s): %s", it.qid, e)
            await self._record(s, None)
            await self._advance(s)
            return
        if s.poll_id:
            self.poll_owner.pop(s.poll_id, None)
        s.poll_id = msg.poll.id
        self.poll_owner[s.poll_id] = s.user_id
        s.timer = asyncio.create_task(self._timeout(s, s.pos))

    async def _timeout(self, s: Session, pos: int):
        try:
            await asyncio.sleep(s.seconds + 1.5)
        except asyncio.CancelledError:
            return
        if self.sessions.get(s.user_id) is s and s.pos == pos and not s.answered:
            s.answered = True
            await self._record(s, None)
            await self._advance(s)

    async def on_answer(self, poll_id: str, uid: int, option_ids: list[int]) -> bool:
        owner = self.poll_owner.get(poll_id)
        if owner is None or owner != uid:
            return False
        s = self.sessions.get(uid)
        if not s or s.poll_id != poll_id or s.answered:
            return True
        s.answered = True
        if s.timer:
            s.timer.cancel()
        chosen = option_ids[0] if option_ids else None
        await self._record(s, chosen)
        await asyncio.sleep(NEXT_DELAY)
        if self.sessions.get(uid) is s:
            await self._advance(s)
        return True

    async def _record(self, s: Session, chosen_pos: Optional[int]):
        it = s.items[s.pos]
        ok = chosen_pos is not None and chosen_pos == it.correct_pos
        if ok:
            s.correct += 1
        orig = it.perm[chosen_pos] if chosen_pos is not None else None
        await db.execute("INSERT INTO answers(attempt_id, pos, question_id, chosen, is_correct) VALUES(?,?,?,?,?) "
                         "ON CONFLICT(attempt_id, pos) DO UPDATE SET question_id=excluded.question_id, "
                         "chosen=excluded.chosen, is_correct=excluded.is_correct", (s.attempt_id, s.pos, it.qid, orig, int(ok)))

    async def _advance(self, s: Session):
        s.pos += 1
        if s.pos >= len(s.items):
            await self._finish(s, "done")
        else:
            await self._send_current(s)

    async def stop(self, uid: int) -> bool:
        s = self.sessions.get(uid)
        if not s:
            return False
        if s.timer:
            s.timer.cancel()
        await self._finish(s, "stopped")
        return True

    async def _finish(self, s: Session, status: str):
        self.sessions.pop(s.user_id, None)
        if s.poll_id:
            self.poll_owner.pop(s.poll_id, None)
        now = time.time()
        dur = now - s.started
        await db.execute("UPDATE attempts SET finished_at=?, correct=?, duration=?, status=? WHERE id=?",
                         (now, s.correct, dur, status, s.attempt_id))
        total = len(s.items)
        if status == "stopped":
            text = (f"⏹ Test to'xtatildi.\nJavob berilgan savollar: {s.pos} / {total}\n"
                    f"To'g'ri javoblar: {s.correct}\n\nTo'xtatilgan test reytingga kirmaydi.")
            await self.bot.send_message(s.chat_id, text, reply_markup=kb([[("🔁 Qayta boshlash", f"tst:intro:{s.test_id}")]]))
            return
        text = await result_text(s.user_id, s.test_id, s.attempt_id)
        rows = [[("❌ Xatolarni ko'rish", f"tst:wrong:{s.attempt_id}"), ("🏆 Reyting", f"rank:{s.test_id}")]]
        if await db.get_int("allow_retake"):
            rows.append([("🔁 Qayta ishlash", f"tst:intro:{s.test_id}"), ("📝 Testlar", "tst:list")])
        else:
            rows.append([("📝 Testlar", "tst:list")])
        await self.bot.send_message(s.chat_id, text, reply_markup=kb(rows))


async def result_text(uid: int, test_id: str, attempt_id: int) -> str:
    a = await db.fetchone("SELECT * FROM attempts WHERE id=?", (attempt_id,))
    test = await db.fetchone("SELECT title FROM tests WHERE id=?", (test_id,))
    mode = await db.get_setting("ranking_mode")
    ranked = await db.ranking(test_id, mode)
    p = pct(a["correct"], a["total"])
    cur_ratio = a["correct"] / a["total"]
    others = [r for r in ranked if r["user_id"] != uid]
    better = sum(1 for r in others if (r["correct"] / r["total"] > cur_ratio + 1e-9)
                 or (abs(r["correct"] / r["total"] - cur_ratio) < 1e-9 and r["duration"] < a["duration"]))
    place = better + 1
    n = len(others) + 1
    worse = len(others) - better
    beat = round(100 * worse / len(others)) if others else 100

    if p >= 90:
        medal = "🥇 A'lo!"
    elif p >= 70:
        medal = "🥈 Yaxshi!"
    elif p >= 50:
        medal = "🥉 Yomon emas!"
    else:
        medal = "📖 Darsni yana bir bor takrorlang."

    lines = [f"🏁 <b>{html.escape(test['title'])}</b> — yakunlandi!", "",
             f"✅ To'g'ri javoblar: <b>{a['correct']} / {a['total']}</b> ({p}%)",
             f"⏱ Sarflangan vaqt: <b>{fmt_dur(a['duration'])}</b>",
             f"🏆 O'rningiz: <b>{place}</b> / {n}"]
    if others:
        lines.append(f"📈 Siz ishtirokchilarning <b>{beat}%</b> idan yaxshi natija ko'rsatdingiz")
    else:
        lines.append("📈 Siz bu testni birinchi bo'lib ishladingiz!")
    first = await db.fetchone("SELECT id FROM attempts WHERE user_id=? AND test_id=? AND status='done' "
                              "ORDER BY finished_at LIMIT 1", (uid, test_id))
    if first and first["id"] != attempt_id:
        if mode == "first":
            lines.append("\nℹ️ Bu takroriy urinish. Umumiy reytingda birinchi urinishingiz hisoblanadi.")
        else:
            lines.append("\nℹ️ Umumiy reytingda eng yaxshi natijangiz hisoblanadi.")
    lines += ["", medal]
    return "\n".join(lines)


async def mistakes_text(attempt_id: int, uid: int) -> str:
    a = await db.fetchone("SELECT * FROM attempts WHERE id=? AND user_id=?", (attempt_id, uid))
    if not a:
        return "Natija topilmadi."
    rows = await db.fetchall(
        "SELECT an.*, q.q, q.options, q.correct, q.explanation FROM answers an "
        "JOIN questions q ON q.id = an.question_id WHERE an.attempt_id=? AND an.is_correct=0 ORDER BY an.pos",
        (attempt_id,))
    if not rows:
        return "🎉 Xato yo'q — barcha javoblar to'g'ri!"
    import json
    out = [f"❌ <b>Xatolar: {len(rows)} ta</b>\n"]
    for r in rows:
        opts = json.loads(r["options"])
        yours = opts[r["chosen"]] if r["chosen"] is not None and r["chosen"] < len(opts) else "⏰ javob berilmadi"
        out.append(f"<b>{r['pos'] + 1}.</b> {html.escape(r['q'])}\n"
                   f"   Sizning javobingiz: {html.escape(yours)}\n"
                   f"   ✅ To'g'ri javob: <b>{html.escape(opts[r['correct']])}</b>"
                   + (f"\n   💡 {html.escape(r['explanation'])}" if r["explanation"] else ""))
    return "\n\n".join(out)


quiz = QuizManager()
