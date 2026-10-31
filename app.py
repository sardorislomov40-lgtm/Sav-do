import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone

import html

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from sqlalchemy import bindparam, create_engine, text

st.set_page_config(page_title="Sav-do ERP", page_icon="🛒", layout="wide")


# ================================================================ BAZA
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
D = "DOUBLE PRECISION"


@st.cache_resource
def init_db():
    tables = [
        f"users (id {PK}, username TEXT UNIQUE NOT NULL, full_name TEXT, pw TEXT NOT NULL, role TEXT NOT NULL, active INTEGER DEFAULT 1)",
        f"products (id {PK}, name TEXT NOT NULL, unit TEXT, price {D}, stock {D} DEFAULT 0, barcode TEXT, marked INTEGER DEFAULT 0, cost {D} DEFAULT 0, active INTEGER DEFAULT 1)",
        f"sales (id {PK}, created TEXT, cashier TEXT, payment TEXT, customer TEXT, total {D}, partner_id INTEGER, paid {D}, debt {D}, given {D}, change_amt {D}, account_id INTEGER)",
        f"sale_items (id {PK}, sale_id INTEGER, product_id INTEGER, name TEXT, qty {D}, price {D}, codes TEXT)",
        f"partners (id {PK}, name TEXT NOT NULL, phone TEXT, kind TEXT NOT NULL)",
        f"accounts (id {PK}, name TEXT NOT NULL, kind TEXT NOT NULL, number TEXT, opening {D} DEFAULT 0, active INTEGER DEFAULT 1)",
        f"cash_moves (id {PK}, created TEXT, account_id INTEGER, amount {D}, partner_id INTEGER, doc TEXT, note TEXT, user_name TEXT)",
        f"ledger (id {PK}, created TEXT, partner_id INTEGER, amount {D}, doc TEXT, note TEXT, user_name TEXT)",
        f"receipts (id {PK}, created TEXT, user_name TEXT, partner_id INTEGER, total {D}, paid {D}, note TEXT)",
        f"receipt_items (id {PK}, receipt_id INTEGER, product_id INTEGER, name TEXT, qty {D}, cost {D})",
        f"mark_codes (id {PK}, product_id INTEGER, code TEXT UNIQUE NOT NULL, status TEXT, receipt_id INTEGER, sale_id INTEGER)",
        f"audit (id {PK}, created TEXT, user_name TEXT, action TEXT, details TEXT)",
    ]
    with ENGINE.begin() as c:
        for t in tables:
            c.execute(text("CREATE TABLE IF NOT EXISTS " + t))
    # eski bazalar uchun yangi ustunlar
    for t, col in [("products", "barcode TEXT"), ("products", "marked INTEGER DEFAULT 0"), ("products", f"cost {D} DEFAULT 0"),
                   ("products", "active INTEGER DEFAULT 1"), ("sales", "partner_id INTEGER"), ("sales", f"paid {D}"), ("sales", f"debt {D}"), ("sales", f"given {D}"), ("sales", f"change_amt {D}"), ("sales", "account_id INTEGER"), ("sale_items", "codes TEXT")]:
        try:
            with ENGINE.begin() as c:
                c.execute(text(f"ALTER TABLE {t} ADD COLUMN {col}"))
        except Exception:
            pass


init_db()


def q(sql, **p):
    with ENGINE.connect() as c:
        return pd.read_sql(text(sql), c, params=p)


def ex(sql, **p):
    with ENGINE.begin() as c:
        c.execute(text(sql), p)


def now():
    return datetime.now(timezone(timedelta(hours=5))).strftime("%Y-%m-%d %H:%M:%S")  # Toshkent


def m(x):
    return f"{x:,.0f} so'm"


def show_df(d, rename=None):
    d = d.rename(columns=rename) if rename else d
    try:
        st.dataframe(d, width="stretch", hide_index=True)
    except Exception:
        st.dataframe(d, use_container_width=True, hide_index=True)


def hash_pw(pw, salt=None):
    salt = salt or secrets.token_hex(8)
    return f"{salt}${hashlib.pbkdf2_hmac('sha256', pw.encode(), salt.encode(), 200_000).hex()}"


def check_pw(pw, stored):
    return secrets.compare_digest(hash_pw(pw, stored.split("$", 1)[0]), stored)


def log(action, details=""):
    u = (st.session_state.get("user") or {}).get("username", "-")
    ex("INSERT INTO audit (created,user_name,action,details) VALUES (:t,:u,:a,:d)", t=now(), u=u, a=action, d=details)


def acc_balances():
    return q("""SELECT a.id, a.name, a.kind, a.number,
        a.opening + COALESCE((SELECT SUM(amount) FROM cash_moves k WHERE k.account_id=a.id),0) AS balance
        FROM accounts a WHERE a.active=1 ORDER BY a.id""")


def partner_balances(kind=None):
    sql = """SELECT p.id, p.name, p.phone, p.kind,
        COALESCE((SELECT SUM(amount) FROM ledger l WHERE l.partner_id=p.id),0) AS balance FROM partners p"""
    if kind:
        return q(sql + " WHERE p.kind=:k ORDER BY p.name", k=kind)
    return q(sql + " ORDER BY p.name")


def pick(label, df, idcol, namecol, key=None, none=None):
    ids = ([None] if none else []) + df[idcol].tolist()
    names = dict(zip(df[idcol], df[namecol]))
    return st.selectbox(label, ids, format_func=lambda x: none if x is None else names[x], key=key)


def existing_codes(codes):
    out = set()
    with ENGINE.connect() as c:
        for i in range(0, len(codes), 500):
            r = c.execute(text("SELECT code FROM mark_codes WHERE code IN :c").bindparams(bindparam("c", expanding=True)), {"c": codes[i:i + 500]})
            out |= {x[0] for x in r}
    return out


def clean_code(s):
    return "".join(ch for ch in s if ch.isprintable()).strip()


# ================================================================ MENYU
RN_P = {"id": "ID", "name": "Tovar", "unit": "Birlik", "price": "Sotuv narxi", "stock": "Qoldiq", "barcode": "Shtrix-kod", "cost": "Tan narxi"}
ROLES = {"admin": "Administrator", "kassir": "Kassir", "omborchi": "Omborchi"}
NAV = [  # (belgi, bo'lim, [(ichki bo'lim, sahifa kaliti)])
    ("🏠", "Asosiy", [("Boshqaruv paneli", "panel")]),
    ("🏦", "Bank va kassa", [("Hisoblar", "hisob"), ("To'lovlar", "tolov"), ("Harakatlar", "harakat"), ("Kassa tahlili", "kassa")]),
    ("🛍️", "Sotuvlar", [("Kassa (POS)", "pos"), ("Sotuvlar ro'yxati", "sotuvlar"), ("Mijozlar", "mijoz")]),
    ("🛒", "Xaridlar", [("Omborga kirim", "kirim"), ("Kirim hujjatlari", "kirimlar"), ("Yetkazib beruvchilar", "taminot")]),
    ("📦", "Ombor", [("Qoldiqlar", "qoldiq"), ("Tovarlar", "tovar"), ("Markirovka kodlari", "kodlar")]),
    ("📊", "Hisobotlar", [("Savdo hisoboti", "hisobot"), ("Qarzdorlik", "qarz"), ("Akt sverka", "akt")]),
    ("⚙️", "Sozlamalar", [("Kassirlar", "kassirlar"), ("Audit jurnali", "audit")]),
]
ALLOWED = {"kassir": {"pos"}, "omborchi": {"tovar", "qoldiq", "kirim", "kirimlar", "kodlar"}}

