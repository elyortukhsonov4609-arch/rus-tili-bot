"""O'quvchi bo'limi: ro'yxatdan o'tish, darsliklar, testlar, natijalar, reyting."""
import html
import time

from aiogram import Bot, F, Router
from aiogram.filters import Command, CommandStart, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, ReplyKeyboardRemove

import db
from common import (BTN_LESSONS, BTN_RATING, BTN_RESULTS, BTN_TESTS, Approved, PrivateChat, chunk_text, fmt_dur,
                    is_admin, kb, main_menu, pct, safe_answer, safe_edit)
from config import ADMIN_IDS
from quiz import mistakes_text, quiz

router = Router(name="student")
router.message.filter(PrivateChat())
router.callback_query.filter(PrivateChat())


class Reg(StatesGroup):
    name = State()


# ======================= Ro'yxatdan o'tish =======================
@router.message(CommandStart())
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()
    uid = msg.from_user.id
    if is_admin(uid):
        await msg.answer("👋 Assalomu alaykum, admin! Bot ishga tayyor.\n"
                         "Boshqaruv uchun «⚙️ Admin panel» tugmasini bosing.", reply_markup=main_menu(uid))
        return
    u = await db.get_user(uid)
    if u and u["status"] == "approved":
        await msg.answer(f"👋 Xush kelibsiz, {html.escape(u['full_name'])}!\nQuyidagi bo'limlardan birini tanlang.",
                         reply_markup=main_menu(uid))
    elif u and u["status"] == "pending":
        await msg.answer("⏳ Arizangiz ko'rib chiqilmoqda. Admin ruxsat bergach, sizga xabar keladi.")
    elif u and u["status"] in ("blocked", "rejected"):
        await msg.answer("🚫 Sizga botdan foydalanishga ruxsat berilmagan. Iltimos, o'qituvchingiz bilan bog'laning.")
    else:
        await state.set_state(Reg.name)
        await msg.answer("👋 Assalomu alaykum! Bu bot rus tili darslari va testlari uchun.\n\n"
                         "Botdan foydalanish uchun o'qituvchi ruxsati kerak.\n"
                         "✍️ <b>Ism va familiyangizni</b> yozib yuboring (masalan: <i>Aliyev Sardor</i>):",
                         reply_markup=ReplyKeyboardRemove())


@router.message(Reg.name, F.text)
async def reg_name(msg: Message, state: FSMContext, bot: Bot):
    name = " ".join(msg.text.split())
    if len(name) < 3 or len(name) > 60 or name.startswith("/"):
        await msg.answer("Iltimos, ism va familiyangizni to'g'ri yozing (3–60 belgi).")
        return
    await state.clear()
    uid = msg.from_user.id
    await db.add_user(uid, name, msg.from_user.username)
    await msg.answer("✅ Arizangiz o'qituvchiga yuborildi. Ruxsat berilgach, sizga xabar keladi.")
    uname = f"@{msg.from_user.username}" if msg.from_user.username else "username yo'q"
    for admin in ADMIN_IDS:
        try:
            await bot.send_message(
                admin, f"🆕 <b>Yangi ariza</b>\n👤 {html.escape(name)}\n🔗 {uname}\n🆔 <code>{uid}</code>",
                reply_markup=kb([[("✅ Ruxsat berish", f"adm:ok:{uid}"), ("❌ Rad etish", f"adm:no:{uid}")]]))
        except Exception:  # noqa: BLE001 — admin botni bloklagan bo'lishi mumkin
            pass


# Ruxsat berilmagan foydalanuvchilar uchun ushlagich (eng oxirida ro'yxatdan o'tadi — main.py ga qarang)
fallback = Router(name="fallback")
fallback.message.filter(PrivateChat())
fallback.callback_query.filter(PrivateChat())


@fallback.message()
async def not_allowed(msg: Message, state: FSMContext):
    u = await db.get_user(msg.from_user.id)
    if u and u["status"] == "pending":
        await msg.answer("⏳ Arizangiz hali ko'rib chiqilmoqda. Iltimos, kuting.")
    elif u and u["status"] in ("blocked", "rejected"):
        await msg.answer("🚫 Sizga botdan foydalanishga ruxsat berilmagan.")
    else:
        await cmd_start(msg, state)


@fallback.callback_query()
async def not_allowed_cb(cb: CallbackQuery):
    await cb.answer("Botdan foydalanish uchun o'qituvchi ruxsati kerak. /start ni bosing.", show_alert=True)


# ======================= Quyidagilar faqat ruxsat berilganlar uchun =======================
app = Router(name="student_app")
app.message.filter(PrivateChat(), Approved())
app.callback_query.filter(PrivateChat(), Approved())


