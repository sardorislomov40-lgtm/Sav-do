# Sav-do ERP: do'konlar uchun savdo, ombor va nasiya tizimi

## Har bir yangi do'konga o'rnatish (5 qadam)
1. Bu papkani (app.py, requirements.txt, .streamlit/config.toml) yangi GitHub repoga joylang.
2. neon.tech da shu do'kon uchun **alohida** bepul PostgreSQL baza yarating.
3. share.streamlit.io da repodan ilova yarating (asosiy fayl: app.py).
4. Ilovaning Settings → Secrets bo'limiga yozing:
   DATABASE_URL = "postgresql://...neon ulanish manzili..."
5. Ilovani oching: birinchi administratorni yarating, keyin
   Sozlamalar → Do'kon ma'lumotlari (nomi, manzil, telefon, STIR, chek matni) va Bank va kassa → Kassalar (naqd kassa, karta, bank hisobi) ni to'ldiring.

Har bir do'kon o'z bazasi va o'z ilovasiga ega bo'ladi, ma'lumotlar aralashmaydi.

## Ishni boshlash tartibi
Tovarlar → Yetkazib beruvchilar → Omborga kirim → Kassa (POS).