ss = st.session_state
for k, v in {"user": None, "cart": [], "receipt": "", "msg": None, "rc": []}.items():
    ss.setdefault(k, v)

# ================================================================ KIRISH
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
                ex("INSERT INTO users (username, full_name, pw, role) VALUES (:u,:n,:p,'admin')", u=u.strip().lower(), n=n.strip(), p=hash_pw(p1))
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
                log("Tizimga kirdi")
                st.rerun()
            else:
                st.error("Login yoki parol noto'g'ri.")
    st.stop()

user = ss.user
st.markdown("""<style>
[data-testid="stSidebar"]{background:#FFF4B8}
[data-testid="stSidebar"] button{justify-content:flex-start;text-align:left;border:none;box-shadow:none}
[data-testid="stSidebar"] button[kind="secondary"],[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]{background:transparent;color:#222}
[data-testid="stSidebar"] button[kind="secondary"]:hover,[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover{background:#FFE98A}
[data-testid="stSidebar"] button[kind="primary"],[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]{background:#FFD84D;color:#111;font-weight:600}
</style>""", unsafe_allow_html=True)
st.sidebar.markdown(f"👤 **{user['name']}**  \n{ROLES[user['role']]}")
if st.sidebar.button("🚪 Chiqish"):
    log("Tizimdan chiqdi")
    ss.user = None
    ss.cart = []
    st.rerun()


def ok(k):
    return user["role"] == "admin" or k in ALLOWED.get(user["role"], set())


sections = []
for icon, name, subs in NAV:
    subs = [x for x in subs if ok(x[1])]
    if subs:
        sections.append((f"{icon}  {name}", subs))
sec_map = dict(sections)
def go(sec_, sub_):
    ss.nav_sec, ss.nav_sub = sec_, sub_


def nbtn(label, key, active, sec_, sub_):
    kw = dict(key=key, type="primary" if active else "secondary", on_click=go, args=(sec_, sub_))
    try:
        st.sidebar.button(label, width="stretch", **kw)
    except Exception:
        st.sidebar.button(label, use_container_width=True, **kw)


if ss.get("nav_sec") not in sec_map:
    ss.nav_sec = list(sec_map)[0]
if ss.get("nav_sub") not in [x[1] for x in sec_map[ss.nav_sec]]:
    ss.nav_sub = sec_map[ss.nav_sec][0][1]
for label, subs_ in sections:
    is_act = label == ss.nav_sec
    nbtn(label, f"sec_{label}", is_act, label, subs_[0][1])
    if is_act and len(subs_) > 1:  # tanlangan bo'lim tagida ichki bo'limlar ochiladi
        for nm, k_ in subs_:
            nbtn("\u00a0\u00a0\u00a0\u00a0↳ " + nm, f"sub_{k_}", k_ == ss.nav_sub, label, k_)
menu = ss.nav_sub
pk = next(n for n, k_ in sec_map[ss.nav_sec] if k_ == menu)
st.subheader(pk)


# ================================================================ SAHIFALAR
SALES_SQL = """SELECT *, COALESCE(paid, CASE WHEN payment='Nasiya' THEN 0 ELSE total END) AS paid_,
    COALESCE(debt, CASE WHEN payment='Nasiya' THEN total ELSE 0 END) AS debt_ FROM sales"""


def build_receipt(sid):
    s_ = q("""SELECT s.*, a.name AS acc_name, a.number AS acc_number FROM sales s
              LEFT JOIN accounts a ON a.id=s.account_id WHERE s.id=:i""", i=int(sid)).iloc[0]
    items = q("SELECT name,qty,price FROM sale_items WHERE sale_id=:i", i=int(sid))
    W = 32
    paid = s_["paid"] if pd.notna(s_["paid"]) else (0 if s_["payment"] == "Nasiya" else s_["total"])
    debt = s_["debt"] if pd.notna(s_["debt"]) else (s_["total"] if s_["payment"] == "Nasiya" else 0)
    L = ["SAV-DO".center(W), f"Chek №{sid}".center(W), str(s_["created"]), f"Kassir: {s_['cashier']}", "-" * W]
    for _, r in items.iterrows():
        L += [r["name"], f"{r['qty']:g} x {r['price']:,.0f} = {r['qty'] * r['price']:,.0f}".rjust(W)]
    L += ["-" * W, f"JAMI: {s_['total']:,.0f} so'm"]
    if paid > 0:
        if s_["payment"] == "Karta":
            num = (s_["acc_number"] or "")[-4:]
            L.append(f"Karta: {s_['acc_name'] or ''} {'**** ' + num if num else ''}".strip())
        else:
            L.append(f"Naqd: {s_['acc_name'] or 'kassa'}")
        L.append(f"To'langan: {paid:,.0f} so'm")
        if s_["payment"] == "Naqd" and pd.notna(s_["given"]) and s_["given"] > 0:
            L += [f"Berildi: {s_['given']:,.0f} so'm", f"Qaytim: {(s_['change_amt'] or 0):,.0f} so'm"]
    if debt > 0:
        L += [f"NASIYA (qarz): {debt:,.0f} so'm", f"Mijoz: {s_['customer'] or ''}"]
    L += ["-" * W, "Xaridingiz uchun rahmat!".center(W)]
    return "\n".join(L)


def show_receipt(txt):
    h = (f'<pre style="font-family:monospace;font-size:13px;background:#fff;border:1px dashed #999;padding:8px;width:290px;margin:0 0 8px">{html.escape(txt)}</pre>'
         '<button onclick="window.print()" style="padding:6px 14px;cursor:pointer">🖨️ Chop etish</button>')
    components.html(h, height=70 + 19 * (txt.count("\n") + 1))
    st.download_button("⬇️ Chekni yuklab olish (.txt)", txt.encode("utf-8"), file_name="chek.txt")


def partners_page(kind):
    top = st.container()
    with st.form("np_" + kind, clear_on_submit=True):
        n = st.text_input("Nomi / ism")
        ph = st.text_input("Telefon")
        if st.form_submit_button("Qo'shish", type="primary") and n.strip():
            ex("INSERT INTO partners (name,phone,kind) VALUES (:n,:p,:k)", n=n.strip(), p=ph.strip(), k=kind)
            log(f"{kind} qo'shildi", n.strip())
            st.success("Qo'shildi.")
    with top:
        show_df(partner_balances(kind), {"id": "ID", "name": "Nomi", "phone": "Telefon", "kind": "Turi", "balance": "Balans (+ u bizga qarz, − biz unga qarz)"})


def add_cart(p, code=None):
    for i in ss.cart:
        if i["id"] == int(p["id"]):
            i["qty"] += 1
            if code:
                i["codes"].append(code)
            return
    ss.cart.append({"id": int(p["id"]), "name": p["name"], "price": float(p["price"]), "qty": 1.0, "marked": bool(p["marked"]), "codes": [code] if code else []})


