# Content Manager AI — Dehqon Dorixona (Railway)

**Bitta Telegram bot, ko‘p brend.** Hozir dastlabki faol brend `dehkon-dorixona`; `Dehqon Market` keyinchalik Telegram Super Admin menyusida `/newbrand dehkon-market Dehqon Market` orqali qo‘shiladi. Market uchun yangi deploy ham, yangi bot ham shart emas.

## Texnologiyalar

Python 3.12 + FastAPI, PostgreSQL, Redis/RQ, Railway S3 bucket, OpenAI Speech-to-text va vision, FFmpeg, Meta Instagram Login OAuth, Google YouTube OAuth, Telegram Business Bot API.

## Nimalar kodlangan

- Rasmiy Telegram webhook, secret header, faqat shaxsiy chatda ishlash.
- Super Admin: `/menu`, `/newbrand`, `/brands`, `/grant`, `/revoke`, `/accounts`, `/setdefaults`, `/connectig`, `/connectyoutube`, `/bindbiz`.
- Bir xodimga bir brend yoki bir nechta brend huquqini berish.
- Video kelganda yagona brend bo‘lsa avtomatik tanlanadi; ko‘p brend bo‘lsa tanlatiladi.
- RQ navbat, video normalizatsiya (1080×1920), AI nutq+3 kadr orqali matn, Story uchun ustma-ust hook.
- **Super Admin tasdig‘i:** hech bir video avtomatik joylanmaydi. AI tayyorlagan video, hook, caption, YouTube matni va qaysi akkauntlarga joylanishi Super Admin'ga yuboriladi: `✅ Joylash` / `✏️ Matnni o‘zgartirish` / `❌ Bekor`.
- **Uzun Story bo‘laklanadi:** 60 soniyadan uzun video Instagram Story va Telegram Business Story uchun teng, har biri ≤59 s qismlarga bo‘linadi va ketma-ket joylanadi (hook faqat 1-qismda). Bir qism xato bersa, keyingi qismlar joylanmaydi. Qismlar soni limiti `STORY_MAX_PARTS` (default 10).
- **Local Bot API server:** `telegram-bot-api/` servisi orqali 2 GB gacha video qabul qilinadi.
- **Alembic migratsiyalar:** `content-api` har ishga tushganda `alembic upgrade head` bajariladi.
- Instagram Business Login OAuth, YouTube OAuth, Telegram Business connection qabul qilish va brendga admin biriktirishi.
- Instagram Story, Reels, Trial Reels (API capability maxsus faollashtirilganda), YouTube Shorts, Telegram Business Story publisher funksiyalari.
- Shifrlangan OAuth ma'lumotlari, barcha brend/account/publish huquqlari serverda tekshiriladi, xatolar loglanadi.
- Qayta yuklashdan kelgan Telegram webhooklar va noaniq remote API javoblarda ikki marta joylashdan himoya.

## Mavjud cheklovlar (ishga tushirishdan oldin o‘qish shart)

