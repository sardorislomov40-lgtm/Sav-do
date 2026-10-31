import hashlib
import secrets
from datetime import datetime, timedelta, timezone

import pandas as pd
import streamlit as st
from sqlalchemy import create_engine, text

st.set_page_config(page_title="Sav-do ERP", page_icon="🛒", layout="wide")

# ---------------------------------------------------------------- BAZA
# Streamlit Secrets ichida DATABASE_URL bo'lsa Neon PostgreSQL, bo'lmasa SQLite (vaqtincha)
@st.cache_resource
def get_engine():
    try:
        url = st.secrets["DATABASE_URL"]
    except Exception:
        url = "sqlite:///savdo.db"
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return create_engine(url, pool_pre_ping=True)


ENGINE = get_engine()
PK = "SERIAL PRIMARY KEY" if ENGINE.dialect.name == "postgresql" else "INTEGER PRIMARY KEY AUTOINCREMENT"


@st.cache_resource
def init_db():
    with ENGINE.begin() as c:
        for sql in [
            f"CREATE TABLE IF NOT EXISTS users (id {PK}, username TEXT UNIQUE NOT NULL, full_name TEXT, pw TEXT NOT NULL, role TEXT NOT NULL, active INTEGER DEFAULT 1)",
            f"CREATE TABLE IF NOT EXISTS products (id {PK}, name TEXT NOT NULL, unit TEXT, price DOUBLE PRECISION, stock DOUBLE PRECISION DEFAULT 0)",
            f"CREATE TABLE IF NOT EXISTS sales (id {PK}, created TEXT, cashier TEXT, payment TEXT, customer TEXT, total DOUBLE PRECISION)",
            f"CREATE TABLE IF NOT EXISTS sale_items (id {PK}, sale_id INTEGER, product_id INTEGER, name TEXT, qty DOUBLE PRECISION, price DOUBLE PRECISION)",
        ]:
            c.execute(text(sql))


init_db()


def q(sql, **p):
    with ENGINE.connect() as c:
        return pd.read_sql(text(sql), c, params=p)


def ex(sql, **p):
    with ENGINE.begin() as c:
        c.execute(text(sql), p)


def now():
    return datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d %H:%M:%S")  # Toshkent


def show_df(d):
    try:
        st.dataframe(d, width="stretch", hide_index=True)
    except Exception:
        st.dataframe(d, use_container_width=True, hide_index=True)


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"


def check_pw(pw, stored):
    return secrets.compare_digest(hash_pw(pw, stored.split("$", 1)[0]), stored)


RN = {"id": "ID", "name": "Tovar", "unit": "Birlik", "price": "Narx", "stock": "Qoldiq"}
ROLES = {"admin": "Administrator", "kassir": "Kassir", "omborchi": "Omborchi"}
MENU = {
    "admin": ["🛒 Kassa", "📦 Tovarlar", "📥 Omborga kirim", "📊 Hisobotlar", "👥 Foydalanuvchilar"],
    "kassir": ["🛒 Kassa"],
    "omborchi": ["📦 Tovarlar", "📥 Omborga kirim"],
}
ss = st.session_state
ss.setdefault("user", None)
ss.setdefault("cart", [])
ss.setdefault("receipt", "")

# ---------------------------------------------------------------- KIRISH
st.title("🛒 Sav-do ERP")

if q("SELECT COUNT(*) FROM users").iloc[0, 0] == 0:
    st.subheader("Birinchi administratorni yarating")
    with st.form("first"):
        u = st.text_input("Login")
        n = st.text_input("Ism-familiya")
        p1 = st.text_input("Parol (kamida 6 belgi)", type="password")
        p2 = st.text_input("Parolni takrorlang", type="password")
        if st.form_submit_button("Yaratish", type="primary"):
            if not u.strip() or len(p1) < 6 or p1 != p2:
                st.error("Login kiriting, parol kamida 6 belgi va ikkalasi bir xil bo'lsin.")
            else:
                ex("INSERT INTO users (username, full_name, pw, role) VALUES (:u,:n,:p,'admin')",
                   u=u.strip().lower(), n=n.strip(), p=hash_pw(p1))
                st.success("Tayyor! Endi sahifani yangilab, kiring.")
    st.stop()