@app.message(Command("help"))
async def cmd_help(msg: Message):
    await msg.answer("📚 <b>Darslar</b> — mavzuni o'qing.\n"
                     "📝 <b>Testlar</b> — o'qigan darsingiz bo'yicha test ishlang.\n"
                     "📊 <b>Natijalarim</b> — barcha natijalaringiz.\n"
                     "🏆 <b>Reyting</b> — eng yaxshi natijalar.\n\n"
                     "Har bir savolga vaqt beriladi — tez va to'g'ri javob bering!",
                     reply_markup=main_menu(msg.from_user.id))


# ---------------- Darslar ----------------
async def lessons_markup(uid: int):
    lessons = await db.fetchall("SELECT * FROM lessons WHERE is_open=1 ORDER BY num")
    read = {r["lesson_id"] for r in await db.fetchall("SELECT lesson_id FROM lesson_reads WHERE user_id=?", (uid,))}
    rows = [[(f"{'✅' if l['id'] in read else '📖'} {l['num']}-dars: {l['short']}", f"les:open:{l['id']}:0")]
            for l in lessons]
    return rows


@app.message(F.text == BTN_LESSONS)
async def lessons_list(msg: Message):
    rows = await lessons_markup(msg.from_user.id)
    if not rows:
        await msg.answer("Hozircha ochiq darslar yo'q.")
        return
    await msg.answer("📚 <b>Darslar</b>\nAvval darsni o'qing, keyin test ishlang. ✅ — o'qilgan darslar.",
                     reply_markup=kb(rows))


@app.callback_query(F.data == "les:list")
async def lessons_list_cb(cb: CallbackQuery):
    rows = await lessons_markup(cb.from_user.id)
    await safe_edit(cb, "📚 <b>Darslar</b>\nAvval darsni o'qing, keyin test ishlang. ✅ — o'qilgan darslar.",
                    kb(rows) if rows else None)
    await cb.answer()


@app.callback_query(F.data.startswith("les:open:"))
async def lesson_page(cb: CallbackQuery):
    _, _, lid, page = cb.data.split(":")
    lid, page = int(lid), int(page)
    les = await db.fetchone("SELECT * FROM lessons WHERE id=?", (lid,))
    if not les or (not les["is_open"] and not is_admin(cb.from_user.id)):
        await cb.answer("Bu dars hozircha yopiq.", show_alert=True)
        return
    pages = await db.fetchall("SELECT html FROM lesson_pages WHERE lesson_id=? ORDER BY idx", (lid,))
    n = len(pages)
    if n == 0:
        text = f"📖 <b>{les['num']}-dars: {html.escape(les['title'])}</b>\n\nDarslik matni hali yuklanmagan."
    else:
        page = max(0, min(page, n - 1))
        text = f"📖 <b>{les['num']}-dars</b> · sahifa {page + 1}/{n}\n\n" + pages[page]["html"]
    nav = []
    if n and page > 0:
        nav.append(("⬅️ Oldingi", f"les:open:{lid}:{page - 1}"))
    if n and page < n - 1:
        nav.append(("Keyingi ➡️", f"les:open:{lid}:{page + 1}"))
    rows = [nav] if nav else []
    if les["file_id"]:
        rows.append([("📎 Darslik faylini yuklab olish", f"les:file:{lid}")])
    if n == 0 or page == n - 1:
        rows.append([("✅ O'qib chiqdim — testga o'tish", f"les:done:{lid}")])
    rows.append([("📚 Darslar ro'yxati", "les:list")])
    await safe_edit(cb, text, kb(rows))
    await cb.answer()


@app.callback_query(F.data.startswith("les:file:"))
async def lesson_file(cb: CallbackQuery):
    lid = int(cb.data.split(":")[2])
    les = await db.fetchone("SELECT * FROM lessons WHERE id=?", (lid,))
    if les and les["file_id"]:
        await cb.message.answer_document(les["file_id"], caption=f"📎 {les['num']}-dars: {html.escape(les['title'])}")
    await cb.answer()


@app.callback_query(F.data.startswith("les:done:"))
async def lesson_done(cb: CallbackQuery):
    lid = int(cb.data.split(":")[2])
    await db.execute("INSERT INTO lesson_reads(user_id, lesson_id, read_at) VALUES(?,?,?) ON CONFLICT DO NOTHING",
                     (cb.from_user.id, lid, int(time.time())))
    tests = await db.fetchall("SELECT * FROM tests WHERE lesson_id=? AND is_open=1 ORDER BY sort", (lid,))
    if not tests:
        await cb.answer("✅ Dars o'qildi deb belgilandi!", show_alert=True)
        await lessons_list_cb(cb)
        return
    rows = [[(f"📝 {t['title']}", f"tst:intro:{t['id']}")] for t in tests]
    rows.append([("📚 Darslar ro'yxati", "les:list")])
    await safe_edit(cb, "✅ Barakalla, dars o'qildi!\nEndi bilimingizni sinab ko'ring:", kb(rows))
    await cb.answer()


