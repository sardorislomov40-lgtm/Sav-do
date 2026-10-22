# Sav-do: do'kon boshqaruvi (1-bosqich)

Django + PostgreSQL (Neon) + Tailwind/HTMX. Bu bosqichda: tovarlar, o'lchov birliklari (dona/kg/quti...),
chakana va ulgurji narxlar, shtrix-kod (zavod kodi + ichki EAN-13 «27…»), etiketka PDF, ombor (kirim,
qoldiq, harakatlar jurnali, inventarizatsiya), rollar (Admin, Sotuvchi/Kassir, Omborchi).
Kassa, nasiya va chek chop etish keyingi bosqichlarda.

## Ishga tushirish

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env                                    # DATABASE_URL ga Neon manzilini yozing (yoki bo'sh qoldiring: SQLite)
python manage.py makemigrations accounts catalog inventory   # migratsiya fayllari repoga qo'shiladi (git add)
python manage.py migrate
python manage.py seed_defaults                          # birliklar + «Asosiy ombor»
python manage.py createsuperuser
python manage.py runserver
```

`/admin/` orqali foydalanuvchilar yaratiladi va **Rol** tanlanadi. Superuser Admin hisoblanadi.
Testlar: `python manage.py test`

## Rollar

| Bo'lim | Admin | Omborchi | Sotuvchi/Kassir |
|---|---|---|---|
| Tovarlar, qoldiq ko'rish, etiketka | ha | ha | ha |
| Tovar qo'shish/tahrirlash, kategoriya | ha | ha | yo'q |
| Narxlarni o'zgartirish | ha | yo'q* | yo'q |
| Kirim, inventarizatsiya, harakatlar jurnali | ha | ha | yo'q |

\* `.env` da `STOREKEEPER_CAN_EDIT_PRICES=1` qilinsa, omborchi ham narxni o'zgartira oladi.

## Muhim qoidalar

- Qoldiq alohida maydon emas: `StockMovement` yozuvlari yig'indisi. Yozuvlar o'zgartirilmaydi va o'chirilmaydi,
  xato inventarizatsiya (tuzatish) bilan to'g'rilanadi.
- Asosiy birlik tovar yaratilgach o'zgartirilmaydi. Quti/qop koeffitsiyenti asosiy birlikda beriladi (1 quti = 12 dona).
- Ichki kod: `27` + 10 xonali tartib raqami + nazorat raqami (EAN-13). Zavod kodlarida nazorat raqami tekshiriladi.
- Etiketka: lenta 58×40, 40×30 mm yoki A4 varaq 3×8. Kirill harflar uchun `static/fonts/DejaVuSans*.ttf` ishlatiladi.

## Ishlab chiqarish uchun eslatmalar

- `base.html` da Tailwind CDN (Play) ishlatilgan: tez boshlash uchun qulay, lekin ishlab chiqarishda Tailwind CLI bilan
  `static/css/app.css` ga build qilib, CDN skriptini olib tashlang.
- Neon: ulanishda `sslmode=require`, regionni do'konga yaqinroq tanlang; bepul tarifda bo'sh turganda baza uxlab qoladi
  va birinchi so'rov sekin bo'lishi mumkin.
- `DEBUG=0`, uzun `SECRET_KEY`, `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS` ni to'ldiring; `python manage.py collectstatic`.