def on_scan():
    c = clean_code(ss.scan)
    ss.scan = ""
    if not c:
        return
    r = q("SELECT p.* FROM mark_codes k JOIN products p ON p.id=k.product_id WHERE k.code=:c AND k.status='omborda'", c=c)
    if not r.empty:
        if any(c in i["codes"] for i in ss.cart):
            ss.msg = ("error", "Bu kod savatda allaqachon bor.")
        else:
            add_cart(r.iloc[0], c)
        return
    if not q("SELECT 1 FROM mark_codes WHERE code=:c", c=c).empty:
        ss.msg = ("error", "⛔ Bu markirovka kodi omborda yo'q (sotilgan)!")
        return
    r = q("SELECT * FROM products WHERE barcode=:c AND active=1", c=c)
    if r.empty:
        ss.msg = ("error", "Kod topilmadi.")
        return
    p = r.iloc[0]
    if p["marked"]:
        ss.msg = ("warning", "Bu tovar markirovkali: 2D (DataMatrix) kodni skanerlang.")
        return
    have = sum(i["qty"] for i in ss.cart if i["id"] == int(p["id"]))
    if have + 1 > p["stock"]:
        ss.msg = ("error", f"Omborda yetarli emas. Qoldiq: {p['stock']:g}")
        return
    add_cart(p)


if menu == "pos":
    prods = q("SELECT * FROM products WHERE active=1 ORDER BY name")
    accs = acc_balances()
    c1, c2 = st.columns([3, 2])
    with c1:
        st.text_input("📷 Skaner: shtrix-kod yoki markirovka kodi (ixtiyoriy)", key="scan", on_change=on_scan)
        if ss.msg:
            getattr(st, ss.msg[0])(ss.msg[1])
            ss.msg = None
        if prods.empty:
            st.info("Tovarlar yo'q. Ombor → Tovarlar va Xaridlar → Omborga kirim orqali kiriting.")
        else:
            names = {int(r["id"]): f"{r['name']}   |   qoldiq: {r['stock']:g} {r['unit'] or ''}   |   {r['price']:,.0f} so'm" + ("   |   🏷️ markirovka" if r["marked"] else "")
                     for _, r in prods.iterrows()}
            pid = st.selectbox("🔍 Tovar (nomini yozib qidiring):", [None] + list(names), format_func=lambda x: "— tanlang —" if x is None else names[x])
            if pid:
                p = prods[prods["id"] == pid].iloc[0]
                incart = sum(i["qty"] for i in ss.cart if i["id"] == pid)
                a, b, c = st.columns(3)
                a.metric("Omborda", f"{p['stock']:g} {p['unit'] or ''}")
                b.metric("Narxi", m(p["price"]))
                c.metric("Savatdan keyin qoladi", f"{p['stock'] - incart:g}")
                if p["stock"] - incart <= 0:
                    st.error("Omborda qolmagan.")
                if p["marked"]:
                    st.warning("Markirovkali tovar: 2D (DataMatrix) kodni skanerlang.")
                else:
                    qty = st.number_input("Miqdori:", min_value=0.01, value=1.0, step=1.0, key=f"q_{pid}")
                    if st.button("➕ Savatga qo'shish", type="primary"):
                        if incart + qty > p["stock"]:
                            st.error(f"Omborda yetarli emas. Qoldiq: {p['stock']:g}, savatda: {incart:g}")
                        else:
                            for i in ss.cart:
                                if i["id"] == pid:
                                    i["qty"] += qty
                                    break
                            else:
                                ss.cart.append({"id": int(pid), "name": p["name"], "price": float(p["price"]), "qty": qty, "marked": False, "codes": []})
                            st.rerun()
    with c2:
        st.markdown("### 🛍️ Savat")
        if ss.cart:
            cart = pd.DataFrame(ss.cart)
            cart["jami"] = cart["price"] * cart["qty"]
            show_df(cart[["name", "qty", "price", "jami"]], {"name": "Tovar", "qty": "Miqdor", "price": "Narx", "jami": "Jami"})
            total = float(cart["jami"].sum())
            st.markdown(f"## Jami: **{m(total)}**")
            nas = st.checkbox("🧾 Nasiyaga (qarzga) sotish")
            pid_c, cname, due = None, "", total
            if nas:
                custs = q("SELECT id,name FROM partners WHERE kind='Mijoz' ORDER BY name")
                pid_c = pick("Mijoz:", custs, "id", "name", none="— tanlang —")
                nn = st.text_input("yoki yangi mijoz ismi")
                if nn.strip() and pid_c is None:
                    cname = nn.strip()
                due = st.number_input("Hozir to'lanadigan summa (qolgani nasiya):", min_value=0.0, max_value=total, value=0.0, step=1000.0)
                st.markdown(f"Nasiya (qarz): **{m(total - due)}**")
            method, acc, given, change, blocked = None, None, 0.0, 0.0, False
            if due > 0:
                method = st.radio("To'lov turi:", ["Naqd", "Karta"], horizontal=True)
                kind = "Naqd kassa" if method == "Naqd" else "Karta"
                ak = accs[accs["kind"] == kind].copy() if not accs.empty else accs
                if ak.empty:
                    st.error(f"«{kind}» hisobi yo'q. Bank va kassa → Hisoblar da qo'shing.")
                    blocked = True
                else:
                    ak["label"] = ak.apply(lambda r: r["name"] + (f" (**** {r['number'][-4:]})" if method == "Karta" and r["number"] else ""), axis=1)
                    acc = pick("Naqd kassa:" if method == "Naqd" else "Qaysi karta:", ak, "id", "label")
                if method == "Naqd":
                    given = st.number_input("💵 Mijoz bergan summa:", min_value=0.0, value=float(due), step=1000.0, key=f"given_{int(due)}")
                    change = given - due
                    if change >= 0:
                        st.success(f"💰 Qaytim: {m(change)}")
                    else:
                        st.error(f"Yetishmayapti: {m(-change)}")
                        blocked = True
            if st.button("✅ Sotuvni yakunlash (chek)", type="primary", disabled=blocked):
                if nas and pid_c is None and not cname:
                    st.error("Nasiya uchun mijozni tanlang yoki yangi mijoz ismini kiriting.")
                else:
                    try:
                        debt = total - due
                        with ENGINE.begin() as c:
                            if nas and pid_c is None:
                                pid_c = c.execute(text("INSERT INTO partners (name,kind) VALUES (:n,'Mijoz') RETURNING id"), {"n": cname}).scalar()
                            cn = c.execute(text("SELECT name FROM partners WHERE id=:i"), {"i": pid_c}).scalar() if pid_c else ""
                            sid = c.execute(text("""INSERT INTO sales (created,cashier,payment,customer,total,partner_id,paid,debt,given,change_amt,account_id)
                                                    VALUES (:t,:u,:p,:c,:s,:pi,:pd,:db,:g,:ch,:a) RETURNING id"""),
                                            {"t": now(), "u": user["username"], "p": method or "Nasiya", "c": cn, "s": total, "pi": pid_c, "pd": due, "db": debt,
                                             "g": given if method == "Naqd" else 0, "ch": max(change, 0) if method == "Naqd" else 0, "a": acc}).scalar()
                            for i in ss.cart:
                                r = c.execute(text("UPDATE products SET stock = stock - :q WHERE id=:i AND stock >= :q"), {"q": i["qty"], "i": i["id"]})
                                if r.rowcount == 0:
                                    raise ValueError(f"{i['name']}: omborda yetarli emas")
                                for code in i["codes"]:
                                    r = c.execute(text("UPDATE mark_codes SET status='sotilgan', sale_id=:s WHERE code=:c AND product_id=:p AND status='omborda'"),
                                                  {"s": sid, "c": code, "p": i["id"]})
                                    if r.rowcount == 0:
                                        raise ValueError(f"{i['name']}: kod omborda yo'q")
                                c.execute(text("INSERT INTO sale_items (sale_id,product_id,name,qty,price,codes) VALUES (:s,:p,:n,:q,:pr,:cd)"),
                                          {"s": sid, "p": i["id"], "n": i["name"], "q": i["qty"], "pr": i["price"], "cd": ",".join(i["codes"])})
                            if debt > 0:
                                c.execute(text("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,:d,'Nasiya savdo',:u)"),
                                          {"t": now(), "p": pid_c, "a": debt, "d": f"Sotuv №{sid}", "u": user["username"]})
                            if due > 0:  # kassaga faqat sof tushum (qaytim ayirilgan) yoziladi
                                c.execute(text("INSERT INTO cash_moves (created,account_id,amount,doc,note,user_name) VALUES (:t,:a,:s,:d,:n,:u)"),
                                          {"t": now(), "a": acc, "s": due, "d": f"Sotuv №{sid}", "n": f"Savdo tushumi ({method})", "u": user["username"]})
                        ss.receipt = build_receipt(sid)
                        log("Sotuv", f"№{sid}, {m(total)}, {method or 'Nasiya'}" + (f", nasiya {m(debt)}" if debt > 0 else ""))
                        ss.cart = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"Xato: {e}")
            b1, b2 = st.columns(2)
            if b1.button("↩️ Oxirgisini o'chirish"):
                last = ss.cart[-1]
                if last["codes"]:
                    last["codes"].pop()
                    last["qty"] -= 1
                    if last["qty"] <= 0:
                        ss.cart.pop()
                else:
                    ss.cart.pop()
                st.rerun()
            if b2.button("🗑️ Tozalash"):
                ss.cart = []
                st.rerun()
        else:
            st.info("Savat bo'sh. Tovarni tanlang yoki kodini skanerlang.")
        if ss.receipt:
            st.markdown("**Oxirgi chek:**")
            show_receipt(ss.receipt)

