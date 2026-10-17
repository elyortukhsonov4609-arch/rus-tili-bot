# Rus tili test boti — o'rnatish yo'riqnomasi

## Bot nima qiladi

**O'quvchi uchun:**
- 📚 **Darslar**: 1–7-darslarning nazariyasi va lug'ati sahifalarga bo'lingan. Darsga Word yoki PDF fayl ham biriktirish mumkin.
- 📝 **Testlar**: darsni o'qimaguncha uning testi qulf turadi (🔒). Har bir savolga vaqt beriladi.
- 🏁 **Natija**: to'g'ri javoblar soni, sarflangan vaqt, *nechanchi o'rinda* ekani va *necha foiz ishtirokchidan yaxshi* ishlagani ko'rsatiladi. «Xatolarni ko'rish» tugmasi ham bor.
- 🏆 **Reyting**: har bir test bo'yicha eng yaxshi 10 talik. Ballar teng bo'lsa, tezroq ishlagan yuqorida turadi.

**Siz (admin) uchun** (`⚙️ Admin panel` tugmasi):
- 🆕 **Arizalar**: botga faqat siz ruxsat bergan bolalar kiradi. Har bir yangi ariza sizga ✅/❌ tugmalari bilan keladi.
- ⏱ **Vaqt**: bitta savolga 15 / 20 / 30 / 45 / 60 soniya. Shaxsiy test va guruh uchun alohida sozlanadi.
- 📊 **Natijalar**: har bir test bo'yicha to'liq ro'yxat. Hammasini 📥 Excel faylda yuklab olish mumkin.
- 📚 **Darslar**: darsni ochish yoki yopish, yangi dars qo'shish, Word/PDF fayl yoki matn yuklash.
- 📝 **Testlar**: Word fayldan yangi test yuklash, testni Word'da yuklab olib tahrirlash va qayta yuklash, bitta urinishdagi savollar sonini belgilash (masalan, 140 ta savoldan 30 tasi tasodifiy).
- 👥 **Guruh**: avtomatik test oralig'i (15 daqiqadan 6 soatgacha), qaysi soatlarda yuborish, qiziqarli savollar, guruh reytingi.
- ⚙️ **Boshqa**: darsni o'qish majburiyligi, qayta ishlashga ruxsat, reytingda qaysi urinish hisoblanishi, zaxira nusxa.

---

## 1-qadam. Botni yaratish (2 daqiqa)

