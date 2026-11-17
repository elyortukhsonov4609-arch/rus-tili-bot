"""Kichik guruh 2-paketini tekshirish va takror qo'shilgan darslarni tozalash.

Ishlatish (serverda):  ./venv/bin/python fix_kichik2.py        — faqat ko'rsatadi
                       ./venv/bin/python fix_kichik2.py --fix  — takrorlarni o'chiradi
"""
import asyncio
import json
import sys

import db
from config import SEED_DIR


async def main(fix: bool):
    await db.connect()
    data = json.loads((SEED_DIR / "kichik_v2.json").read_text(encoding="utf-8"))
    titles = {les["title"] for les in data["lessons"]}
    rows = await db.fetchall("SELECT id, num, title FROM lessons WHERE group_id=2 ORDER BY num, id")
    new = [r for r in rows if r["title"] in titles]
    linked = {r["lesson_id"] for r in await db.fetchall(
        "SELECT DISTINCT lesson_id FROM tests WHERE lesson_id IS NOT NULL")}
    print(f"Kichik guruh: jami {len(rows)} dars, ulardan yangi paket nomli: {len(new)}")
    by_title = {}
    for r in new:
        by_title.setdefault(r["title"], []).append(r)
    to_delete = []
    for title, rs in by_title.items():
        keep = [r for r in rs if r["id"] in linked] or rs[:1]
        for r in rs:
            mark = "QOLADI" if r in keep[:1] else "TAKROR"
            print(f"  {r['num']:>3}  id={r['id']:<6} {mark:7} {title}")
            if r not in keep[:1]:
                to_delete.append(r["id"])
    t = await db.fetchone("SELECT COUNT(*) AS c FROM tests WHERE id LIKE 'k2_%'")
    q = await db.fetchone("SELECT COUNT(*) AS c FROM questions WHERE test_id LIKE 'k2_%'")
    print(f"Yangi testlar: {t['c']} ta (kerak 44), savollar: {q['c']} ta (kerak 1320)")
    if not to_delete:
        print("Takror dars yo'q — hammasi joyida.")
        return
    print(f"Takror darslar: {len(to_delete)} ta")
    if not fix:
        print("O'chirish uchun:  ./venv/bin/python fix_kichik2.py --fix")
        return
    for lid in to_delete:
        await db.execute("DELETE FROM lesson_pages WHERE lesson_id=?", (lid,))
        await db.execute("DELETE FROM lesson_reads WHERE lesson_id=?", (lid,))
        await db.execute("DELETE FROM lessons WHERE id=?", (lid,))
    # raqamlarni ketma-ket qilish: qolgan yangi darslar eski darslardan keyin tartib bilan
    rows = await db.fetchall("SELECT id, num, title FROM lessons WHERE group_id=2 ORDER BY num, id")
    old = [r for r in rows if r["title"] not in titles]
    n = max([r["num"] for r in old] or [0])
    order = [les["title"] for les in data["lessons"]]
    for title in order:
        for r in rows:
            if r["title"] == title:
                n += 1
                await db.execute("UPDATE lessons SET num=? WHERE id=?", (n, r["id"]))
    print(f"O'chirildi: {len(to_delete)} ta takror dars. Darslar raqami tartiblandi.")


if __name__ == "__main__":
    asyncio.run(main("--fix" in sys.argv))
