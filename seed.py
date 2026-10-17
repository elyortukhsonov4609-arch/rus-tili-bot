"""Birinchi ishga tushganda darsliklar va testlarni bazaga yuklaydi."""
import json
import logging

import db
from config import SEED_DIR

log = logging.getLogger(__name__)

# test id -> (darsning tartib raqami yoki None, saralash tartibi, bitta urinishdagi savollar soni)
TEST_PLACEMENT = {
    "t_l1": (1, 10, 30),
    "t_l2": (2, 20, 30),
    "t_l3": (3, 30, 30),
    "t_l4": (4, 40, 30),
    "t_rev14": (None, 45, 30),
    "t_exam14": (None, 46, 50),
    "t_l5": (5, 50, 30),
    "t_l6": (6, 60, 30),
    "t_l7": (7, 70, 30),
    "t_vocab15": (None, 75, 30),
}


async def seed_if_empty():
    row = await db.fetchone("SELECT COUNT(*) AS n FROM lessons")
    if row["n"]:
        return
    log.info("Baza bo'sh — darsliklar va testlar yuklanmoqda")
    lessons = json.loads((SEED_DIR / "lessons.json").read_text(encoding="utf-8"))
    num_to_id = {}
    for les in lessons:
        lid = await db.execute("INSERT INTO lessons(num, title, short) VALUES(?,?,?)",
                               (les["num"], les["title"], les["short"]))
        num_to_id[les["num"]] = lid
        for i, page in enumerate(les["pages"]):
            await db.execute("INSERT INTO lesson_pages(lesson_id, idx, html) VALUES(?,?,?)", (lid, i, page))

    tests = []
    for name in ("tests_teacher.json", "tests_extra.json"):
        tests += json.loads((SEED_DIR / name).read_text(encoding="utf-8"))
    for t in tests:
        lesson_num, sort, per = TEST_PLACEMENT.get(t["id"], (None, 100, 30))
        await db.execute("INSERT INTO tests(id, title, lesson_id, sort, per_attempt, source) VALUES(?,?,?,?,?,?)",
                         (t["id"], t["title"], num_to_id.get(lesson_num), sort, per, t.get("source")))
        await db.replace_questions(t["id"], t["questions"])

    fun = json.loads((SEED_DIR / "fun.json").read_text(encoding="utf-8"))
    for q in fun:
        await db.execute("INSERT INTO fun_questions(q, options, correct, explanation) VALUES(?,?,?,?)",
                         (q["q"], json.dumps(q["options"], ensure_ascii=False), q["correct"], q.get("explanation", "")))
    log.info("Yuklandi: %d dars, %d test, %d qiziqarli savol", len(lessons), len(tests), len(fun))