elif menu == "sotuvlar":
    sales = q("SELECT id,created,cashier,payment,customer,total,COALESCE(paid, CASE WHEN payment='Nasiya' THEN 0 ELSE total END) AS paid_, COALESCE(debt, CASE WHEN payment='Nasiya' THEN total ELSE 0 END) AS debt_ FROM sales ORDER BY id DESC LIMIT 200")
    show_df(sales, {"id": "№", "created": "Vaqt", "cashier": "Kassir", "payment": "To'lov", "customer": "Mijoz", "total": "Summa", "paid_": "To'langan", "debt_": "Nasiya (qarz)"})
    if not sales.empty:
        sid = st.selectbox("Chek tarkibi:", sales["id"].tolist())
        show_df(q("SELECT name,qty,price,codes FROM sale_items WHERE sale_id=:s", s=int(sid)), {"name": "Tovar", "qty": "Miqdor", "price": "Narx", "codes": "Markirovka kodlari"})
        show_receipt(build_receipt(sid))

elif menu == "mijoz":
    partners_page("Mijoz")

elif menu == "taminot":
    partners_page("Yetkazib beruvchi")

elif menu == "tovar":
    top = st.container()
    with st.form("addp", clear_on_submit=True):
        st.markdown("**Yangi tovar kartochkasi** (nechta kelganini Xaridlar → Omborga kirim da kiritasiz)")
        n = st.text_input("Nomi")
        c1, c2 = st.columns(2)
        unit = c1.selectbox("Birlik", ["dona", "kg", "quti", "metr", "litr"])
        bc = c2.text_input("Shtrix-kod (ixtiyoriy)")
        price = c1.number_input("Sotuv narxi (so'm)", min_value=0.0, value=1000.0, step=500.0)
        cost = c2.number_input("Tan narxi (so'm)", min_value=0.0, value=0.0, step=500.0)
        marked = st.checkbox("Markirovkali tovar (2D / DataMatrix kod bilan sotiladi)")
        if st.form_submit_button("Saqlash", type="primary") and n.strip():
            ex("INSERT INTO products (name,unit,price,cost,barcode,marked,stock,active) VALUES (:n,:u,:p,:c,:b,:m,0,1)",
               n=n.strip(), u=unit, p=price, c=cost, b=bc.strip() or None, m=int(marked))
            log("Tovar qo'shildi", n.strip())
            st.success("Qo'shildi.")
    prods = q("SELECT * FROM products WHERE active=1 ORDER BY name")
    if not prods.empty:
        with st.form("editp"):
            st.markdown("**Tovarni o'zgartirish**")
            pid = pick("Tovar", prods, "id", "name")
            newp = st.number_input("Yangi sotuv narxi (0 = o'zgartirmaslik)", min_value=0.0, step=500.0)
            newb = st.text_input("Yangi shtrix-kod (bo'sh = o'zgartirmaslik)")
            arch = st.checkbox("Arxivga olish (ro'yxatdan olib tashlash)")
            if st.form_submit_button("Saqlash"):
                old = prods[prods["id"] == pid].iloc[0]
                if newp > 0:
                    ex("UPDATE products SET price=:p WHERE id=:i", p=newp, i=int(pid))
                    log("Narx o'zgardi", f"{old['name']}: {old['price']:,.0f} → {newp:,.0f}")
                if newb.strip():
                    ex("UPDATE products SET barcode=:b WHERE id=:i", b=newb.strip(), i=int(pid))
                    log("Shtrix-kod o'zgardi", old["name"])
                if arch:
                    ex("UPDATE products SET active=0 WHERE id=:i", i=int(pid))
                    log("Tovar arxivga olindi", old["name"])
                st.success("Saqlandi.")
    with top:
        t = q("SELECT * FROM products WHERE active=1 ORDER BY name")
        t["marked"] = t["marked"].map(lambda x: "Ha" if x else "")
        t["barcode"] = t["barcode"].fillna("")
        show_df(t[["id", "name", "unit", "barcode", "marked", "price", "cost", "stock"]], {**RN_P, "marked": "Markirovka"})

