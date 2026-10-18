"""Bot sozlamalari .env faylidan o'qiladi."""
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(BASE_DIR / ".env")

BOT_TOKEN = os.getenv("BOT_TOKEN", "").strip()
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",") if x}
DB_PATH = Path(os.getenv("DB_PATH", BASE_DIR / "data" / "bot.db"))
TZ = ZoneInfo(os.getenv("TIMEZONE", "Asia/Tashkent"))
SEED_DIR = BASE_DIR / "data" / "seed"

# Admin panelda tanlash mumkin bo'lgan qiymatlar
SECONDS_CHOICES = [15, 20, 30, 45, 60]
INTERVAL_CHOICES = [15, 30, 60, 120, 180, 360]  # daqiqa
PER_ATTEMPT_CHOICES = [10, 20, 30, 50, 0]  # 0 = hammasi

DEFAULT_SETTINGS = {
    "private_seconds": "30",     # shaxsiy testda bitta savol uchun vaqt
    "group_seconds": "30",       # guruhdagi savol uchun vaqt
    "group_enabled": "1",        # guruhga avtomatik test tashlash
    "group_interval": "60",      # necha daqiqada bir savol
    "group_start_hour": "8",     # savol yuborish boshlanadigan soat
    "group_end_hour": "21",      # savol yuborish tugaydigan soat
    "group_fun": "1",            # qiziqarli savollar aralashsinmi
    "group_fun_every": "4",      # har nechanchi savol qiziqarli bo'lsin
    "group_scope": "all",        # all yoki test id
    "require_read": "1",         # testdan oldin darsni o'qish majburiy
    "ranking_mode": "first",     # first = birinchi urinish, best = eng yaxshi urinish
    "allow_retake": "1",         # testni qayta ishlash mumkinmi
    # kunlik vazifa
    "daily_on": "1",             # har kuni shaxsiy vazifa yuborish
    "daily_time": "16:00",       # vazifa yuboriladigan vaqt
    "daily_count": "10",         # vazifadagi savollar soni
    "daily_group_min": "5",      # guruhda nechta savolga javob bersa — vazifa bajarilgan hisoblanadi
    "remind_on": "1",            # bajarmaganlarga eslatma
    "remind_time": "20:00",      # eslatma vaqti
    # ota-onalarga haftalik hisobot
    "report_on": "1",
    "report_day": "6",           # 0 = dushanba ... 6 = yakshanba
    "report_time": "19:00",
}
