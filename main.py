"""Botni ishga tushirish: python main.py

Ikki rejim:
  • Kompyuterda (oddiy) — long polling.
  • Render kabi serverda — webhook. RENDER_EXTERNAL_URL (Render o'zi beradi) yoki WEBHOOK_URL bo'lsa yoqiladi.
    Bunda bot veb-server bo'lib ishlaydi: Telegram xabarlarni o'zi yuboradi, /health manzili esa
    «uyg'otgich» xizmati (cron-job.org) uchun.
"""
import asyncio
import hashlib
import logging
import os
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import BotCommand, BotCommandScopeAllGroupChats, BotCommandScopeAllPrivateChats

import admin
import cron
import daily
import db
import group
import parents
import student
from config import ADMIN_IDS, BOT_TOKEN
from seed import seed_if_empty, seed_kichik

ALLOWED = ["message", "callback_query", "poll_answer", "my_chat_member"]
WEBHOOK_BASE = (os.getenv("WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or "").rstrip("/")


async def run_webhook(bot: Bot, dp: Dispatcher):
    from aiohttp import web
    from aiogram.webhook.aiohttp_server import SimpleRequestHandler

    secret = hashlib.sha256(BOT_TOKEN.encode()).hexdigest()[:32]
    path = f"/tg/{secret[:16]}"

    async def health(_):
        return web.Response(text="ok")

    app = web.Application()
    app.router.add_get("/", health)
    app.router.add_get("/health", health)
    SimpleRequestHandler(dispatcher=dp, bot=bot, secret_token=secret, handle_in_background=True).register(app, path=path)
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    await bot.set_webhook(WEBHOOK_BASE + path, secret_token=secret, allowed_updates=ALLOWED)
    logging.info("Webhook rejimi: %s (port %s)", WEBHOOK_BASE, port)
    try:
        await asyncio.Event().wait()
    finally:
        await runner.cleanup()


async def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        stream=sys.stdout)
    if not BOT_TOKEN or not ADMIN_IDS:
        print("❗ BOT_TOKEN va ADMIN_IDS ni to'ldiring (.env faylida yoki server sozlamalarida). README.md ga qarang.")
        sys.exit(1)

    await db.connect()
    await seed_if_empty()
    await db.migrate()
    await seed_kichik()
    # oldingi ishga tushirishdan qolib ketgan tugallanmagan testlar
    await db.execute("UPDATE attempts SET status='abandoned' WHERE status='active'")

    bot = Bot(BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher(storage=MemoryStorage())
    # Tartib muhim: admin → ro'yxatdan o'tish → o'quvchi → guruh → ruxsatsizlar uchun ushlagich
    dp.include_routers(admin.router, parents.router, student.router, student.app, daily.router,
                       parents.child_router, group.router, student.fallback)

    await bot.set_my_commands([BotCommand(command="start", description="Bosh menyu"),
                               BotCommand(command="help", description="Yordam"),
                               BotCommand(command="stop", description="Testni to'xtatish")],
                              scope=BotCommandScopeAllPrivateChats())
    await bot.set_my_commands([BotCommand(command="reyting", description="Guruh reytingi"),
                               BotCommand(command="test", description="Test yuborish (admin)"),
                               BotCommand(command="stoptest", description="Testni to'xtatish (admin)")],
                              scope=BotCommandScopeAllGroupChats())

    sched = asyncio.create_task(group.scheduler(bot))
    cron_task = asyncio.create_task(cron.loop(bot))
    try:
        if WEBHOOK_BASE:
            await run_webhook(bot, dp)
        else:
            await bot.delete_webhook()  # serverdagi webhook bo'lsa — o'chiriladi, kompyuterda polling ishlaydi
            await dp.start_polling(bot, allowed_updates=ALLOWED)
    finally:
        sched.cancel()
        cron_task.cancel()
        await db.close()
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(main())