elif menu == "kirim":
    NEW = -1
    if ss.get("kirim_ok"):
        st.success(ss.kirim_ok)
        ss.kirim_ok = None
    sup = q("SELECT id,name FROM partners WHERE kind='Yetkazib beruvchi' ORDER BY name")
    prods = q("SELECT * FROM products WHERE active=1 ORDER BY name")
    snames, pnames = dict(zip(sup["id"], sup["name"])), dict(zip(prods["id"], prods["name"]))

    st.markdown("### 1️⃣ Yetkazib beruvchi (kimdan keldi?)")
    sp = st.selectbox("Yetkazib beruvchi", [None] + sup["id"].tolist() + [NEW], key="rc_sup",
                      format_func=lambda x: "— yetkazib beruvchisiz —" if x is None else ("➕ Yangi yetkazib beruvchi (nomini yozaman)" if x == NEW else snames[x]))
    new_sup = st.text_input("Yangi yetkazib beruvchi nomi", key="rc_newsup").strip() if sp == NEW else ""

    st.markdown("### 2️⃣ Tovar va nechta keldi")
    pp = st.selectbox("Tovar", [NEW] + prods["id"].tolist(), key="rc_prod",
                      format_func=lambda x: "➕ Yangi tovar (ro'yxatda yo'q)" if x == NEW else pnames[x])
    if pp == NEW:
        c1, c2, c3 = st.columns(3)
        nn = c1.text_input("Yangi tovar nomi", key="rc_nn").strip()
        unit = c2.selectbox("Birlik", ["dona", "kg", "quti", "metr", "litr"], key="rc_unit")
        marked = c3.checkbox("Markirovkali", key="rc_mk")
        cost0 = price0 = 0.0
    else:
        p = prods[prods["id"] == pp].iloc[0]
        nn, unit, marked = p["name"], p["unit"] or "dona", bool(p["marked"])
        cost0, price0 = float(p["cost"] or 0), float(p["price"] or 0)
        st.caption(f"Hozir omborda: **{p['stock']:g} {unit}**")
    c1, c2 = st.columns(2)
    cost = c1.number_input("Tan narxi (1 ta uchun, so'm)", min_value=0.0, value=cost0, step=500.0, key=f"rc_cost_{pp}")
    price = c2.number_input("Sotuv narxi (1 ta uchun, so'm)", min_value=0.0, value=price0, step=500.0, key=f"rc_price_{pp}")
    codes_in = []
    if marked:
        txt = st.text_area("Markirovka kodlari (har qatorda bitta; skaner bilan ketma-ket o'qing yoki ro'yxatni joylang)", height=120, key=f"rc_codes_{pp}")
        up = st.file_uploader("yoki .txt / .csv fayl (har qatorda bitta kod)", type=["txt", "csv"], key=f"rc_up_{pp}")
        raw = txt.splitlines() + (up.getvalue().decode("utf-8", "ignore").splitlines() if up else [])
        codes_in = list(dict.fromkeys(c for c in (clean_code(x).split(",")[0].strip() for x in raw) if c))
        qty = float(len(codes_in))
        st.caption(f"Kodlar soni = kelgan miqdor: **{len(codes_in)}**")
    else:
        qty = st.number_input(f"Nechta {unit} keldi?", min_value=0.0, value=0.0, step=1.0, key=f"rc_qty_{pp}")
    if st.button("➕ Ro'yxatga qo'shish", type="primary"):
        low = {x.lower() for x in prods["name"]} | {r["name"].lower() for r in ss.rc if r["pid"] is None}
        if pp == NEW and not nn:
            st.error("Yangi tovar nomini yozing.")
        elif pp == NEW and nn.lower() in low:
            st.error("Bunday tovar allaqachon bor. Ro'yxatdan tanlang.")
        elif qty <= 0:
            st.error("Nechta kelganini kiriting (yoki markirovka kodlarini).")
        else:
            bad = (existing_codes(codes_in) if codes_in else set()) | ({c for r in ss.rc for c in r["codes"]} & set(codes_in))
            if bad:
                st.error(f"{len(bad)} ta kod allaqachon bor, masalan: {next(iter(bad))}")
            else:
                ss.rc.append({"pid": None if pp == NEW else int(pp), "name": nn, "unit": unit, "marked": marked, "qty": qty, "cost": cost, "price": price, "codes": codes_in})
                st.rerun()

    if ss.rc:
        st.markdown("### 3️⃣ Kirim ro'yxati")
        rc = pd.DataFrame(ss.rc)
        rc["jami"] = rc["qty"] * rc["cost"]
        show_df(rc[["name", "qty", "unit", "cost", "jami"]], {"name": "Tovar", "qty": "Nechta keldi", "unit": "Birlik", "cost": "Tan narxi", "jami": "Jami"})
        total = float(rc["jami"].sum())
        st.markdown(f"#### Kirim summasi: **{m(total)}**")
        accs = acc_balances()
        c1, c2 = st.columns(2)
        paid = c1.number_input("Hozir yetkazib beruvchiga to'langan summa:", min_value=0.0, max_value=total, value=0.0, step=1000.0)
        acc = None
        if paid > 0 and not accs.empty:
            with c2:
                acc = pick("Qaysi hisobdan to'landi:", accs, "id", "name", none="—")
        st.caption(f"Qolgan {m(total - paid)} yetkazib beruvchiga qarz bo'lib yoziladi.")
        b1, b2 = st.columns(2)
        if b1.button("✅ Kirimni saqlash", type="primary"):
            if sp == NEW and not new_sup:
                st.error("Yangi yetkazib beruvchi nomini yozing.")
            elif sp is None and paid < total:
                st.error("Qarzga olingan bo'lsa, yetkazib beruvchini tanlang yoki yozing.")
            elif paid > 0 and acc is None:
                st.error("To'lov hisobini tanlang (Bank va kassa → Hisoblar).")
            else:
                try:
                    with ENGINE.begin() as c:
                        partner = sp
                        if sp == NEW:
                            partner = c.execute(text("SELECT id FROM partners WHERE name=:n AND kind='Yetkazib beruvchi'"), {"n": new_sup}).scalar()
                            if partner is None:
                                partner = c.execute(text("INSERT INTO partners (name,kind) VALUES (:n,'Yetkazib beruvchi') RETURNING id"), {"n": new_sup}).scalar()
                        rid = c.execute(text("INSERT INTO receipts (created,user_name,partner_id,total,paid) VALUES (:t,:u,:p,:s,:pd) RETURNING id"),
                                        {"t": now(), "u": user["username"], "p": partner, "s": total, "pd": paid}).scalar()
                        for r in ss.rc:
                            pid_ = r["pid"]
                            if pid_ is None:
                                pid_ = c.execute(text("INSERT INTO products (name,unit,price,cost,marked,stock,active) VALUES (:n,:u,:p,:c,:m,0,1) RETURNING id"),
                                                 {"n": r["name"], "u": r["unit"], "p": r["price"], "c": r["cost"], "m": int(r["marked"])}).scalar()
                            c.execute(text("INSERT INTO receipt_items (receipt_id,product_id,name,qty,cost) VALUES (:r,:p,:n,:q,:c)"),
                                      {"r": rid, "p": pid_, "n": r["name"], "q": r["qty"], "c": r["cost"]})
                            c.execute(text("UPDATE products SET stock = stock + :q, cost=:c, price=:pr WHERE id=:p"),
                                      {"q": r["qty"], "c": r["cost"], "pr": r["price"], "p": pid_})
                            if r["codes"]:
                                c.execute(text("INSERT INTO mark_codes (product_id,code,status,receipt_id) VALUES (:p,:c,'omborda',:r)"),
                                          [{"p": pid_, "c": x, "r": rid} for x in r["codes"]])
                        if partner:
                            c.execute(text("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,:d,'Tovar kirimi',:u)"),
                                      {"t": now(), "p": partner, "a": -total, "d": f"Kirim №{rid}", "u": user["username"]})
                        if paid > 0:
                            c.execute(text("INSERT INTO cash_moves (created,account_id,amount,partner_id,doc,note,user_name) VALUES (:t,:a,:s,:p,:d,'Kirim uchun to''lov',:u)"),
                                      {"t": now(), "a": acc, "s": -paid, "p": partner, "d": f"Kirim №{rid}", "u": user["username"]})
                            if partner:
                                c.execute(text("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,:d,'To''lov',:u)"),
                                          {"t": now(), "p": partner, "a": paid, "d": f"Kirim №{rid}", "u": user["username"]})
                    log("Omborga kirim", f"№{rid}, {m(total)}, {len(ss.rc)} qator")
                    ss.kirim_ok = f"✅ Kirim №{rid} saqlandi: {len(ss.rc)} ta tovar, {m(total)}. Qoldiq yangilandi."
                    ss.rc = []
                    st.rerun()
                except Exception as e:
                    st.error(f"Xato: {e}")
        if b2.button("↩️ Oxirgi qatorni o'chirish"):
            ss.rc.pop()
            st.rerun()

    st.markdown("---")
    st.markdown("### 📦 Ombordagi tovarlar (hozirgi qoldiq)")
    cur = q("SELECT name, unit, stock, cost, price FROM products WHERE active=1 ORDER BY name")
    if cur.empty:
        st.info("Omborda hali tovar yo'q. Yuqorida «Yangi tovar» tanlab, birinchi kirimni kiriting.")
    else:
        cur["summa"] = cur["stock"] * cur["cost"].fillna(0)
        show_df(cur, {"name": "Tovar", "unit": "Birlik", "stock": "Qoldiq", "cost": "Tan narxi", "price": "Sotuv narxi", "summa": "Qoldiq summasi (tan narx)"})
        st.caption(f"Jami {len(cur)} xil tovar, qoldiq summasi: {m(cur['summa'].sum())}")