1. Telegramda **@BotFather** ni oching va `/newbot` yozing.
2. Bot nomini yozing (masalan: *Rus tili testlari*).
3. Keyin username yozing. U `bot` bilan tugashi shart (masalan: *rustili_test_bot*).
4. BotFather **token** beradi (`1234567890:AAH...` ko'rinishida). Uni hech kimga bermang.
5. Botni guruhga qo'shish mumkin bo'lishi uchun BotFather'da `/setjoingroups` → botingizni tanlang → **Enable** ni bosing.

## 2-qadam. Telegram ID raqamingizni bilish

Telegramda **@userinfobot** ga `/start` yozing. U `Id: 123456789` ko'rinishidagi raqamni ko'rsatadi. Shu raqam sizni admin qiladi.

## 3-qadam. Avval o'z kompyuteringizda sinab ko'rish (ixtiyoriy)

1. https://www.python.org/downloads/ saytidan Python'ni o'rnating. O'rnatishda **«Add python.exe to PATH»** belgisini qo'ying.
2. Bot papkasidagi `.env.example` faylidan nusxa oling, nomini `.env` qiling va Bloknotda oching. `BOT_TOKEN` va `ADMIN_IDS` ni to'ldiring.
3. `run_windows.bat` faylini ikki marta bosing. Oyna ochiq turgan paytda bot ishlaydi.

> Kompyuter o'chsa, bot ham to'xtaydi. 24/7 ishlashi uchun 4-qadamni bajaring.

## 4-qadam. Bepul serverga qo'yish: GitHub + Render + Neon (karta kerak emas)

Bot to'rtta bepul xizmat yordamida 24/7 ishlaydi:
- **GitHub** — bot kodi saqlanadi;
- **Render.com** — bot shu yerda ishlaydi;
- **Neon.tech** — o'quvchilar va natijalar shu bazada saqlanadi. Render'ning bepul serveri qayta yoqilganda fayllarni o'chiradi, shuning uchun ma'lumotlar alohida bazada turadi;
- **cron-job.org** — har 10 daqiqada botni «uyg'otib» turadi. Aks holda Render 15 daqiqa ishlatilmagan botni uxlatib qo'yadi.

> ⚠️ Bot Render'da ishga tushishidan **oldin** kompyuterdagi qora oynani yoping. Bitta bot bir vaqtda ikki joyda ishlay olmaydi.

### A. GitHub — kodni joylash
1. **github.com** saytida ro'yxatdan o'ting (Sign up).
2. Yuqori o'ngdagi **+** → **New repository** ni bosing:
   - Repository name: `rus-tili-bot`;
   - **Private** ni tanlang;
   - **Create repository** ni bosing.
3. Ochilgan sahifada **«uploading an existing file»** havolasini bosing.
4. Arxivdan chiqarilgan **toza** `rus_tili_bot` papkasini oching. Ichidagi **hamma narsani** (`data` papkasi bilan birga) belgilab, brauzer oynasiga sudrab tashlang.
   ⚠️ `.env`, `venv` va `data\bot.db` **yuklanmasin**: ularda tokeningiz va kompyuterdagi baza bor. Toza arxivda ular yo'q.
5. Pastdagi **Commit changes** tugmasini bosing.

### B. Neon — ma'lumotlar bazasi
1. **neon.com** saytida Google yoki GitHub akkaunti bilan ro'yxatdan o'ting.
2. **Create project** ni bosing: nomi `rustili`, region **AWS Europe Central (Frankfurt)**.
3. Loyiha ochilgach, **Connect** tugmasini bosing va **connection string**'ni nusxalab oling. U `postgresql://...neon.tech/neondb?sslmode=require` ko'rinishida bo'ladi.

### C. Render — botni ishga tushirish
1. **render.com** saytida **Get Started** → **GitHub** orqali kiring.
2. **New +** → **Web Service** → ro'yxatdan `rus-tili-bot` ni tanlang. Ro'yxatda yo'q bo'lsa, «Configure GitHub» orqali ruxsat bering.
3. Sozlamalar:
   - Name: `rustili-bot`;
   - Region: **Frankfurt**;
   - Runtime: **Python 3**;
   - Build Command: `pip install -r requirements.txt`;
   - Start Command: `python main.py`;
   - Instance Type: **Free**.
4. **Environment Variables** bo'limiga uchta qator qo'shing:
   | Key | Value |
   |---|---|
   | `BOT_TOKEN` | BotFather bergan token |
   | `ADMIN_IDS` | `641728328` |
   | `DATABASE_URL` | Neon'dan nusxalangan manzil |
5. **Deploy Web Service** ni bosing. 2–4 daqiqadan keyin jurnalda (Logs) `Webhook rejimi` qatori chiqadi. Sahifaning tepasida botning manzili ko'rinadi, masalan `https://rustili-bot.onrender.com`.

### D. cron-job.org — botni uyg'oq ushlash
1. **cron-job.org** saytida ro'yxatdan o'ting va emailingizni tasdiqlang.
2. **Create cronjob** ni bosing:
   - URL: `https://rustili-bot.onrender.com/health` (o'z manzilingizni yozing);
   - Execution schedule: **Every 10 minutes**;
   - **Create** ni bosing.

### Tayyor!
Botga `/start` yozing. Admin panel chiqsa, hammasi ishlayapti. Darslar va testlar yangi bazaga birinchi ishga tushishda avtomatik yuklanadi. O'quvchilar botga qaytadan `/start` bosib ro'yxatdan o'tishadi.

**Keyinchalik kodni yangilash:** GitHub'da `rus-tili-bot` → **Add file → Upload files** → yangi fayllarni tashlang → **Commit**. Render botni o'zi yangilaydi (2–3 daqiqa).

**Zaxira:** `Admin panel → ⚙️ Boshqa → 💾 Zaxira nusxa` butun bazani JSON fayl qilib beradi. Haftada bir marta olib qo'ying.

> Bepul xizmatlarning shartlari vaqti-vaqti bilan o'zgarishi mumkin. Biror xizmat pullik bo'lib qolsa, bot o'zgarishsiz istalgan VPS'ga ham ko'chadi (`install.sh`).

### Muqobil: o'z VPS serveringiz (Ubuntu)
Bot papkasini serverga yuboring va `bash install.sh` buyrug'ini ishga tushiring. Skript token va ID raqamingizni so'raydi, qolganini o'zi bajaradi.

## Botni guruhga ulash

1. Botni guruhga qo'shing va **admin** qiling. Uni **siz** qo'shsangiz, guruh avtomatik faollashadi.
2. **Avtomatik rejim.** Bot siz belgilagan oraliqda (standart: har soatda, 8:00–21:00) savol tashlaydi. Savolni o'zi **tahlil qilib** tanlaydi: kam o'quvchi ishlagan testlar, ko'p xato qilinayotgan savollar va guruhga hali yuborilmagan savollar ko'proq chiqadi. Yaqinda berilgan savol takrorlanmaydi. Har 4-savol qiziqarli savol bo'ladi.
3. **Qo'lda yuborish (istalgan payt).**
   - Guruhda `/test` yozing → testni tanlang → savollar sonini tanlang. Bot savollarni birin-ketin tashlaydi, oxirida g'oliblarni e'lon qiladi. Tugmalarni faqat siz bosa olasiz.
   - Yoki `Admin panel → 👥 Guruh sozlamalari → 📝 Guruhga test yuborish` orqali yuboring.
   - `/stoptest` — ketayotgan testni to'xtatadi.
   - `/savol` — bitta savol yuboradi.
   - `/reyting` — guruh reytingini ko'rsatadi.
   Qo'lda yuborilgan test paytida avtomatik savollar to'xtab turadi.
4. Bot savollarni siz `/test` yoki `/savol` yozgan mavzuga (topic) yuboradi.
5. **Tahlil:** `Admin panel → 📊 Natijalar → 📈 Tahlil`. Bu yerda qaysi testni kam o'quvchi ishlagani (🔴🟡🟢), o'rtacha natija va eng ko'p xato qilinayotgan savollar ko'rinadi.

## Word'dan test yuklash

`Admin panel → 📝 Testlar → ➕ Word'dan yangi test yuklash` bo'limiga o'tib, .docx fayl yuboring. Format:

```
1. Savol matni?
A) variant
B) to'g'ri variant      ← qalin (bold) qilib belgilang
C) variant
D) variant
Izoh: ixtiyoriy tushuntirish
```

To'g'ri javobni belgilashning uch usuli bor: **qalin (bold)** qilish, tagiga chizish yoki fayl oxiriga kalit yozish (`1 — B, 2 — A, ...`). Variantlar 2 tadan 10 tagacha bo'lishi mumkin. Telegram cheklovi: savol 290 belgigacha, variant 100 belgigacha.

Mavjud testni tahrirlash: `📄 Word'da yuklab olish` → Word'da o'zgartiring → `♻️ Word bilan almashtirish`.

## Fayllar tuzilishi

| Fayl | Vazifasi |
|---|---|
| `main.py` | ishga tushirish |
| `student.py` | o'quvchi bo'limi: ro'yxatdan o'tish, darslar, testlar, reyting |
| `quiz.py` | vaqtli test, natija, o'rin va foiz hisoblash |
| `admin.py` | admin panel |
| `group.py` | guruhga avtomatik savollar va guruh reytingi |
| `docx_tools.py` | Word'dan test va darslik o'qish, Word'ga chiqarish |
| `data/seed/` | boshlang'ich darsliklar va testlar (birinchi ishga tushishda bazaga yuklanadi) |
| `data/bot.db` | kompyuterdagi ma'lumotlar bazasi (serverda esa Neon ishlatiladi) |
