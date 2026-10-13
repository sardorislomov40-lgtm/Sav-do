# Sav-do
Dokonlar uchun maxsus mukammal programma 
# Savdo ERP — loyiha qoidalari

Bu fayl Claude Code uchun: har safar loyiha ochilganda o'qiladi. Mazmuni o'zgarsa, yangilab boring.

## Maqsad
Savdo (do'kon) uchun to'liq hisob tizimi: tovar, ombor, sotuv, xarid, nasiya va qarz,
kassa, xodimlar, hisobotlar. Tizim ishonchli bo'lishi va pul hisobi aniq chiqishi eng muhim.

## Foydalanuvchi haqida
- Egasi dasturchi emas. Har bir o'zgarishni oddiy o'zbek tilida tushuntir (nima o'zgardi, nega).
- Ish tartibi: kichik qadamlar. Avval reja yoz, tasdiqlagandan keyin kodni yoz.
- Interfeys tili: o'zbek (lotin).

## Texnologiya (boshlang'ich qaror, 1-bosqichdan oldin tasdiqlansin)
- Python + Streamlit (tez boshlash uchun), baza: PostgreSQL (Neon). SQLite fayl ishlatilmasin:
  Streamlit Cloud serverida fayl o'chib ketadi.
- Maxfiy ma'lumot (baza paroli va h.k.) faqat Streamlit Secrets'da. Repoga yozilmasin.
- Foydalanuvchi soni oshsa yoki murakkablashsa, Django'ga o'tish ko'riladi. Shuning uchun
  baza logikasi (database.py) ekran kodidan (views/) ajratilgan bo'lsin.

## Rollar
- Admin: hamma narsa. Sotuvchi: faqat o'z ishi (sotuv, o'z mijozlari, o'z hisoboti).
- Omborchi (keyinroq): kirim-chiqim va qoldiq.
- Menyu rolga qarab chiqadi; ruxsatsiz bo'limni ko'rsatma.

## Bosqichlar (har bir bosqich alohida tugaydi va sinab ko'riladi)
1. Tovarlar va ombor: katalog, o'lchov birligi, tan narxi, sotuv narxi, qoldiq, minimal qoldiq ogohlantirishi.
2. Sotuv: savat, naqd / karta / nasiya, chek, qaytarish. Nasiya sotuvi mijoz qarziga yoziladi.
3. Mijozlar va nasiya: qarz, to'lov, 30 kundan oshgan nasiyalar (qizil ro'yxat).
4. Xarid: ta'minotchi, kirim hujjati, ta'minotchiga to'lov va qarz.
5. Kassa va xarajatlar: kunlik kirim-chiqim, kassa yopish.
6. Hisobotlar: foyda, eng ko'p sotilgan tovar, qoldiq, qarzdorlik. Excel va PDF yuklash.
7. Qo'shimcha: Telegram orqali zaxira va bildirishnoma, shtrix-kod, telefonda qulay ko'rinish.

## Qoidalar (avvalgi nasiya loyihasidan olingan saboqlar)
- Pul hisobi: summani butun so'mda yoki aniq (NUMERIC) turda saqla. Qoldiq har doim BARCHA yozuvlar
  bo'yicha hisoblansin, faqat bitta sotuvchining yozuvlaridan emas.
- Har bir o'zgarish (kiritish, tahrirlash, o'chirish) audit jurnaliga yozilsin: kim, qachon, nima.
- Login katta-kichik harfga va bo'sh joyga qaramasin. Parol kamida 6 belgi, xeshlangan saqlansin.
- Yangi parol almashtirishni faqat yangi yoki tiklangan hisob uchun bir marta so'ra.
- Rasm va fayllar ham doimiy joyda saqlansin (server qayta ishga tushganda yo'qolmasin).
- Har o'zgarishdan keyin ishga tushirib sinab ko'r, nima sinalganini va nima sinalmaganini ayt.
- Hech qachon parol, kalit yoki bazaga ulanish satrini chatga yoki repoga yozma.
- Mavjud ma'lumot bor bazani o'zgartirganda eski ma'lumot buzilmasin (migratsiya yoz).

## Hozirgi holat
(Bu qismni ish davomida yangilab boring: nima tayyor, nima kutilmoqda.)