elif menu == "kirimlar":
    rs = q("""SELECT r.id, r.created, p.name AS partner, r.total, r.paid, r.user_name FROM receipts r
              LEFT JOIN partners p ON p.id=r.partner_id ORDER BY r.id DESC LIMIT 200""")
    show_df(rs, {"id": "№", "created": "Vaqt", "partner": "Yetkazib beruvchi", "total": "Summa", "paid": "To'langan", "user_name": "Kim kiritdi"})
    if not rs.empty:
        rid = st.selectbox("Kirim tarkibi:", rs["id"].tolist())
        show_df(q("SELECT name,qty,cost FROM receipt_items WHERE receipt_id=:r", r=int(rid)), {"name": "Tovar", "qty": "Miqdor", "cost": "Tan narxi"})

elif menu == "qoldiq":
    prods = q("SELECT * FROM products WHERE active=1 ORDER BY name")
    if prods.empty:
        st.info("Tovarlar yo'q.")
    else:
        c1, c2, c3 = st.columns([2, 1, 1])
        s = c1.text_input("🔍 Nomi yoki shtrix-kod")
        only = c2.checkbox("Faqat qoldig'i borlar")
        low = c3.checkbox("Kam qoldiq (≤ 5)")
        v = prods
        if s:
            v = v[v["name"].str.contains(s, case=False, na=False) | v["barcode"].fillna("").str.contains(s, case=False)]
        if only:
            v = v[v["stock"] > 0]
        if low:
            v = v[v["stock"] <= 5]
        a, b, c = st.columns(3)
        a.metric("Tovar turlari", len(v))
        b.metric("Qoldiq bahosi (tan narx)", m((v["stock"] * v["cost"].fillna(0)).sum()))
        c.metric("Qoldiq bahosi (sotuv narx)", m((v["stock"] * v["price"]).sum()))
        v = v.copy()
        v["marked"] = v["marked"].map(lambda x: "Ha" if x else "")
        v["summa"] = v["stock"] * v["cost"].fillna(0)
        show_df(v[["name", "unit", "barcode", "marked", "stock", "cost", "price", "summa"]],
                {"name": "Tovar", "unit": "Birlik", "barcode": "Shtrix-kod", "marked": "Markirovka", "stock": "Qoldiq", "cost": "Tan narxi", "price": "Sotuv narxi", "summa": "Qoldiq summasi"})
        st.markdown("**Tovar harakati (kirim / sotuv)**")
        pid = pick("Tovar:", prods, "id", "name", key="mv")
        mv = q("""SELECT r.created AS vaqt, 'Kirim №' || r.id AS hujjat, ri.qty AS miqdor FROM receipt_items ri JOIN receipts r ON r.id=ri.receipt_id WHERE ri.product_id=:p
                  UNION ALL
                  SELECT s.created, 'Sotuv №' || s.id, -si.qty FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE si.product_id=:p
                  ORDER BY 1 DESC""", p=int(pid))
        show_df(mv, {"vaqt": "Vaqt", "hujjat": "Hujjat", "miqdor": "Miqdor (+kirim / −sotuv)"})

elif menu == "kodlar":
    mp = q("SELECT * FROM products WHERE marked=1 AND active=1 ORDER BY name")
    if mp.empty:
        st.info("Markirovkali tovar yo'q. Ombor → Tovarlar da «Markirovkali» belgisini qo'ying.")
    else:
        cnt = q("SELECT product_id, SUM(CASE WHEN status='omborda' THEN 1 ELSE 0 END) AS omborda, SUM(CASE WHEN status='sotilgan' THEN 1 ELSE 0 END) AS sotilgan FROM mark_codes GROUP BY product_id")
        t = mp.merge(cnt, left_on="id", right_on="product_id", how="left").fillna({"omborda": 0, "sotilgan": 0})
        show_df(t[["name", "omborda", "sotilgan"]], {"name": "Tovar", "omborda": "Omborda (kod)", "sotilgan": "Sotilgan (kod)"})
        pid = pick("Tovar kodlari:", mp, "id", "name")
        s = st.text_input("Kod bo'yicha qidirish")
        k = q("SELECT code,status,receipt_id,sale_id FROM mark_codes WHERE product_id=:p ORDER BY id DESC LIMIT 1000", p=int(pid))
        if s:
            k = k[k["code"].str.contains(s, case=False)]
        show_df(k, {"code": "Kod", "status": "Holati", "receipt_id": "Kirim №", "sale_id": "Sotuv №"})

elif menu == "hisob":
    top = st.container()
    if user["role"] == "admin":
        with st.form("na", clear_on_submit=True):
            st.markdown("**Yangi hisob**")
            c1, c2 = st.columns(2)
            n = c1.text_input("Nomi (masalan: Asosiy kassa, Ipak Yo'li hisobi, Uzcard)")
            kd = c2.selectbox("Turi", ["Naqd kassa", "Bank hisobi", "Karta"])
            num = c1.text_input("Hisob / karta raqami")
            op = c2.number_input("Boshlang'ich qoldiq (so'm)", value=0.0, step=1000.0)
            if st.form_submit_button("Qo'shish", type="primary") and n.strip():
                ex("INSERT INTO accounts (name,kind,number,opening) VALUES (:n,:k,:u,:o)", n=n.strip(), k=kd, u=num.strip(), o=op)
                log("Hisob qo'shildi", f"{n.strip()} ({kd})")
                st.success("Qo'shildi.")
    with top:
        ab = acc_balances()
        if ab.empty:
            st.info("Hisoblar yo'q. Pastdagi formadan qo'shing (naqd kassa, bank hisobi, karta). Savdo tushumi shu hisoblarga avtomatik yoziladi.")
        else:
            st.metric("Jami pul", m(ab["balance"].sum()))
            cols = st.columns(min(len(ab), 4))
            for i, r in ab.iterrows():
                cols[i % len(cols)].metric(f"{r['name']} ({r['kind']})", m(r["balance"]), r["number"] or None, delta_color="off")