1. Bu **ishga tushirish uchun tayyorlanayotgan dastlabki kod bazasi**, hali haqiqiy Railway loyihasiga deploy qilinmagan, Meta/Google/Telegram akkauntlariga token olinmagan, real nashr ishlayotgani sinovdan o‘tmagan.
2. Katta videolar (2 GB gacha) uchun `telegram-bot-api` servisi kerak (pastda). U yoqilmasa (`TELEGRAM_LOCAL_MODE=false`), 20 MB dan katta video rad qilinadi. `aiogram/telegram-bot-api` image va fayl-server Railway'da hali jonli sinalmagan.
3. Meta Trial Reels API akkauntga mosligi va joriy parametr ishlashi alohida live test talab etadi; xavfsizlik uchun `IG_ENABLE_TRIAL=false` default. Sinovsiz nashr qilmaydi.
4. Instagram Story caption alohida ko‘rinmasligi sababli videoga hook yoziladi. Google/Youtube OAuth unverified app cheklovlari bo‘lishi mumkin.
5. Instagram akkaunti professional (Business/Creator), Story imkoniyati mos bo‘lishi, Meta ilovasida publishing permissions bo‘lishi shart. Boshqa kompaniya akkauntlari uchun Meta App Review/Advanced Access talab qilinishi mumkin.
6. YouTube Shorts video 3 daqiqagacha (uzunrog‘i preview'da "o‘tkazib yuboriladi" deb ko‘rsatiladi). Story uchun video bo‘laklanadi; har bir Telegram Story qismi 30 MB dan oshmasligi kerak.
7. Schema Alembic bilan boshqariladi (`migrations/`). PostgreSQL zaxira nusxalarini Railway'da alohida yoqing.
8. Videoning o‘zi qayta ishlanishi uchun Railway Worker resurslarini mos tanlang; juda katta ko‘lamga chiqqanda parallelism va rate-limit monitoring kerak.
9. AI natijasi faktlarni to‘liq kafolatlamaydi: brend qoidalari va moderatsiya nazorati qo‘shilgan, ammo tibbiy kontentda xatoni qatʼiy istisno etmaydi.

## Railway: yangi loyiha yaratish tartibi

1. Railway’da **yangi alohida `content-manager-ai`** project oching. Oldingi `dehkondorixona` serverini bu loyiha bilan bog‘lamang.
2. Shu koddan **alohida GitHub repository** yarating va Railway’dagi uchta service’ga bir xil repository ulang:
   - `content-api`: `RUN_MODE=api`; Railway `PORT` avtomatik; public Railway HTTPS domain bering. Ishga tushganda migratsiyalarni o‘zi bajaradi.
   - `content-worker`: `RUN_MODE=worker`; public domain kerak emas. `rq worker -u REDIS_URL media` ishlaydi.
   - `telegram-bot-api`: **Root Directory = `telegram-bot-api`**. Public domain **bermang** (faqat private network). Volume: `/var/lib/telegram-bot-api` (eng katta video hajmidan kattaroq). Variables: `TELEGRAM_API_ID`, `TELEGRAM_API_HASH` (my.telegram.org → API development tools), `FILE_SERVER_SECRET` (uzun tasodifiy satr).
3. Railway’da `Postgres` va `Redis` servislarini qo‘shing.
4. Railway’da `media-storage` nomli S3 Bucket yarating. `content-api` va `content-worker` uchun environment variables’da S3 credentials’ni Railway reference variables bilan ulang.
5. Har ikki Python service’ga **shared env** qiling:
   - `DATABASE_URL=postgresql+psycopg://...` (`Postgres.DATABASE_URL` odatda `postgresql://` bo‘ladi; SQLAlchemy uchun `postgresql+psycopg://` prefixga almashtirish kerak; alohida `DATABASE_URL` da shuni sozlang).
   - `REDIS_URL=${{Redis.REDIS_URL}}`
   - `TELEGRAM_BOT_TOKEN`, `TELEGRAM_WEBHOOK_SECRET`, `SUPERADMIN_TELEGRAM_IDS`.
   - `PUBLIC_BASE_URL=https://...up.railway.app`, `FERNET_KEY`, `OPENAI_API_KEY`.
   - `S3_ENDPOINT_URL`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_BUCKET`, `S3_REGION`.
   - Instagram `IG_APP_ID`, `IG_APP_SECRET` va Google `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET`.
   - Local Bot API: `TELEGRAM_LOCAL_MODE=true`, `TELEGRAM_API_BASE=http://telegram-bot-api.railway.internal:8081`, `BOTAPI_FILE_SERVER_URL=http://telegram-bot-api.railway.internal:8090`, `BOTAPI_FILE_SECRET=${{telegram-bot-api.FILE_SERVER_SECRET}}`.
   - `SUPERADMIN_TELEGRAM_IDS` majburiy: videolarni shu odamlar tasdiqlaydi.
6. Meta Developers Instagram Login: redirect URL EXACT `https://DOMAIN/oauth/instagram/callback`.
7. Google Cloud OAuth client: redirect URL EXACT `https://DOMAIN/oauth/youtube/callback`; YouTube Data API v3 yoqilsin.
8. Webhookni bir marta sozlang (Railway `content-api` environment’ida, `telegram-bot-api` servisi ishga tushgach):
   `python -m content_manager.setup_webhook --logout-cloud`
   Bu botni `api.telegram.org` dan chiqaradi (`logOut`) va webhookni Local Bot API server orqali qo‘yadi. Shundan keyin bot 10 daqiqa davomida cloud serverga qaytolmaydi. Keyingi safar webhookni yangilash uchun `--logout-cloud` siz ishga tushiring.
9. Telegram `@BotFather` orqali biznes ulanish imkoniyatlarini yoqing va Business profile tarafidan `can_manage_stories` ruxsatini bering.
10. `/start` → `/connectig dehkon-dorixona` → login orqali ulash; `/connectyoutube dehkon-dorixona`; Telegram Business ulanganidan so‘ng `/bindbiz UUID dehkon-dorixona`.
11. `dehkon-dorixona` da 4 ta format default yoqilgan (Story, Reels, YouTube Shorts, Telegram Business Story). Har bir video joylanishidan oldin sizga preview keladi; o‘chirish/yoqish botdagi ⚙️ Formatlar menyusida.

**Railway’ga hech qachon `.env` faylni GitHub orqali qo‘shmang.** Secretlarni Railway Variables/Secrets orqali kiriting. `FERNET_KEY`ni alohida backup qiling.

## Super Admin xodimlarni boshqaradi

`/grant 123456789 dehkon-dorixona` — faqat dorixona.

`/newbrand dehkon-market Dehqon Market` — yangi brend ochadi. Birinchi so‘z slug (kichik lotin harflar, raqamlar va kamida bitta `-`), qolgani nom. Slug yozilmasa, nomdan yasaladi: `/newbrand Dehqon Market` → `dehqon-market`. Bot javobida haqiqiy ID ko‘rsatiladi.

`/grant 123456789 dehkon-market` — boshqa xodimga faqat market huquqini beradi.

`/setdefaults dehkon-market instagram_story,instagram_reels,youtube_shorts` — market formatlarini tanlaydi.

`/connectig dehkon-market` — market Instagramni OAuth orqali ulaydi.

Bir xodimga ikkala brendni bersangiz, video yuborilganda brend tanlash tugmalari paydo bo‘ladi. Hech qaysi xodim Super Admin tasdig‘isiz yangi akkaunt ulay olmaydi.

## Video tasdiqlash oqimi

1. Xodim video yuboradi → worker uni yuklab oladi, formatlaydi, AI matn yozadi, Story qismlarini tayyorlaydi (S3 ga). Hech narsa joylanmaydi.
2. Har bir Super Admin'ga: video preview + hook, caption, YouTube matni va reja (qaysi akkaunt, nechta qism, nima o‘tkazib yuboriladi va nega).
3. `✅ Joylash` → joylash boshlanadi, oxirida hisobot xodimga va Super Admin'larga keladi. Ikki marta bosish xavfsiz.
   `✏️ Matnni o‘zgartirish` → keyingi xabaringiz yangi caption bo‘ladi (Reels va Telegram Story uchun; hook videoga yozilgan, YouTube matni o‘zgarmaydi), keyin preview qayta keladi.
   `❌ Bekor` → hech qayerga joylanmaydi.

## Migratsiyalar (Alembic)

Model o‘zgarsa: `DATABASE_URL=... alembic revision --autogenerate -m "nima o‘zgardi"`, faylni tekshiring, commit qiling. Deployda `content-api` uni avtomatik qo‘llaydi. `tests/test_changes.py::test_migrations_match_models` migratsiya modellarga mosligini tekshiradi.

## Lokal test

```bash
python3 -m pip install -r requirements.txt
python3 -m pytest -q
# Railway variables sozlangach
python3 -m uvicorn content_manager.app:app --host 0.0.0.0 --port 8000
```