# ---------------- Testlar ----------------
async def tests_markup(uid: int):
    tests = await db.fetchall("SELECT t.*, l.num AS lnum FROM tests t LEFT JOIN lessons l ON l.id=t.lesson_id "
                              "WHERE t.is_open=1 ORDER BY t.sort, t.title")
    read = {r["lesson_id"] for r in await db.fetchall("SELECT lesson_id FROM lesson_reads WHERE user_id=?", (uid,))}
    need_read = await db.get_int("require_read") and not is_admin(uid)
    best = {r["test_id"]: r for r in await db.fetchall(
        "SELECT test_id, MAX(CAST(correct AS REAL)/total) AS r FROM attempts WHERE user_id=? AND status='done' "
        "GROUP BY test_id", (uid,))}
    rows = []
    for t in tests:
        if need_read and t["lesson_id"] and t["lesson_id"] not in read:
            icon = "🔒"
        elif t["id"] in best:
            icon = f"✅{round(best[t['id']]['r'] * 100)}%"
        else:
            icon = "📝"
        rows.append([(f"{icon} {t['title']}", f"tst:intro:{t['id']}")])
    return rows


@app.message(F.text == BTN_TESTS)
async def tests_list(msg: Message):
    rows = await tests_markup(msg.from_user.id)
    await msg.answer("📝 <b>Testlar</b>\n🔒 — avval darsni o'qing · ✅ — eng yaxshi natijangiz",
                     reply_markup=kb(rows) if rows else None)


@app.callback_query(F.data == "tst:list")
async def tests_list_cb(cb: CallbackQuery):
    rows = await tests_markup(cb.from_user.id)
    await cb.message.answer("📝 <b>Testlar</b>\n🔒 — avval darsni o'qing · ✅ — eng yaxshi natijangiz",
                            reply_markup=kb(rows) if rows else None)
    await cb.answer()


@app.callback_query(F.data.startswith("tst:intro:"))
async def test_intro(cb: CallbackQuery):
    tid = cb.data.split(":", 2)[2]
    uid = cb.from_user.id
    t = await db.fetchone("SELECT t.*, l.num AS lnum, l.short AS lshort FROM tests t "
                          "LEFT JOIN lessons l ON l.id=t.lesson_id WHERE t.id=?", (tid,))
    if not t or (not t["is_open"] and not is_admin(uid)):
        await cb.answer("Bu test hozircha yopiq.", show_alert=True)
        return
    if t["lesson_id"] and await db.get_int("require_read") and not is_admin(uid):
        r = await db.fetchone("SELECT 1 FROM lesson_reads WHERE user_id=? AND lesson_id=?", (uid, t["lesson_id"]))
        if not r:
            await cb.answer(f"🔒 Avval {t['lnum']}-darsni ({t['lshort']}) o'qib chiqing!", show_alert=True)
            return
    done = await db.fetchone("SELECT COUNT(*) AS n FROM attempts WHERE user_id=? AND test_id=? AND status='done'",
                             (uid, tid))
    if done["n"] and not await db.get_int("allow_retake") and not is_admin(uid):
        await cb.answer("Siz bu testni ishlagansiz. Qayta ishlash o'chirilgan.", show_alert=True)
        return
    nq = await db.fetchone("SELECT COUNT(*) AS n FROM questions WHERE test_id=?", (tid,))
    n = min(t["per_attempt"] or nq["n"], nq["n"])
    sec = await db.get_int("private_seconds")
    text = (f"📝 <b>{html.escape(t['title'])}</b>\n\n"
            f"❓ Savollar soni: <b>{n}</b>\n⏱ Har bir savolga: <b>{sec} soniya</b>\n"
            f"⌛ Eng ko'pi bilan: ~{fmt_dur(n * sec)}\n\n"
            "Natijangiz to'g'ri javoblar soni va sarflangan vaqtga qarab baholanadi. Tayyormisiz?")
    if done["n"]:
        text += f"\n\nℹ️ Siz bu testni avval {done['n']} marta ishlagansiz."
    await cb.message.answer(text, reply_markup=kb([[("▶️ Boshlash", f"tst:start:{tid}")],
                                                    [("🏆 Reyting", f"rank:{tid}"), ("📝 Testlar", "tst:list")]]))
    await cb.answer()