if not ss.user:
    st.subheader("🔐 Tizimga kirish")
    with st.form("login"):
        u = st.text_input("Login")
        p = st.text_input("Parol", type="password")
        if st.form_submit_button("Kirish", type="primary"):
            r = q("SELECT * FROM users WHERE username=:u AND active=1", u=u.strip().lower())
            if not r.empty and check_pw(p, r.iloc[0]["pw"]):
                row = r.iloc[0]
                ss.user = {"username": row["username"], "name": row["full_name"] or row["username"], "role": row["role"]}
                st.rerun()
            else:
                st.error("Login yoki parol noto'g'ri.")
    st.stop()

user = ss.user
st.sidebar.markdown(f"👤 **{user['name']}**  \n{ROLES[user['role']]}")
if st.sidebar.button("🚪 Chiqish"):
    ss.user = None
    ss.cart = []
    st.rerun()
menu = st.sidebar.radio("Bo'lim", MENU[user["role"]])

# ---------------------------------------------------------------- KASSA
if menu == "🛒 Kassa":
    prods = q("SELECT * FROM products ORDER BY name")
    c1, c2 = st.columns([2, 1])
    with c1:
        st.subheader("💳 Tezkor savdo")
        if prods.empty:
            st.info("Avval «Tovarlar» bo'limida tovar qo'shing.")
        else:
            s = st.text_input("🔍 Qidirish")
            view = prods[prods["name"].str.contains(s, case=False, na=False)] if s else prods
            show_df(view.rename(columns=RN))
            names = dict(zip(prods["id"], prods["name"]))
            if view.empty:
                st.warning("Tovar topilmadi.")
            else:
                pid = int(st.selectbox("Tovar:", view["id"].tolist(), format_func=lambda x: names[x]))
                qty = st.number_input("Miqdori:", min_value=0.01, value=1.0, step=0.5)
                if st.button("➕ Savatga qo'shish", type="primary"):
                    t = prods[prods["id"] == pid].iloc[0]
                    have = sum(i["qty"] for i in ss.cart if i["id"] == pid)
                    if have + qty > t["stock"]:
                        st.error(f"Omborda yetarli emas. Qoldiq: {t['stock']:g}, savatda: {have:g}")
                    else:
                        for i in ss.cart:
                            if i["id"] == pid:
                                i["qty"] += qty
                                break
                        else:
                            ss.cart.append({"id": pid, "name": t["name"], "price": float(t["price"]), "qty": qty})
                        st.rerun()
    with c2:
        st.subheader("🛍️ Savat")
        if ss.cart:
            cart = pd.DataFrame(ss.cart)
            cart["jami"] = cart["price"] * cart["qty"]
            show_df(cart[["name", "qty", "jami"]].rename(columns={"name": "Tovar", "qty": "Miqdor", "jami": "Jami"}))
            total = float(cart["jami"].sum())
            st.markdown(f"### Jami: **{total:,.0f} so'm**")
            pay = st.radio("To'lov turi:", ["Naqd", "Karta", "Nasiya"])
            cust = st.text_input("Mijoz ismi / telefoni") if pay == "Nasiya" else ""
            if st.button("✅ Yakunlash (chek)", type="primary"):
                if pay == "Nasiya" and not cust.strip():
                    st.error("Nasiya uchun mijozni kiriting.")
                else:
                    try:
                        with ENGINE.begin() as c:
                            sid = c.execute(text("INSERT INTO sales (created,cashier,payment,customer,total) VALUES (:t,:u,:p,:c,:s) RETURNING id"),
                                            {"t": now(), "u": user["username"], "p": pay, "c": cust.strip(), "s": total}).scalar()
                            for i in ss.cart:
                                r = c.execute(text("UPDATE products SET stock = stock - :q WHERE id=:i AND stock >= :q"), {"q": i["qty"], "i": i["id"]})
                                if r.rowcount == 0:
                                    raise ValueError(f"{i['name']}: omborda yetarli emas")
                                c.execute(text("INSERT INTO sale_items (sale_id,product_id,name,qty,price) VALUES (:s,:p,:n,:q,:pr)"),
                                          {"s": sid, "p": i["id"], "n": i["name"], "q": i["qty"], "pr": i["price"]})
                        lines = [f"SAV-DO   Chek №{sid}", now(), f"Kassir: {user['name']}", "-" * 30]
                        lines += [f"{i['name']}\n  {i['qty']:g} x {i['price']:,.0f} = {i['qty'] * i['price']:,.0f}" for i in ss.cart]
                        lines += ["-" * 30, f"JAMI: {total:,.0f} so'm", f"To'lov: {pay}" + (f" ({cust.strip()})" if cust.strip() else "")]
                        ss.receipt = "\n".join(lines)
                        ss.cart = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"Xato: {e}")
            if st.button("🗑️ Tozalash"):
                ss.cart = []
                st.rerun()
        else:
            st.info("Savat bo'sh.")
        if ss.receipt:
            st.markdown("**Oxirgi chek:**")
            st.code(ss.receipt)

