"""Ota-onalar: farzand havolasi orqali ulanish va haftalik hisobot."""
import asyncio
import hashlib
import html
import logging
import time
from urllib.parse import urlencode
from datetime import datetime, timedelta

from aiogram import Bot, F, Router
from aiogram.dispatcher.event.bases import SkipHandler
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import CallbackQuery, Message

import db
from common import BTN_CHILD_REPORT, BTN_PARENT, BTN_PARENT_OLD, Approved, PrivateChat, is_admin, kb, main_menu, parent_menu, pct
from config import ADMIN_IDS, BOT_TOKEN, TZ

log = logging.getLogger(__name__)

# Ota-ona uchun (ro'yxatdan o'tmagan foydalanuvchi ham kira oladi) — student.router dan OLDIN ulanadi
router = Router(name="parents")
router.message.filter(PrivateChat())
router.callback_query.filter(PrivateChat())

# O'quvchi uchun tugma — student.app bilan birga
child_router = Router(name="parents_child")
child_router.message.filter(PrivateChat(), Approved())
child_router.callback_query.filter(PrivateChat(), Approved())

WEEKDAYS = ["Dushanba", "Seshanba", "Chorshanba", "Payshanba", "Juma", "Shanba", "Yakshanba"]


def _sig(child_id: int) -> str:
    return hashlib.sha256(f"{BOT_TOKEN}:parent:{child_id}".encode()).hexdigest()[:10]


async def invite_link(bot: Bot, child_id: int) -> str:
    me = await bot.me()
    return f"https://t.me/{me.username}?start=p{child_id}_{_sig(child_id)}"


async def is_parent(uid: int) -> bool:
    return bool(await db.fetchone("SELECT 1 FROM parents WHERE parent_id=?", (uid,)))


async def children_of(uid: int):
    return await db.fetchall("SELECT p.child_id, u.full_name FROM parents p JOIN users u ON u.id=p.child_id "
                             "WHERE p.parent_id=? ORDER BY u.full_name", (uid,))


# ---------------- ota-ona havola orqali kiradi ----------------
@router.message(CommandStart(deep_link=True))
async def start_with_link(msg: Message, command: CommandObject, bot: Bot):
    arg = command.args or ""
    if not arg.startswith("p") or "_" not in arg:
        raise SkipHandler()
    try:
        child_part, sig = arg[1:].split("_", 1)
        child_id = int(child_part)
    except ValueError:
        raise SkipHandler()
    if sig != _sig(child_id):
        await msg.answer("❗ Havola noto'g'ri. Farzandingizdan havolani qaytadan so'rang.")
        return
    child = await db.get_user(child_id)
    if not child or child["status"] != "approved":
        await msg.answer("❗ Bu o'quvchi topilmadi yoki hali tasdiqlanmagan.")
        return
    uid = msg.from_user.id
    if uid == child_id:
        await msg.answer("Bu havola ota-onangiz uchun. Uni ota-onangizga yuboring 🙂")
        return
    me = await db.get_user(uid)
    me_student = bool(me and me["status"] == "approved")  # bu telefon boshqa farzandning akkaunti ham bo'lishi mumkin
    await db.execute("INSERT INTO parents(parent_id, child_id, name, username, created_at) VALUES(?,?,?,?,?) "
                     "ON CONFLICT DO NOTHING",
                     (uid, child_id, msg.from_user.full_name, msg.from_user.username, int(time.time())))
    await msg.answer(f"👋 Assalomu alaykum!\nSiz <b>{html.escape(child['full_name'])}</b>ning ota-onasi sifatida "
                     "ulandingiz ✅\n\nHar hafta farzandingizning darslari, test natijalari va faolligi haqida "
                     "hisobot olasiz. Istalgan vaqtda «📊 " + ("Haftalik hisobot" if me_student else "Farzandim hisoboti") +
                     "» tugmasini bosib ko'rishingiz mumkin.",
                     reply_markup=main_menu(uid) if me_student else parent_menu())
    uname = f"@{msg.from_user.username}" if msg.from_user.username else "username yo'q"
    for a in ADMIN_IDS:
        try:
            await bot.send_message(a, f"👨‍👩‍👦 <b>{html.escape(child['full_name'])}</b>ning ota-onasi ulandi: "
                                      f"{html.escape(msg.from_user.full_name)} ({uname})",
                                   reply_markup=kb([[("❌ Uzib qo'yish", f"adm:punl:{uid}:{child_id}")]]))
        except TelegramAPIError:
            pass