@app.callback_query(F.data.startswith("tst:start:"))
async def test_start(cb: CallbackQuery, bot: Bot):
    tid = cb.data.split(":", 2)[2]
    await cb.answer()
    try:
        await cb.message.edit_reply_markup(reply_markup=None)
    except Exception:  # noqa: BLE001
        pass
    err = await quiz.start(bot, cb.from_user.id, cb.message.chat.id, tid)
    if err:
        await cb.message.answer(err, reply_markup=kb([[("⏹ Testni to'xtatish", "tst:stop")]])
                                if "tugallanmagan" in err else None)


@app.callback_query(F.data == "tst:stop")
async def test_stop(cb: CallbackQuery):
    ok = await quiz.stop(cb.from_user.id)
    await cb.answer("Test to'xtatildi." if ok else "Faol test yo'q.")


@app.message(Command("stop"))
async def cmd_stop(msg: Message):
    if not await quiz.stop(msg.from_user.id):
        await msg.answer("Faol test yo'q.")


@app.callback_query(F.data.startswith("tst:wrong:"))
async def test_wrong(cb: CallbackQuery):
    aid = int(cb.data.split(":")[2])
    text = await mistakes_text(aid, cb.from_user.id)
    for part in chunk_text(text):
        await safe_answer(cb.message, part)
    await cb.answer()


# ---------------- Natijalar va reyting ----------------
@app.message(F.text == BTN_RESULTS)
async def my_results(msg: Message):
    rows = await db.fetchall(
        "SELECT a.*, t.title FROM attempts a JOIN tests t ON t.id=a.test_id "
        "WHERE a.user_id=? AND a.status='done' ORDER BY a.finished_at DESC LIMIT 30", (msg.from_user.id,))
    if not rows:
        await msg.answer("Siz hali test ishlamagansiz. «📝 Testlar» bo'limiga o'ting.")
        return
    lines = ["📊 <b>Natijalaringiz</b> (oxirgi 30 ta)\n"]
    for r in rows:
        lines.append(f"• {html.escape(r['title'])}\n   ✅ {r['correct']}/{r['total']} ({pct(r['correct'], r['total'])}%)"
                     f" · ⏱ {fmt_dur(r['duration'])}")
    for part in chunk_text("\n".join(lines)):
        await msg.answer(part)


@app.message(F.text == BTN_RATING)
async def rating_menu(msg: Message):
    tests = await db.fetchall("SELECT * FROM tests WHERE is_open=1 ORDER BY sort")
    rows = [[(f"🏆 {t['title']}", f"rank:{t['id']}")] for t in tests]
    await msg.answer("🏆 Qaysi test reytingini ko'rmoqchisiz?", reply_markup=kb(rows) if rows else None)


async def leaderboard_text(tid: str, uid: int, limit: int = 10) -> str:
    t = await db.fetchone("SELECT title FROM tests WHERE id=?", (tid,))
    if not t:
        return "Test topilmadi."
    mode = await db.get_setting("ranking_mode")
    ranked = await db.ranking(tid, mode)
    if not ranked:
        return f"🏆 <b>{html.escape(t['title'])}</b>\n\nHali hech kim bu testni ishlamagan."
    medals = {1: "🥇", 2: "🥈", 3: "🥉"}
    lines = [f"🏆 <b>{html.escape(t['title'])}</b>\nIshtirokchilar: {len(ranked)}\n"]
    me = None
    for i, r in enumerate(ranked, 1):
        if r["user_id"] == uid:
            me = (i, r)
        if i <= limit:
            name = html.escape(r["full_name"])
            if r["user_id"] == uid:
                name = f"<b>{name} (siz)</b>"
            lines.append(f"{medals.get(i, f'{i}.')} {name} — {r['correct']}/{r['total']} · ⏱ {fmt_dur(r['duration'])}")
    if me and me[0] > limit:
        i, r = me
        lines.append(f"…\n<b>{i}. Siz</b> — {r['correct']}/{r['total']} · ⏱ {fmt_dur(r['duration'])}")
    lines.append("\n<i>" + ("Har bir o'quvchining birinchi urinishi hisoblanadi." if mode == "first"
                            else "Har bir o'quvchining eng yaxshi natijasi hisoblanadi.") + "</i>")
    return "\n".join(lines)


@app.callback_query(F.data.startswith("rank:"))
async def rating_show(cb: CallbackQuery):
    tid = cb.data.split(":", 1)[1]
    await cb.message.answer(await leaderboard_text(tid, cb.from_user.id))
    await cb.answer()


@app.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer()
