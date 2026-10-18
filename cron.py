"""Vaqtga bog'liq ishlar: rejali guruh testlari, kunlik vazifa, eslatma, ota-onalarga haftalik hisobot.

Har 30 soniyada vaqtni tekshiradi. Sozlamalar xotirada saqlanadi, shuning uchun bazaga faqat biror ish
bajarilishi kerak bo'lganda murojaat qilinadi (bepul onlayn baza limitini tejaydi).
"""
import asyncio
import logging
from datetime import datetime

from aiogram import Bot

import daily
import db
import group
import parents
from config import TZ

log = logging.getLogger(__name__)


def _minutes(hm: str) -> int:
    try:
        h, m = map(int, hm.split(":"))
        return h * 60 + m
    except ValueError:
        return -1


def _due(now: datetime, hm: str, window: int = 120) -> bool:
    """Belgilangan vaqt kelganmi (kechikish oynasi ichida — bot qayta ishga tushsa ham o'tkazib yubormaydi)."""
    t = _minutes(hm)
    cur = now.hour * 60 + now.minute
    return t >= 0 and 0 <= cur - t <= window


async def tick(bot: Bot):
    now = datetime.now(TZ)
    today = now.date().isoformat()
    await group.sched_tick(bot)

    if await db.get_int("daily_on") and _due(now, await db.get_setting("daily_time")) \
            and await db.get_setting("last_daily") != today:
        await db.set_setting("last_daily", today)
        n = await daily.send_daily_all(bot)
        log.info("Kunlik vazifa yuborildi: %d o'quvchi", n)

    if await db.get_int("remind_on") and _due(now, await db.get_setting("remind_time")) \
            and await db.get_setting("last_remind") != today:
        await db.set_setting("last_remind", today)
        n = await daily.remind_all(bot)
        log.info("Eslatma yuborildi: %d o'quvchi", n)

    if await db.get_int("report_on") and now.weekday() == await db.get_int("report_day") \
            and _due(now, await db.get_setting("report_time"), window=300) \
            and await db.get_setting("last_report") != today:
        await db.set_setting("last_report", today)
        n = await parents.send_reports_all(bot)
        log.info("Haftalik hisobot yuborildi: %d ota-ona", n)


async def loop(bot: Bot):
    while True:
        try:
            await tick(bot)
        except Exception:  # noqa: BLE001 — rejalashtiruvchi hech qachon to'xtamasligi kerak
            log.exception("Cron xatosi")
        await asyncio.sleep(30)