@router.message(CommandStart())
async def parent_start(msg: Message):
    uid = msg.from_user.id
    if is_admin(uid) or not await is_parent(uid):
        raise SkipHandler()
    u = await db.get_user(uid)
    if u and u["status"] == "approved":
        raise SkipHandler()
    kids = await children_of(uid)
    names = ", ".join(html.escape(k["full_name"]) for k in kids) or "—"
    await msg.answer(f"👋 Assalomu alaykum! Farzand(lar)ingiz: <b>{names}</b>\n"
                     "Hisobotni ko'rish uchun quyidagi tugmani bosing.", reply_markup=parent_menu())


@router.message(F.text == BTN_CHILD_REPORT)
async def parent_report_btn(msg: Message):
    kids = await children_of(msg.from_user.id)
    if not kids:
        raise SkipHandler()
    for k in kids:
        await msg.answer(await build_report(k["child_id"]))


@router.message()
async def parent_other(msg: Message):
    """Ota-ona boshqa narsa yozsa — menyuni eslatadi (o'quvchi va adminlarga tegmaydi)."""
    uid = msg.from_user.id
    if is_admin(uid) or not await is_parent(uid):
        raise SkipHandler()
    u = await db.get_user(uid)
    if u and u["status"] in ("approved", "pending"):
        raise SkipHandler()
    await msg.answer("Hisobotni ko'rish uchun «📊 Farzandim hisoboti» tugmasini bosing.", reply_markup=parent_menu())


# ---------------- o'quvchi (ota-ona telefoni): hisobot va boshqa telefonni ulash ----------------
# Kichik o'quvchilarda telefon yo'q — bot odatda ota-onaning telefonida. Shuning uchun hisobot shu akkauntning
# o'ziga keladi, havola esa ikkinchi ota-ona (masalan, dadasi) ham o'z telefonida hisobot olishi uchun.
@child_router.message(F.text.in_({BTN_PARENT, BTN_PARENT_OLD}))
async def child_parent_btn(msg: Message, bot: Bot):
    uid = msg.from_user.id
    await msg.answer(await build_report(uid))
    for k in await children_of(uid):  # shu telefonga ulangan boshqa farzand (aka-uka, opa-singil)
        if k["child_id"] != uid:
            await msg.answer(await build_report(k["child_id"]))
    link = await invite_link(bot, uid)
    linked = await db.fetchall("SELECT name FROM parents WHERE child_id=?", (uid,))
    share = "https://t.me/share/url?" + urlencode(
        {"url": link, "text": "Farzandimizning rus tili natijalarini shu bot orqali kuzatib boring"})
    text = ("📊 Bu hisobot har hafta shu telefonga avtomatik keladi.\n\n"
            "👨‍👩‍👦 <b>Boshqa telefonda ham olish</b> (masalan, dadasi yoki onasi): quyidagi havolani o'sha odamga "
            "yuboring. U havolani bosib botga kirsa, hisobot unga ham keladi.\n\n"
            f"🔗 {link}\n\n" +
            (f"✅ Ulangan: {', '.join(html.escape(p['name'] or '—') for p in linked)}" if linked else
             "Hozircha boshqa telefon ulanmagan."))
    await msg.answer(text, reply_markup=kb([[("📤 Havolani yuborish", "url:" + share)]]),
                     disable_web_page_preview=True)


# ---------------- hisobot ----------------
async def weekly_points(gid, since: float) -> list[tuple[int, int]]:
    """Guruh a'zolarining haftalik ballari: botdagi + guruhdagi to'g'ri javoblar. [(user_id, ball)] kamayish tartibida."""
    members = [r["id"] for r in await db.fetchall("SELECT id FROM users WHERE status='approved' AND group_id=?",
                                                  (gid,))]
    pts = {m: 0 for m in members}
    for r in await db.fetchall("SELECT a.user_id AS u, SUM(an.is_correct) AS c FROM answers an "
                               "JOIN attempts a ON a.id = an.attempt_id WHERE a.started_at >= ? GROUP BY a.user_id",
                               (since,)):
        if r["u"] in pts:
            pts[r["u"]] += r["c"] or 0
    for r in await db.fetchall("SELECT user_id AS u, SUM(ok) AS c FROM group_answers WHERE answered_at >= ? "
                               "GROUP BY user_id", (since,)):
        if r["u"] in pts:
            pts[r["u"]] += r["c"] or 0
    return sorted(pts.items(), key=lambda x: -x[1])