# ---------------------------------------------------------------- TOVARLAR
elif menu == "📦 Tovarlar":
    st.subheader("📦 Tovarlar")
    top = st.container()
    with st.form("addp", clear_on_submit=True):
        st.markdown("**Yangi tovar**")
        n = st.text_input("Nomi")
        unit = st.selectbox("Birlik", ["dona", "kg", "quti", "metr", "litr"])
        price = st.number_input("Sotuv narxi (so'm)", min_value=0.0, value=1000.0, step=500.0)
        stock = st.number_input("Boshlang'ich qoldiq", min_value=0.0, value=0.0)
        if st.form_submit_button("Saqlash", type="primary") and n.strip():
            ex("INSERT INTO products (name,unit,price,stock) VALUES (:n,:u,:p,:s)", n=n.strip(), u=unit, p=price, s=stock)
            st.success("Qo'shildi!")
    prods = q("SELECT * FROM products ORDER BY name")
    if not prods.empty:
        with st.form("editp"):
            st.markdown("**Narxni o'zgartirish**")
            pid = st.selectbox("Tovar", prods["id"].tolist(), format_func=lambda x: prods.loc[prods["id"] == x, "name"].iloc[0])
            newp = st.number_input("Yangi narx", min_value=0.0, step=500.0)
            if st.form_submit_button("Yangilash"):
                ex("UPDATE products SET price=:p WHERE id=:i", p=newp, i=int(pid))
                st.success("Narx yangilandi.")
    with top:
        show_df(q("SELECT * FROM products ORDER BY name").rename(columns=RN))

# ---------------------------------------------------------------- KIRIM
elif menu == "📥 Omborga kirim":
    st.subheader("📥 Omborga kirim")
    top = st.container()
    prods = q("SELECT * FROM products ORDER BY name")
    if prods.empty:
        st.info("Avval tovar qo'shing.")
    else:
        with st.form("kirim", clear_on_submit=True):
            pid = st.selectbox("Tovar", prods["id"].tolist(), format_func=lambda x: prods.loc[prods["id"] == x, "name"].iloc[0])
            add = st.number_input("Kirim miqdori", min_value=0.01, value=10.0)
            if st.form_submit_button("Kirim qilish", type="primary"):
                ex("UPDATE products SET stock = stock + :q WHERE id=:i", q=add, i=int(pid))
                st.success("Qoldiq yangilandi.")
    with top:
        show_df(q("SELECT * FROM products ORDER BY name").rename(columns=RN))