elif menu == "tolov":
    accs = acc_balances()
    if accs.empty:
        st.info("Avval Bank va kassa → Hisoblar da hisob qo'shing.")
    else:
        kind = st.radio("Amal turi:", ["Chiqim (to'lash)", "Kirim (qabul qilish)", "Hisobdan hisobga o'tkazma"], horizontal=True)
        with st.form("pay", clear_on_submit=True):
            acc = pick("Hisob:", accs, "id", "name")
            acc2, partner = None, None
            if kind.startswith("Hisobdan"):
                acc2 = pick("Qaysi hisobga:", accs, "id", "name", key="acc2")
            else:
                allp = q("SELECT id, name || ' (' || kind || ')' AS name FROM partners ORDER BY name")
                partner = pick("Kontragent:", allp, "id", "name", none="— kontragentsiz (boshqa) —")
            amt = st.number_input("Summa (so'm)", min_value=0.0, step=1000.0)
            note = st.text_input("Izoh")
            if st.form_submit_button("Bajarish", type="primary"):
                bal = float(accs.loc[accs["id"] == acc, "balance"].iloc[0])
                if amt <= 0:
                    st.error("Summani kiriting.")
                elif not kind.startswith("Kirim") and amt > bal:
                    st.error(f"Hisobda yetarli mablag' yo'q: {m(bal)}")
                elif acc2 is not None and acc2 == acc:
                    st.error("Hisoblar bir xil.")
                else:
                    t = now()
                    mv = "INSERT INTO cash_moves (created,account_id,amount,partner_id,doc,note,user_name) VALUES (:t,:a,:s,:p,:d,:n,:u)"
                    if acc2 is not None:
                        ex(mv, t=t, a=int(acc), s=-amt, p=None, d="O'tkazma", n=note, u=user["username"])
                        ex(mv, t=t, a=int(acc2), s=amt, p=None, d="O'tkazma", n=note, u=user["username"])
                    elif kind.startswith("Chiqim"):
                        ex(mv, t=t, a=int(acc), s=-amt, p=partner, d="To'lov (chiqim)", n=note, u=user["username"])
                        if partner:
                            ex("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,'To''lov (chiqim)',:n,:u)", t=t, p=partner, a=amt, n=note, u=user["username"])
                    else:
                        ex(mv, t=t, a=int(acc), s=amt, p=partner, d="To'lov (kirim)", n=note, u=user["username"])
                        if partner:
                            ex("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,'To''lov (kirim)',:n,:u)", t=t, p=partner, a=-amt, n=note, u=user["username"])
                    log(kind, f"{m(amt)} | {note}")
                    st.success("Amal bajarildi.")
        st.caption("Eslatma: bu yerda to'lov hisob-kitobga yoziladi. Bank/karta orqali haqiqiy pul o'tkazish (Payme, Click, bank API) hali ulanmagan.")

elif menu == "harakat":
    ab = acc_balances()
    aid = pick("Hisob:", ab, "id", "name", none="Barchasi") if not ab.empty else None
    sql = """SELECT k.created, a.name AS acc, k.doc, k.note, p.name AS partner, k.amount, k.user_name FROM cash_moves k
             JOIN accounts a ON a.id=k.account_id LEFT JOIN partners p ON p.id=k.partner_id"""
    d = q(sql + (" WHERE k.account_id=:a" if aid else "") + " ORDER BY k.id DESC LIMIT 300", **({"a": int(aid)} if aid else {}))
    show_df(d, {"created": "Vaqt", "acc": "Hisob", "doc": "Hujjat", "note": "Izoh", "partner": "Kontragent", "amount": "Summa (+kirim / −chiqim)", "user_name": "Kim"})

elif menu == "kassa":
    c1, c2 = st.columns(2)
    d1 = c1.date_input("Boshlanish", value=date.today().replace(day=1), key="kd1")
    d2 = c2.date_input("Tugash", value=date.today(), key="kd2")
    st0, en = f"{d1} 00:00:00", f"{d2} 23:59:59"
    ab = q("SELECT id,name,kind,opening FROM accounts WHERE active=1 ORDER BY id")
    mv = q("SELECT account_id, created, amount FROM cash_moves")
    if ab.empty:
        st.info("Hisoblar yo'q. Bank va kassa → Hisoblar da qo'shing.")
    else:
        rows = []
        for _, a_ in ab.iterrows():
            x = mv[mv["account_id"] == a_["id"]]
            op = a_["opening"] + x.loc[x["created"] < st0, "amount"].sum()
            per = x[(x["created"] >= st0) & (x["created"] <= en)]
            kir, chi = per.loc[per["amount"] > 0, "amount"].sum(), -per.loc[per["amount"] < 0, "amount"].sum()
            rows.append({"Hisob": a_["name"], "Turi": a_["kind"], "Davr boshida": op, "Kirim": kir, "Chiqim": chi, "Davr oxirida": op + kir - chi})
        t = pd.DataFrame(rows)
        a, b, c = st.columns(3)
        a.metric("Jami kirim", m(t["Kirim"].sum()))
        b.metric("Jami chiqim", m(t["Chiqim"].sum()))
        c.metric("Hozirgi jami pul", m(acc_balances()["balance"].sum()))
        show_df(t)
    sl = q(SALES_SQL + " WHERE created >= :a AND created <= :b", a=st0, b=en)
    st.markdown("**Savdo tahlili (shu davr)**")
    a, b, c, d, e = st.columns(5)
    a.metric("Savdo jami", m(sl["total"].sum()))
    b.metric("Naqd tushum", m(sl.loc[sl["payment"] == "Naqd", "paid_"].sum()))
    c.metric("Karta tushum", m(sl.loc[sl["payment"] == "Karta", "paid_"].sum()))
    d.metric("Nasiyaga sotildi", m(sl["debt_"].sum()))
    e.metric("Qaytim berildi", m(sl["change_amt"].fillna(0).sum()))
    if not mv.empty:
        dd = mv[(mv["created"] >= st0) & (mv["created"] <= en)].copy()
        if not dd.empty:
            dd["Kun"] = dd["created"].str[:10]
            dd["Kirim"] = dd["amount"].clip(lower=0)
            dd["Chiqim"] = (-dd["amount"]).clip(lower=0)
            st.markdown("**Kunlar bo'yicha (barcha hisoblar)**")
            show_df(dd.groupby("Kun")[["Kirim", "Chiqim"]].sum().reset_index())

elif menu == "hisobot":
    c1, c2 = st.columns(2)
    d1 = c1.date_input("Boshlanish", value=date.today().replace(day=1))
    d2 = c2.date_input("Tugash", value=date.today())
    sl = q(SALES_SQL + " WHERE created >= :a AND created <= :b", a=f"{d1} 00:00:00", b=f"{d2} 23:59:59")
    a, b, c = st.columns(3)
    a.metric("Savdo summasi", m(sl["total"].sum()))
    b.metric("Cheklar soni", len(sl))
    c.metric("Shundan nasiya", m(sl["debt_"].sum()))
    if not sl.empty:
        pm = sl[sl["paid_"] > 0].groupby("payment")["paid_"].sum()
        rows = [{"To'lov turi": k, "Summa": v} for k, v in pm.items()] + [{"To'lov turi": "Nasiya (qarz)", "Summa": sl["debt_"].sum()}]
        show_df(pd.DataFrame(rows))
        show_df(sl.groupby("cashier")["total"].agg(["count", "sum"]).reset_index(), {"cashier": "Kassir", "count": "Cheklar", "sum": "Summa"})
        top = q("""SELECT si.name, SUM(si.qty) AS qty, SUM(si.qty*si.price) AS sm FROM sale_items si JOIN sales s ON s.id=si.sale_id
                   WHERE s.created >= :a AND s.created <= :b GROUP BY si.name ORDER BY sm DESC LIMIT 20""", a=f"{d1} 00:00:00", b=f"{d2} 23:59:59")
        st.markdown("**Eng ko'p sotilgan tovarlar**")
        show_df(top, {"name": "Tovar", "qty": "Miqdor", "sm": "Summa"})