async def build_report(child_id: int, days: int = 7) -> str:
    from daily import streak  # aylanma importdan qochish uchun
    u = await db.get_user(child_id)
    if not u:
        return "O'quvchi topilmadi."
    now = datetime.now(TZ)
    start = (now - timedelta(days=days - 1)).replace(hour=0, minute=0, second=0, microsecond=0)
    since = start.timestamp()
    gname = await db.group_name(u["group_id"])
    reads = await db.fetchall("SELECT l.num, l.short FROM lesson_reads r JOIN lessons l ON l.id=r.lesson_id "
                              "WHERE r.user_id=? AND r.read_at >= ? ORDER BY l.num", (child_id, int(since)))
    atts = await db.fetchall("SELECT a.test_id, a.correct, a.total, t.title FROM attempts a JOIN tests t ON t.id=a.test_id "
                             "WHERE a.user_id=? AND a.status='done' AND a.started_at >= ? ORDER BY a.finished_at",
                             (child_id, since))
    best = {}
    for a in atts:
        r = a["correct"] / a["total"] if a["total"] else 0
        if a["test_id"] not in best or r > best[a["test_id"]][0]:
            best[a["test_id"]] = (r, a)
    daily_days = (await db.fetchone("SELECT COUNT(*) AS n FROM daily_log WHERE user_id=? AND day >= ?",
                                    (child_id, start.date().isoformat())))["n"]
    grp = await db.fetchone("SELECT COUNT(*) AS n, SUM(ok) AS c FROM group_answers WHERE user_id=? AND answered_at >= ?",
                            (child_id, since))
    st = await streak(child_id)
    ranking = await weekly_points(u["group_id"], since)
    place = next((i for i, (uid, _) in enumerate(ranking, 1) if uid == child_id), None)
    my_pts = dict(ranking).get(child_id, 0)

    lines = [f"📊 <b>Haftalik hisobot</b> · {start.strftime('%d.%m')} – {now.strftime('%d.%m')}",
             f"👦 <b>{html.escape(u['full_name'])}</b> · {html.escape(gname)}", ""]
    if reads:
        lines.append(f"📚 O'qilgan darslar: {len(reads)} ta — " + ", ".join(f"{r['num']}-dars" for r in reads))
    else:
        lines.append("📚 Bu hafta yangi dars o'qimadi")
    if best:
        lines.append("📝 Testlar:")
        for r, a in best.values():
            lines.append(f"   • {html.escape(a['title'])} — {a['correct']}/{a['total']} ({pct(a['correct'], a['total'])}%)")
    else:
        lines.append("📝 Bu hafta test ishlamadi")
    lines.append(f"📅 Kunlik vazifa: <b>{daily_days} / {days}</b> kun")
    lines.append(f"🔥 Seriya: {st} kun ketma-ket")
    if grp["n"]:
        lines.append(f"👥 Guruhdagi savollar: {grp['c'] or 0} ta to'g'ri javob ({grp['n']} tadan)")
    if place:
        lines.append(f"🏆 Guruhdagi haftalik o'rni: <b>{place} / {len(ranking)}</b> ({my_pts} ball)")
    avg = (sum(r for r, _ in best.values()) / len(best) * 100) if best else 0
    lines.append("")
    if daily_days >= 5 and (avg >= 80 or not best):
        lines.append("🌟 A'lo hafta! Farzandingiz muntazam shug'ullanmoqda.")
    elif daily_days >= 3 or avg >= 60:
        lines.append("👍 Yaxshi. Har kuni shug'ullansa, natija yanada oshadi.")
    else:
        lines.append("⚠️ Bu hafta faollik past. Iltimos, farzandingiz har kuni botdagi vazifani bajarishini "
                     "nazorat qiling.")
    return "\n".join(lines)


async def send_reports_all(bot: Bot) -> int:
    """Hisobot: 1) har bir o'quvchi akkauntiga (ko'pincha bu ota-onaning telefoni); 2) ulangan qo'shimcha telefonlarga."""
    n = 0
    cache = {}
    for u in await db.fetchall("SELECT id FROM users WHERE status='approved'"):
        cache[u["id"]] = await build_report(u["id"])
        try:
            await bot.send_message(u["id"], cache[u["id"]])
            n += 1
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
    for p in await db.fetchall("SELECT parent_id, child_id FROM parents"):
        if p["child_id"] not in cache:
            continue  # o'quvchi chiqarilgan
        # qo'shimcha telefon o'zi ham o'quvchi akkaunti bo'lsa (masalan, aka-ukaning biri) — menyusini almashtirmaymiz
        markup = None if p["parent_id"] in cache else parent_menu()
        try:
            await bot.send_message(p["parent_id"], cache[p["child_id"]], reply_markup=markup)
            n += 1
        except TelegramAPIError:
            pass
        await asyncio.sleep(0.05)
    return n