# ---------------------------------------------------------------- HISOBOT
elif menu == "📊 Hisobotlar":
    st.subheader("📊 Hisobotlar")
    sales = q("SELECT * FROM sales ORDER BY id DESC")
    prods = q("SELECT * FROM products")
    today = sales[sales["created"].str[:10] == now()[:10]] if not sales.empty else sales
    a, b, c = st.columns(3)
    a.metric("Bugungi savdo", f"{today['total'].sum():,.0f} so'm")
    b.metric("Bugungi cheklar", len(today))
    c.metric("Ombor bahosi", f"{(prods['stock'] * prods['price']).sum():,.0f} so'm" if not prods.empty else "0")
    if not today.empty:
        st.markdown("**Bugun to'lov turi bo'yicha**")
        show_df(today.groupby("payment")["total"].sum().reset_index().rename(columns={"payment": "To'lov", "total": "Summa"}))
    nas = sales[sales["payment"] == "Nasiya"] if not sales.empty else sales
    if not nas.empty:
        st.markdown("**Nasiya (jami qarz, to'lovlar hisobga olinmagan)**")
        show_df(nas.groupby("customer")["total"].sum().reset_index().rename(columns={"customer": "Mijoz", "total": "Qarz"}))
    low = prods[prods["stock"] <= 5] if not prods.empty else prods
    if not low.empty:
        st.markdown("**⚠️ Qoldig'i kam tovarlar (≤ 5)**")
        show_df(low.rename(columns=RN))
    st.markdown("**Oxirgi 30 ta chek**")
    show_df(sales.head(30).rename(columns={"id": "№", "created": "Vaqt", "cashier": "Kassir", "payment": "To'lov", "customer": "Mijoz", "total": "Summa"}))

# ---------------------------------------------------------------- FOYDALANUVCHILAR
elif menu == "👥 Foydalanuvchilar":
    st.subheader("👥 Foydalanuvchilar")
    top = st.container()
    with st.form("nu", clear_on_submit=True):
        st.markdown("**Yangi foydalanuvchi**")
        u = st.text_input("Login")
        n = st.text_input("Ism-familiya")
        p = st.text_input("Parol (kamida 6 belgi)", type="password")
        r = st.selectbox("Rol", list(ROLES), format_func=lambda x: ROLES[x])
        if st.form_submit_button("Qo'shish", type="primary"):
            if not u.strip() or len(p) < 6:
                st.error("Login kiriting va parol kamida 6 belgi bo'lsin.")
            elif not q("SELECT 1 FROM users WHERE username=:u", u=u.strip().lower()).empty:
                st.error("Bunday login bor.")
            else:
                ex("INSERT INTO users (username,full_name,pw,role) VALUES (:u,:n,:p,:r)", u=u.strip().lower(), n=n.strip(), p=hash_pw(p), r=r)
                st.success("Qo'shildi!")
    users = q("SELECT username, full_name, role, active FROM users ORDER BY id")
    with st.form("eu"):
        st.markdown("**Parolni almashtirish / o'chirib qo'yish**")
        who = st.selectbox("Foydalanuvchi", users["username"].tolist())
        newp = st.text_input("Yangi parol (bo'sh qoldirsangiz o'zgarmaydi)", type="password")
        act = st.checkbox("Faol", value=True)
        if st.form_submit_button("Saqlash"):
            if who == user["username"] and not act:
                st.error("O'zingizni o'chirib qo'ya olmaysiz.")
            elif newp and len(newp) < 6:
                st.error("Parol kamida 6 belgi.")
            else:
                ex("UPDATE users SET active=:a WHERE username=:u", a=int(act), u=who)
                if newp:
                    ex("UPDATE users SET pw=:p WHERE username=:u", p=hash_pw(newp), u=who)
                st.success("Saqlandi.")
    with top:
        show_df(q("SELECT username AS login, full_name AS ism, role AS rol, active AS faol FROM users ORDER BY id"))