elif menu == "qarz":
    pb = partner_balances()
    owe_us, we_owe = pb[pb["balance"] > 0.5], pb[pb["balance"] < -0.5]
    a, b = st.columns(2)
    a.metric("Bizga qarzdorlar (haqimiz)", m(owe_us["balance"].sum()))
    b.metric("Biz qarzdormiz (yetkazib beruvchilar va b.)", m(-we_owe["balance"].sum()))
    st.markdown("**Kimdan haqmiz (ular bizga qarzdor)**")
    show_df(owe_us[["name", "phone", "kind", "balance"]], {"name": "Nomi", "phone": "Telefon", "kind": "Turi", "balance": "Qarz summasi"})
    st.markdown("**Kimga qarzmiz**")
    w = we_owe.copy()
    w["balance"] = -w["balance"]
    show_df(w[["name", "phone", "kind", "balance"]], {"name": "Nomi", "phone": "Telefon", "kind": "Turi", "balance": "Qarz summasi"})

elif menu == "akt":
    pb = partner_balances()
    if pb.empty:
        st.info("Kontragentlar yo'q.")
    else:
        pb["label"] = pb["name"] + " (" + pb["kind"] + ")"
        pid = pick("Kontragent:", pb, "id", "label")
        c1, c2 = st.columns(2)
        d1 = c1.date_input("Davr boshi", value=date.today().replace(day=1), key="ad1")
        d2 = c2.date_input("Davr oxiri", value=date.today(), key="ad2")
        led = q("SELECT created,doc,note,amount FROM ledger WHERE partner_id=:p ORDER BY created, id", p=int(pid))
        st0, en = f"{d1} 00:00:00", f"{d2} 23:59:59"
        opening = float(led.loc[led["created"] < st0, "amount"].sum()) if not led.empty else 0.0
        per = led[(led["created"] >= st0) & (led["created"] <= en)].copy() if not led.empty else led
        per["debet"] = per["amount"].clip(lower=0)
        per["kredit"] = (-per["amount"]).clip(lower=0)
        per["qoldiq"] = opening + per["amount"].cumsum()
        closing = opening + float(per["amount"].sum())
        name = pb.loc[pb["id"] == pid, "name"].iloc[0]
        st.markdown(f"**Davr boshiga qoldiq:** {m(opening)}")
        out = per[["created", "doc", "note", "debet", "kredit", "qoldiq"]]
        show_df(out, {"created": "Sana", "doc": "Hujjat", "note": "Izoh", "debet": "Debet (u bizga qarzdor bo'ldi)", "kredit": "Kredit (to'ladi / biz qarzdor bo'ldik)", "qoldiq": "Qoldiq"})
        if closing > 0.5:
            res = f"{name} bizga {m(closing)} qarzdor."
        elif closing < -0.5:
            res = f"Biz {name} oldida {m(-closing)} qarzdormiz."
        else:
            res = "Hisob-kitob teng, qarz yo'q."
        st.success(f"{d1} – {d2} davr oxiriga: {res}")
        csv = out.rename(columns={"created": "Sana", "doc": "Hujjat", "note": "Izoh", "debet": "Debet", "kredit": "Kredit", "qoldiq": "Qoldiq"}).to_csv(index=False).encode("utf-8-sig")
        st.download_button("⬇️ Akt sverkani yuklab olish (CSV)", csv, file_name=f"akt_sverka_{name}_{d1}_{d2}.csv", mime="text/csv")

elif menu == "kassirlar":
    top = st.container()
    with st.form("nu", clear_on_submit=True):
        st.markdown("**Yangi xodim**")
        u = st.text_input("Login")
        n = st.text_input("Ism-familiya")
        p = st.text_input("Parol (kamida 6 belgi)", type="password")
        r = st.selectbox("Rol", list(ROLES), format_func=lambda x: ROLES[x], index=1)
        if st.form_submit_button("Qo'shish", type="primary"):
            if not u.strip() or len(p) < 6:
                st.error("Login kiriting va parol kamida 6 belgi bo'lsin.")
            elif not q("SELECT 1 FROM users WHERE username=:u", u=u.strip().lower()).empty:
                st.error("Bunday login bor.")
            else:
                ex("INSERT INTO users (username,full_name,pw,role) VALUES (:u,:n,:p,:r)", u=u.strip().lower(), n=n.strip(), p=hash_pw(p), r=r)
                log("Xodim qo'shildi", f"{u.strip().lower()} ({ROLES[r]})")
                st.success("Qo'shildi!")
    users = q("SELECT username, full_name, role, active FROM users ORDER BY id")
    with st.form("eu"):
        st.markdown("**Parolni almashtirish / ruxsatni o'chirish** (faqat administrator)")
        who = st.selectbox("Xodim", users["username"].tolist())
        newp = st.text_input("Yangi parol (bo'sh = o'zgarmaydi)", type="password")
        act = st.checkbox("Faol (tizimga kira oladi)", value=True)
        if st.form_submit_button("Saqlash"):
            if who == user["username"] and not act:
                st.error("O'zingizni o'chirib qo'ya olmaysiz.")
            elif newp and len(newp) < 6:
                st.error("Parol kamida 6 belgi.")
            else:
                ex("UPDATE users SET active=:a WHERE username=:u", a=int(act), u=who)
                if newp:
                    ex("UPDATE users SET pw=:p WHERE username=:u", p=hash_pw(newp), u=who)
                log("Xodim o'zgartirildi", f"{who}: faol={act}, parol {'almashtirildi' if newp else 'o`zgarmadi'}")
                st.success("Saqlandi.")
    with top:
        show_df(q("SELECT username, full_name, role, active FROM users ORDER BY id"), {"username": "Login", "full_name": "Ism", "role": "Rol", "active": "Faol"})

elif menu == "audit":
    s = st.text_input("Foydalanuvchi yoki amal bo'yicha qidirish")
    a = q("SELECT created,user_name,action,details FROM audit ORDER BY id DESC LIMIT 500")
    if s:
        a = a[a.apply(lambda r: s.lower() in f"{r['user_name']} {r['action']} {r['details']}".lower(), axis=1)]
    show_df(a, {"created": "Vaqt", "user_name": "Kim", "action": "Amal", "details": "Tafsilot"})

elif menu == "panel":
    sales = q("SELECT * FROM sales")
    today = sales[sales["created"].str[:10] == now()[:10]] if not sales.empty else sales
    ab, pb = acc_balances(), partner_balances()
    prods = q("SELECT * FROM products WHERE active=1")
    a, b, c = st.columns(3)
    a.metric("Bugungi savdo", m(today["total"].sum()))
    b.metric("Bugungi cheklar", len(today))
    c.metric("Hisoblardagi pul", m(ab["balance"].sum()) if not ab.empty else "0 so'm")
    d, e, f = st.columns(3)
    d.metric("Bizga qarzdorlar", m(pb.loc[pb["balance"] > 0, "balance"].sum()))
    e.metric("Biz qarzdormiz", m(-pb.loc[pb["balance"] < 0, "balance"].sum()))
    f.metric("Qoldig'i kam tovarlar (≤ 5)", int((prods["stock"] <= 5).sum()) if not prods.empty else 0)
