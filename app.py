import hashlib
import io
import json
import secrets
import time
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
        f"receipt_items (id {PK}, receipt_id INTEGER, product_id INTEGER, name TEXT, qty {D}, cost {D}, price {D})",
        f"mark_codes (id {PK}, product_id INTEGER, code TEXT UNIQUE NOT NULL, status TEXT, receipt_id INTEGER, sale_id INTEGER)",
        f"audit (id {PK}, created TEXT, user_name TEXT, action TEXT, details TEXT)",
        f"sessions (id {PK}, token_hash TEXT UNIQUE NOT NULL, username TEXT, created TEXT, last_seen TEXT)",
        f"carts (id {PK}, username TEXT UNIQUE NOT NULL, data TEXT, updated TEXT)",
        f"held_sales (id {PK}, created TEXT, username TEXT, label TEXT, data TEXT, total {D})",
        f"shifts (id {PK}, username TEXT, opened TEXT, closed TEXT, account_id INTEGER, open_cash {D}, expected {D}, counted {D}, diff {D}, handed {D}, note TEXT, status TEXT)",
        f"price_requests (id {PK}, created TEXT, user_name TEXT, product_id INTEGER, old_price {D}, new_price {D}, status TEXT, decided_by TEXT, decided_at TEXT)",
        "settings (k TEXT PRIMARY KEY, v TEXT)",
        f"promos (id {PK}, product_id INTEGER, title TEXT, kind TEXT, value {D}, start_date TEXT, end_date TEXT, active INTEGER DEFAULT 1)",
        f"supplier_returns (id {PK}, created TEXT, partner_id INTEGER, product_id INTEGER, name TEXT, qty {D}, price {D}, user_name TEXT, note TEXT)",
        f"stock_adj (id {PK}, created TEXT, product_id INTEGER, name TEXT, qty {D}, reason TEXT, user_name TEXT)",
    ]
    with ENGINE.begin() as c:
        for t in tables:
            c.execute(text("CREATE TABLE IF NOT EXISTS " + t))
    # eski bazalar uchun yangi ustunlar
    for t, col in [("products", "barcode TEXT"), ("products", "marked INTEGER DEFAULT 0"), ("products", f"cost {D} DEFAULT 0"),
                   ("products", "active INTEGER DEFAULT 1"), ("sales", "partner_id INTEGER"), ("sales", f"paid {D}"), ("sales", f"debt {D}"), ("sales", f"given {D}"), ("sales", f"change_amt {D}"), ("sales", "account_id INTEGER"), ("sale_items", "codes TEXT"), ("receipt_items", "price DOUBLE PRECISION"), ("sales", "due_date TEXT"), ("sale_items", "returned DOUBLE PRECISION DEFAULT 0"), ("sale_items", "base DOUBLE PRECISION")]:
        try:
            with ENGINE.begin() as c:
                c.execute(text(f"ALTER TABLE {t} ADD COLUMN {col}"))
        except Exception:
            pass
    # tezlik uchun indekslar
    for t, cols in [("sales", "created"), ("sales", "cashier"), ("sales", "partner_id"), ("sale_items", "sale_id"), ("sale_items", "product_id"),
                    ("receipts", "created"), ("receipts", "partner_id"), ("receipts", "user_name"), ("receipt_items", "receipt_id"),
                    ("receipt_items", "product_id"), ("cash_moves", "account_id"), ("cash_moves", "created"), ("cash_moves", "partner_id"),
                    ("ledger", "partner_id"), ("ledger", "created"), ("mark_codes", "product_id, status"), ("mark_codes", "sale_id"),
                    ("mark_codes", "receipt_id"), ("audit", "created"), ("products", "barcode"), ("partners", "kind")]:
        try:
            with ENGINE.begin() as c:
                c.execute(text(f"CREATE INDEX IF NOT EXISTS ix_{t}_{cols.replace(', ', '_')} ON {t} ({cols})"))
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


XL = [0]
XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def to_xlsx(df, sheet="Jadval"):
    buf = io.BytesIO()
    with pd.ExcelWriter(buf, engine="openpyxl") as w:
        df.to_excel(w, index=False, sheet_name=str(sheet)[:31] or "Jadval")
    return buf.getvalue()


def show_df(d, rename=None, color=None, xl=True):
    d = d.rename(columns=rename) if rename else d
    obj = d
    if color is not None and not d.empty:
        def sty(r):
            c = color(r)
            return [f"background-color:{c}" if c else ""] * len(r)
        obj = d.style.apply(sty, axis=1)
    try:
        st.dataframe(obj, width="stretch", hide_index=True)
    except Exception:
        st.dataframe(obj, use_container_width=True, hide_index=True)
    if xl and not d.empty:
        XL[0] += 1
        try:
            st.download_button("⬇️ Excelga yuklab olish", to_xlsx(d, globals().get("pk", "Jadval")), key=f"xl_{XL[0]}", mime=XLSX,
                               file_name=f"{globals().get('menu', 'jadval')}_{now()[:10]}.xlsx")
        except Exception:
            pass


def sv(x):
    return "" if x is None or (isinstance(x, float) and pd.isna(x)) else str(x).strip()


def nv(x):
    try:
        v = float(str(x).replace(" ", "").replace(",", "."))
        return 0.0 if pd.isna(v) else v
    except Exception:
        return 0.0


def import_box(key, title, template, on_apply):
    """Excel/CSV dan yuklash: shablon + fayl + ko'rib chiqish + tasdiqlash."""
    if ss.get("imp_msg"):
        st.success(ss.imp_msg)
        ss.imp_msg = None
    with st.expander(f"📥 Excel'dan yuklash: {title}"):
        st.download_button("📄 Shablonni yuklab olish (Excel)", to_xlsx(template, "Shablon"), file_name=f"shablon_{key}.xlsx", key=f"tpl_{key}", mime=XLSX)
        up = st.file_uploader("Excel (.xlsx) yoki CSV faylni tanlang", type=["xlsx", "csv"], key=f"up_{key}")
        if up is not None:
            try:
                df = pd.read_csv(up) if up.name.lower().endswith(".csv") else pd.read_excel(up)
            except Exception as e:
                st.error(f"Faylni o'qib bo'lmadi: {e}")
                return
            df.columns = [str(c).strip() for c in df.columns]
            st.caption(f"{len(df)} qator o'qildi. Dastlabki qatorlar:")
            show_df(df.head(15), xl=False)
            if st.button("✅ Yuklash", key=f"go_{key}", type="primary"):
                try:
                    ss.imp_msg = on_apply(df)
                except Exception as e:
                    st.error(f"Xato: {e}")
                    return
                st.rerun()


def imp_products(df):
    cur = q("SELECT id,name FROM products WHERE active=1")
    have = {n.lower(): int(i) for i, n in zip(cur["id"], cur["name"])}
    add = upd = 0
    with ENGINE.begin() as c:
        for r in df.to_dict("records"):
            name = sv(r.get("Nomi"))
            if not name:
                continue
            unit, bc = sv(r.get("Birlik")) or "dona", sv(r.get("Shtrix-kod")) or None
            mk = int(sv(r.get("Markirovka")).lower() in ("ha", "1", "yes", "true", "+"))
            cost, price = nv(r.get("Tan narxi")), nv(r.get("Sotuv narxi"))
            if name.lower() in have:
                c.execute(text("UPDATE products SET unit=:u, cost=:c, price=:p, marked=:m, barcode=COALESCE(:b, barcode) WHERE id=:i"),
                          {"u": unit, "c": cost, "p": price, "m": mk, "b": bc, "i": have[name.lower()]})
                upd += 1
            else:
                c.execute(text("INSERT INTO products (name,unit,price,cost,barcode,marked,stock,active) VALUES (:n,:u,:p,:c,:b,:m,0,1)"),
                          {"n": name, "u": unit, "p": price, "c": cost, "b": bc, "m": mk})
                have[name.lower()] = -1
                add += 1
    log("Excel'dan tovarlar yuklandi", f"qo'shildi {add}, yangilandi {upd}")
    return f"✅ Tovarlar: {add} ta yangi qo'shildi, {upd} tasi yangilandi. Qoldiqni «Omborga kirim» orqali kiriting."


def imp_partners(df, kind):
    cur = q("SELECT name FROM partners WHERE kind=:k", k=kind)
    have = {n.lower() for n in cur["name"]}
    add = 0
    with ENGINE.begin() as c:
        for r in df.to_dict("records"):
            name = sv(r.get("Nomi"))
            if name and name.lower() not in have:
                c.execute(text("INSERT INTO partners (name,phone,kind) VALUES (:n,:p,:k)"), {"n": name, "p": sv(r.get("Telefon")), "k": kind})
                have.add(name.lower())
                add += 1
    log(f"Excel'dan {kind} yuklandi", f"qo'shildi {add}")
    return f"✅ {add} ta yangi {kind.lower()} qo'shildi (takroriy nomlar o'tkazib yuborildi)."


def imp_kirim(df):
    pr = q("SELECT id,name,unit,marked,cost,price,barcode FROM products WHERE active=1").to_dict("records")
    byname = {r["name"].lower(): r for r in pr}
    bybc = {str(r["barcode"]): r for r in pr if r["barcode"]}
    ok_ = skip = 0
    for r in df.to_dict("records"):
        name, bc, qty = sv(r.get("Tovar nomi")), sv(r.get("Shtrix-kod")), nv(r.get("Soni"))
        if (not name and not bc) or qty <= 0:
            skip += 1
            continue
        p = (bybc.get(bc) if bc else None) or byname.get(name.lower())
        cost, price = nv(r.get("Tan narxi")), nv(r.get("Sotuv narxi"))
        if p is not None:
            if p["marked"]:
                skip += 1
                continue
            ss.rc.append({"pid": int(p["id"]), "name": p["name"], "unit": p["unit"] or "dona", "marked": False, "qty": qty,
                          "cost": cost or float(p["cost"] or 0), "price": price or float(p["price"] or 0), "codes": []})
        else:
            newrows = {x["name"].lower(): x for x in ss.rc if x["pid"] is None}
            if name.lower() in newrows:
                newrows[name.lower()]["qty"] += qty
            else:
                ss.rc.append({"pid": None, "name": name, "unit": sv(r.get("Birlik")) or "dona", "marked": False, "qty": qty, "cost": cost, "price": price, "codes": []})
        ok_ += 1
    return f"✅ Ro'yxatga {ok_} qator qo'shildi" + (f" ({skip} qator o'tkazib yuborildi: markirovkali yoki to'liq emas)" if skip else "") + ". Tekshirib, «Kirimni saqlash» ni bosing."


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


def get_setting(k, default=""):
    r = q("SELECT v FROM settings WHERE k=:k", k=k)
    return r.iloc[0, 0] if not r.empty else default


def set_setting(k, v):
    ex("DELETE FROM settings WHERE k=:k", k=k)
    ex("INSERT INTO settings (k,v) VALUES (:k,:v)", k=k, v=str(v))


def debtors():
    """Nasiya qarzdor mijozlar: muddati o'tgan / o'tmagan qism (to'lovlar eng eski qarzdan yopiladi)."""
    cols = ["id", "name", "phone", "balance", "overdue", "notdue", "oldest"]
    pb = partner_balances("Mijoz")
    pb = pb[pb["balance"] > 0.5]
    if pb.empty:
        return pd.DataFrame(columns=cols)
    sl = q("""SELECT partner_id, COALESCE(debt, CASE WHEN payment='Nasiya' THEN total ELSE 0 END) AS d,
              COALESCE(due_date, substr(created,1,10)) AS due FROM sales WHERE partner_id IS NOT NULL""")
    sl = sl[sl["d"] > 0.5]
    today, out = now()[:10], []
    for r in pb.itertuples():
        x = sl[sl["partner_id"] == r.id].sort_values("due")
        rem = max(float(x["d"].sum()) - float(r.balance), 0.0)
        od = nd = 0.0
        oldest = None
        for y in x.itertuples():
            cover = min(y.d, rem)
            rem -= cover
            left = y.d - cover
            if left > 0.5:
                oldest = oldest or y.due
                if y.due < today:
                    od += left
                else:
                    nd += left
        extra = float(r.balance) - od - nd
        if extra > 0.5:
            nd += extra
        out.append({"id": r.id, "name": r.name, "phone": r.phone, "balance": float(r.balance), "overdue": od, "notdue": nd, "oldest": oldest})
    return pd.DataFrame(out, columns=cols)


def promo_map():
    r = q("SELECT product_id,kind,value FROM promos WHERE active=1 AND start_date<=:d AND end_date>=:d", d=now()[:10])
    d = {}
    for x in r.itertuples():
        d.setdefault(int(x.product_id), []).append((x.kind, float(x.value)))
    return d


PM = promo_map()


def eff_price(p):
    """Faol aksiya bo'lsa aksiya narxi, bo'lmasa oddiy narx."""
    base = float(p["price"])
    best = base
    for kind, v in PM.get(int(p["id"]), []):
        best = min(best, max(base * (1 - v / 100) if kind == "foiz" else v, 0.0))
    return float(round(best))


def clean_code(s):
    return "".join(ch for ch in s if ch.isprintable()).strip()


# ================================================================ MENYU
RN_P = {"id": "ID", "name": "Tovar", "unit": "Birlik", "price": "Sotuv narxi", "stock": "Qoldiq", "barcode": "Shtrix-kod", "cost": "Tan narxi"}
ROLES = {"admin": "Administrator", "kassir": "Kassir", "omborchi": "Omborchi"}
NAV = [  # (belgi, bo'lim, [(ichki bo'lim, sahifa kaliti)])
    ("🏠", "Asosiy", [("Boshqaruv paneli", "panel")]),
    ("🛍️", "Sotuvlar", [("Kassa (POS)", "pos"), ("Smena", "smena"), ("Sotuvlar ro'yxati", "sotuvlar"), ("Mijozlar", "mijoz"), ("Aksiyalar", "aksiya")]),
    ("🧾", "Nasiya", [("Nasiya daftari", "nas_daftar"), ("Mijoz kartochkasi", "nas_karta"), ("Nasiya tahlili", "nas_tahlil")]),
    ("🛒", "Xaridlar", [("Omborga kirim", "kirim"), ("Kirim hujjatlari", "kirimlar"), ("Yetkazib beruvchilar", "taminot"), ("Yetkazib beruvchiga qaytarish", "taminotqayt")]),
    ("📦", "Ombor", [("Qoldiqlar", "qoldiq"), ("Kirim jurnali", "jurnal"), ("Tovarlar", "tovar"), ("Markirovka kodlari", "kodlar"), ("Inventarizatsiya", "inventar")]),
    ("🏦", "Buxgalteriya", [("Mijozdan to'lov", "mijoztolov"), ("To'lovlar va o'tkazmalar", "tolov"), ("To'lovni qaytarish", "qaytarish"),
                            ("Kirim-Chiqim", "harakat"), ("Kontragent to'lovlari", "kontr"), ("Kassalar (hisoblar)", "hisob"), ("Kassa tahlili", "kassa"),
                            ("Muddati o'tgan qarzdorlar", "qarz_o"), ("Muddati o'tmagan qarzdorlar", "qarz_n"), ("Narx o'zgartirish so'rovlari", "narxsorov")]),
    ("📊", "Hisobotlar", [("Savdo hisoboti", "hisobot"), ("Qarzdorlik", "qarz"), ("Akt sverka", "akt"), ("Kassirlar hisoboti", "stat")]),
    ("⚙️", "Sozlamalar", [("Xodimlar (kassirlar)", "kassirlar"), ("Audit jurnali", "audit"), ("Valyuta kursi", "kurs"), ("Do'kon ma'lumotlari", "dokon"), ("Zaxira nusxa", "zaxira")]),
]
ALLOWED = {"kassir": {"pos", "smena"}, "omborchi": {"tovar", "qoldiq", "jurnal", "kirim", "kirimlar", "kodlar", "narxsorov", "inventar"}}

ss = st.session_state
for k, v in {"user": None, "cart": [], "receipt": "", "msg": None, "rc": []}.items():
    ss.setdefault(k, v)

# ================================================================ KIRISH
if not ss.get("user"):
    st.title("🛒 Sav-do ERP")
if ENGINE.dialect.name == "sqlite":
    st.error("⚠️ DIQQAT: ma'lumotlar bazasi ulanmagan! Ma'lumotlar vaqtinchalik faylda saqlanmoqda va ilova qayta ishga tushganda YO'QOLADI. "
             "Streamlit Cloud → Settings → Secrets ga DATABASE_URL (Neon) ni yozing.")

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

def _jd(o):
    return o.item() if hasattr(o, "item") else str(o)


def tok_hash(t):
    return hashlib.sha256(t.encode()).hexdigest()


def start_session(username):
    tok = secrets.token_urlsafe(24)
    ex("INSERT INTO sessions (token_hash,username,created,last_seen) VALUES (:h,:u,:t,:t)", h=tok_hash(tok), u=username, t=now())
    st.query_params["t"] = tok
    ss.tok = tok


def end_session():
    tok = ss.get("tok") or st.query_params.get("t")
    if tok:
        try:
            ex("DELETE FROM sessions WHERE token_hash=:h", h=tok_hash(str(tok)))
        except Exception:
            pass
    try:
        st.query_params.clear()
    except Exception:
        pass
    ss.tok = None


def restore_session(idle_min):
    """Sahifa yangilanganda tokenga qarab kirishni tiklaydi."""
    tok = st.query_params.get("t")
    if not tok:
        return False
    r = q("SELECT s.last_seen, s.created AS s_created, u.username, u.full_name, u.role FROM sessions s JOIN users u ON u.username=s.username WHERE s.token_hash=:h AND u.active=1", h=tok_hash(str(tok)))
    if not r.empty:
        row = r.iloc[0]
        t_now = datetime.now(timezone(timedelta(hours=5))).replace(tzinfo=None)
        fmt = "%Y-%m-%d %H:%M:%S"
        if t_now - datetime.strptime(row["last_seen"], fmt) <= timedelta(minutes=idle_min) and t_now - datetime.strptime(row["s_created"], fmt) <= timedelta(hours=12):
            ss.user = {"username": row["username"], "name": row["full_name"] or row["username"], "role": row["role"]}
            ss.tok, ss.last_active, ss.cart_loaded = str(tok), time.time(), False
            return True
    end_session()
    return False


def load_cart():
    r = q("SELECT data FROM carts WHERE username=:u", u=ss.user["username"])
    try:
        ss.cart = json.loads(r.iloc[0, 0]) if not r.empty and r.iloc[0, 0] else []
    except Exception:
        ss.cart = []
    ss.cart_saved = json.dumps(ss.cart, ensure_ascii=False, default=_jd)


def save_cart():
    if not ss.get("user"):
        return
    js = json.dumps(ss.cart, ensure_ascii=False, default=_jd)
    if js != ss.get("cart_saved"):
        with ENGINE.begin() as c:
            r = c.execute(text("UPDATE carts SET data=:d, updated=:t WHERE username=:u"), {"d": js, "t": now(), "u": ss.user["username"]})
            if r.rowcount == 0:
                c.execute(text("INSERT INTO carts (username,data,updated) VALUES (:u,:d,:t)"), {"u": ss.user["username"], "d": js, "t": now()})
        ss.cart_saved = js


@st.cache_resource
def fail_store():
    return {}


FAILS, MAX_FAILS, LOCK_SEC = fail_store(), 5, 600

try:
    _idle0 = max(5, int(get_setting("idle_min", "30")))
except Exception:
    _idle0 = 30
if not ss.user:
    _restored = False
    try:
        _restored = restore_session(_idle0)
    except Exception:
        pass
    if _restored:
        st.rerun()

if not ss.user:
    st.subheader("🔐 Tizimga kirish")
    if ss.pop("timeout_msg", False):
        st.info("Uzoq vaqt harakatsiz qoldingiz, xavfsizlik uchun tizimdan chiqarildingiz. Qayta kiring.")
    with st.form("login"):
        u = st.text_input("Login")
        p = st.text_input("Parol", type="password")
        if st.form_submit_button("Kirish", type="primary"):
            key_, tnow = u.strip().lower(), time.time()
            recent = [x for x in FAILS.get(key_, []) if tnow - x < LOCK_SEC]
            FAILS[key_] = recent
            if len(recent) >= MAX_FAILS:
                st.error(f"Juda ko'p noto'g'ri urinish. {int((LOCK_SEC - (tnow - recent[0])) // 60) + 1} daqiqadan keyin qayta urinib ko'ring.")
            else:
                r = q("SELECT * FROM users WHERE username=:u AND active=1", u=key_)
                if not r.empty and check_pw(p, r.iloc[0]["pw"]):
                    row = r.iloc[0]
                    FAILS.pop(key_, None)
                    ss.user = {"username": row["username"], "name": row["full_name"] or row["username"], "role": row["role"]}
                    ss.last_active = time.time()
                    ss.cart_loaded = False
                    start_session(row["username"])
                    log("Tizimga kirdi")
                    st.rerun()
                else:
                    FAILS.setdefault(key_, []).append(tnow)
                    log("Kirish xatosi", key_)
                    st.error("Login yoki parol noto'g'ri.")
    st.stop()

# harakatsizlikdan keyin avtomatik chiqish (sozlama: idle_min, standart 30 daqiqa)
try:
    _idle = max(5, int(get_setting("idle_min", "30")))
except Exception:
    _idle = 30
_tn = time.time()
if ss.get("last_active") and _tn - ss.last_active > _idle * 60:
    try:
        save_cart()
        end_session()
    except Exception:
        pass
    ss.user, ss.cart, ss.last_active, ss.timeout_msg, ss.cart_loaded = None, [], None, True, False
    st.rerun()
ss.last_active = _tn
if _tn - ss.get("last_touch", 0) > 60:
    ss.last_touch = _tn
    if ss.get("tok"):
        try:
            ex("UPDATE sessions SET last_seen=:t WHERE token_hash=:h", t=now(), h=tok_hash(ss.tok))
        except Exception:
            pass
try:
    if not ss.get("cart_loaded"):
        load_cart()
        ss.cart_loaded = True
    else:
        save_cart()
except Exception:
    pass

user = ss.user
try:
    RATE = float(get_setting("usd_rate", "12130") or 12130)
except Exception:
    RATE = 12130.0
st.markdown("""<style>
section[data-testid="stSidebar"]{background:#fff;border-right:1px solid #E6E9F0;width:272px !important;min-width:272px !important}
[data-testid="stSidebar"] [data-testid="stVerticalBlock"]{gap:.2rem}
[data-testid="stSidebar"] button{position:relative;justify-content:flex-start !important;text-align:left !important;border:none;box-shadow:none;padding:.5rem .8rem;min-height:2.4rem;border-radius:10px;font-size:.95rem}
[data-testid="stSidebar"] button>div,[data-testid="stSidebar"] button p{justify-content:flex-start !important;text-align:left !important;width:100%;white-space:normal;line-height:1.25}
[data-testid="stSidebar"] button[kind="secondary"],[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]{background:transparent;color:#1F2937}
[data-testid="stSidebar"] button[kind="secondary"]:hover,[data-testid="stSidebar"] button[data-testid="stBaseButton-secondary"]:hover{background:#F1F4FB}
[data-testid="stSidebar"] button[kind="primary"],[data-testid="stSidebar"] button[data-testid="stBaseButton-primary"]{background:#E8EEFB;color:#1D4ED8;font-weight:600}
[class*="st-key-subs_"]{margin:2px 0 8px 20px;padding-left:8px;border-left:2px solid #E3E8F2}
[class*="st-key-sub_"] button{font-size:.9rem;font-weight:400;padding:.4rem .7rem;padding-right:46px;min-height:2.1rem}
[class*="st-key-sub_"] button[kind="primary"],[class*="st-key-sub_"] button[data-testid="stBaseButton-primary"]{font-weight:600}
.brand{display:flex;align-items:center;gap:10px;padding:2px 6px 14px}
.brand .logo{width:38px;height:38px;border-radius:11px;background:linear-gradient(135deg,#3B82F6,#1D4ED8);color:#fff;display:flex;align-items:center;justify-content:center;font-size:1.15rem}
.brand .bn{font-weight:700;color:#111827;line-height:1.1}.brand .bs{font-size:.72rem;color:#8A94A6}
.ucard{display:flex;align-items:center;gap:10px;margin-top:14px;padding:10px;border:1px solid #E6E9F0;border-radius:12px;background:#F8FAFD}
.ucard .av{width:32px;height:32px;border-radius:50%;background:#E6EEFF;display:flex;align-items:center;justify-content:center}
.ucard span{font-size:.75rem;color:#8A94A6}
.block-container{padding-top:1.4rem}
.topbar{display:flex;justify-content:space-between;align-items:center;gap:12px;flex-wrap:wrap;margin:0 0 12px}
.topbar .ttl{font-size:1.45rem;font-weight:700;color:#111827}
.topbar .chips{display:flex;gap:8px;flex-wrap:wrap}
.chip{background:#fff;border:1px solid #E1E5EE;border-radius:10px;padding:5px 12px;font-size:.85rem;color:#1F2937;box-shadow:0 1px 2px rgba(20,30,60,.05)}
.chip.warn{background:#FFF6DD;border-color:#F3D98B}
h3{font-weight:700}
[data-testid="stMetric"]{background:#F3F7FF;border:1px solid #D6E4FF;border-radius:14px;padding:12px 16px;box-shadow:0 1px 3px rgba(20,30,60,.05)}
[data-testid="stMetricValue"]{color:#1D4ED8}
[data-testid="stVerticalBlockBorderWrapper"]{border-radius:14px;border-color:#E6E9F0}
[data-testid="stExpander"]{border-radius:12px;border-color:#E6E9F0}
[data-testid="stDataFrame"]{border-radius:12px;overflow:hidden}
.stButton button,.stDownloadButton button{border-radius:10px}
</style>""", unsafe_allow_html=True)
st.sidebar.markdown(f"<div class='brand'><div class='logo'>🛒</div><div><div class='bn'>{html.escape(str(get_setting('shop_name', 'SAV-DO')))}</div><div class='bs'>ERP · Savdo tizimi</div></div></div>", unsafe_allow_html=True)

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


def nbtn(label, key, active, sec_, sub_, icon=None, host=None):
    host = host or st.sidebar
    kw = dict(key=key, type="primary" if active else "secondary", on_click=go, args=(sec_, sub_))
    for w in ({"width": "stretch"}, {"use_container_width": True}):
        for ic in ([{"icon": f":material/{icon}:"}] if icon else []) + [{}]:
            try:
                host.button(label, **w, **ic, **kw)
                return
            except Exception:
                continue


ICONS = {"Asosiy": "dashboard", "Sotuvlar": "shopping_cart", "Nasiya": "receipt_long", "Xaridlar": "local_shipping", "Ombor": "inventory_2",
         "Buxgalteriya": "calculate", "Hisobotlar": "bar_chart", "Sozlamalar": "settings"}


if ss.get("nav_sec") not in sec_map:
    ss.nav_sec = list(sec_map)[0]
if ss.get("nav_sub") not in [x[1] for x in sec_map[ss.nav_sec]]:
    ss.nav_sub = sec_map[ss.nav_sec][0][1]
@st.cache_data(ttl=45, show_spinner=False)
def badge_counts(is_admin):
    out = {"low": int(q("SELECT COUNT(*) FROM products WHERE active=1 AND stock<=5").iloc[0, 0])}
    if is_admin:
        out["narxsorov"] = int(q("SELECT COUNT(*) FROM price_requests WHERE status='kutilmoqda'").iloc[0, 0])
        _d = debtors()
        out["qarz_o"] = int((_d["overdue"] > 0.5).sum()) if not _d.empty else 0
    return out


BADGE, BADGE_LOW = {}, 0
if user["role"] != "kassir":
    try:
        _bc = badge_counts(user["role"] == "admin")
        BADGE_LOW = _bc.get("low", 0)
        if user["role"] == "admin":
            BADGE = {k: v for k, v in _bc.items() if k != "low"}
    except Exception:
        pass


BADGE_CSS = "position:absolute;top:50%;transform:translateY(-50%);background:#E53935;color:#fff;border-radius:999px;min-width:22px;height:22px;line-height:22px;text-align:center;font-size:.72rem;font-weight:700;padding:0 6px;"
dyn = []
for si, (label, subs_) in enumerate(sections):
    is_act = label == ss.nav_sec
    plain = label.split("  ", 1)[-1]
    nbtn(plain, f"sec_{si}", is_act, label, subs_[0][1], icon=ICONS.get(plain))
    if len(subs_) > 1:
        dyn.append(f".st-key-sec_{si} button::after{{content:'{'⌄' if is_act else '›'}';position:absolute;right:14px;top:50%;transform:translateY(-50%);color:#8A94A6;font-size:1.15rem}}")
        sb = sum(BADGE.get(k_, 0) for _, k_ in subs_)
        if sb and not is_act:
            dyn.append(f".st-key-sec_{si} button::before{{content:'{sb}';right:38px;{BADGE_CSS}}}.st-key-sec_{si} button{{padding-right:70px}}")
    if is_act and len(subs_) > 1:  # tanlangan bo'lim tagida ichki bo'limlar ochiladi
        try:
            box = st.sidebar.container(key=f"subs_{si}")
        except Exception:
            box = st.sidebar.container()
        for ki, (nm, k_) in enumerate(subs_):
            nbtn(nm, f"sub_{si}_{ki}", k_ == ss.nav_sub, label, k_, host=box)
            if BADGE.get(k_):
                dyn.append(f".st-key-sub_{si}_{ki} button::after{{content:'{BADGE[k_]}';right:10px;{BADGE_CSS}}}")
if dyn:
    st.markdown("<style>" + "".join(dyn) + "</style>", unsafe_allow_html=True)
st.sidebar.markdown(f"<div class='ucard'><div class='av'>👤</div><div><b>{html.escape(str(user['name']))}</b><br><span>{ROLES[user['role']]}</span></div></div>", unsafe_allow_html=True)
try:
    _out = st.sidebar.button("Chiqish", key="logout", icon=":material/logout:", width="stretch")
except Exception:
    _out = st.sidebar.button("🚪 Chiqish", key="logout")
if _out:
    log("Tizimdan chiqdi")
    try:
        save_cart()
        end_session()
    except Exception:
        pass
    ss.user, ss.cart, ss.cart_loaded = None, [], False
    st.rerun()
menu = ss.nav_sub
pk = next(n for n, k_ in sec_map[ss.nav_sec] if k_ == menu)
_low = BADGE_LOW
_bkchip = ""
if user["role"] == "admin":
    try:
        _bk = get_setting("last_backup", "")
        if not _bk or (datetime.now() - datetime.strptime(_bk, "%Y-%m-%d %H:%M:%S")).days >= 7:
            _bkchip = "<span class='chip warn'>💾 Zaxira nusxa oling</span>"
    except Exception:
        pass
_notif = sum(BADGE.values()) + _low
st.markdown(
    f"<div class='topbar'><div class='ttl'>{html.escape(pk)}</div><div class='chips'><span class='chip'>💱 1 $ = {RATE:,.0f} so'm</span><span class='chip'>📅 {now()[:10]}</span>"
    f"{_bkchip}<span class='chip{' warn' if _notif else ''}'>🔔 {_notif}</span>"
    f"<span class='chip'>👤 {html.escape(str(user['name']))} · {ROLES[user['role']]}</span></div></div>", unsafe_allow_html=True)


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
    L = [get_setting("shop_name", "SAV-DO").center(W), f"Chek №{sid}".center(W), str(s_["created"]), f"Kassir: {s_['cashier']}", "-" * W]
    for _, r in items.iterrows():
        L += [r["name"], f"{r['qty']:g} x {r['price']:,.0f} = {r['qty'] * r['price']:,.0f}".rjust(W)]
    L += ["-" * W, f"JAMI: {s_['total']:,.0f} so'm"]
    if paid > 0:
        if s_["payment"] == "Karta":
            num = (s_["acc_number"] or "")[-4:]
            L.append(f"Karta: {s_['acc_name'] or ''} {'**** ' + num if num else ''}".strip())
        elif s_["payment"] == "Hisob raqam":
            L.append(f"Hisob raqam: {s_['acc_name'] or ''} {s_['acc_number'] or ''}".strip())
        else:
            L.append(f"Naqd: {s_['acc_name'] or 'kassa'}")
        L.append(f"To'langan: {paid:,.0f} so'm")
        if s_["payment"] == "Naqd" and pd.notna(s_["given"]) and s_["given"] > 0:
            L += [f"Berildi: {s_['given']:,.0f} so'm", f"Qaytim: {(s_['change_amt'] or 0):,.0f} so'm"]
    if debt > 0:
        L += [f"NASIYA (qarz): {debt:,.0f} so'm", f"Mijoz: {s_['customer'] or ''}"]
    L += ["-" * W, "Xaridingiz uchun rahmat!".center(W)]
    return "\n".join(L)


def receipt_html(sid):
    s_ = q("""SELECT s.*, a.name AS acc_name, a.number AS acc_number FROM sales s
              LEFT JOIN accounts a ON a.id=s.account_id WHERE s.id=:i""", i=int(sid)).iloc[0]
    it = q("SELECT name,qty,price,base FROM sale_items WHERE sale_id=:i", i=int(sid))
    e = html.escape
    shop = get_setting("shop_name", "SAV-DO")
    inn = get_setting("shop_inn", "")
    head = "".join(f"<div class='mut'>{e(str(x))}</div>" for x in [get_setting("shop_addr", ""), get_setting("shop_phone", ""), ("STIR: " + inn) if inn else ""] if x)
    total = float(s_["total"])
    paid = float(s_["paid"]) if pd.notna(s_["paid"]) else (0.0 if s_["payment"] == "Nasiya" else total)
    debt = float(s_["debt"]) if pd.notna(s_["debt"]) else (total if s_["payment"] == "Nasiya" else 0.0)
    rows, saved = "", 0.0
    for r in it.itertuples():
        rows += f"<tr><td colspan='2' class='nm'>{e(str(r.name))}</td></tr><tr><td class='q'>{r.qty:g} × {r.price:,.0f}</td><td class='r'>{r.qty * r.price:,.0f}</td></tr>"
        if pd.notna(r.base) and r.base > r.price + 0.5:
            saved += (r.base - r.price) * r.qty
            rows += f"<tr><td colspan='2' class='sv'>🔥 Aksiya: {r.base:,.0f} → {r.price:,.0f}</td></tr>"
    meth, pay = str(s_["payment"]), ""
    if paid > 0:
        lab = meth if meth in ("Naqd", "Karta", "Hisob raqam") else "To'lov"
        acc = e(str(s_["acc_name"] or ""))
        num = str(s_["acc_number"] or "")
        if meth == "Karta" and num:
            acc += f" ····{e(num[-4:])}"
        elif meth == "Hisob raqam" and num:
            acc += f" {e(num)}"
        pay += f"<tr><td>{lab}{(' — ' + acc) if acc else ''}</td><td class='r'>{paid:,.0f}</td></tr>"
        if meth == "Naqd" and pd.notna(s_["given"]) and s_["given"] > 0:
            ch = float(s_["change_amt"]) if pd.notna(s_["change_amt"]) else 0.0
            pay += f"<tr><td>Mijoz berdi</td><td class='r'>{s_['given']:,.0f}</td></tr><tr><td>Qaytim</td><td class='r'>{ch:,.0f}</td></tr>"
    if debt > 0.5:
        dd = f" · muddat {e(str(s_['due_date']))}" if pd.notna(s_["due_date"]) and s_["due_date"] else ""
        pay += f"<tr class='dbt'><td>NASIYA — {e(str(s_['customer'] or ''))}{dd}</td><td class='r'>{debt:,.0f}</td></tr>"
    if saved > 0.5:
        pay += f"<tr class='sv'><td>Siz tejadingiz</td><td class='r'>{saved:,.0f}</td></tr>"
    qr = ""
    try:
        import segno
        qr = "<div class='c' style='margin-top:8px'>" + segno.make(f"{shop} | chek №{sid} | {s_['created']} | {total:,.0f} so'm", error="m").svg_inline(scale=3, border=1) + "</div>"
    except Exception:
        pass
    foot = get_setting("receipt_footer", "Xaridingiz uchun rahmat!")
    css = ("<style>body{margin:0;font-family:'Segoe UI',Arial,sans-serif}.rc{width:300px;margin:4px auto;padding:14px;background:#fff;border:1px solid #e3e6ee;border-radius:12px;font-size:13px;color:#111}"
           ".c{text-align:center}.shop{font-size:18px;font-weight:700;letter-spacing:.5px}.mut{color:#666;font-size:12px}table{width:100%;border-collapse:collapse}td{padding:2px 0;vertical-align:top}"
           ".r{text-align:right;white-space:nowrap;padding-left:8px}.nm{font-weight:600;padding-top:6px}.q{color:#444}.sv td,.sv{color:#c0392b;font-size:12px}hr{border:0;border-top:1px dashed #aaa;margin:8px 0}"
           ".tot td{font-size:17px;font-weight:700;padding:4px 0}.dbt td{color:#b45309;font-weight:600}svg{width:110px;height:110px}"
           "button{margin:10px auto 0;display:block;padding:7px 16px;border:0;border-radius:8px;background:#2F6BFF;color:#fff;cursor:pointer}@media print{button{display:none}.rc{border:0}}</style>")
    body = (f"<div class='rc'><div class='c'><div class='shop'>{e(shop)}</div>{head}<div class='mut' style='margin-top:4px'>Chek №{int(sid)} · {e(str(s_['created']))}</div>"
            f"<div class='mut'>Kassir: {e(str(s_['cashier']))}</div></div><hr><table>{rows}</table><hr><table><tr class='tot'><td>JAMI</td><td class='r'>{total:,.0f} so'm</td></tr>{pay}</table><hr>"
            f"<div class='c mut'>{e(foot)}</div>{qr}<button onclick='window.print()'>🖨️ Chop etish</button></div>")
    return css + body, 330 + 44 * len(it) + (130 if qr else 0) + (28 if debt > 0.5 else 0) + (28 if saved > 0.5 else 0)


def show_receipt(sid):
    h, hh = receipt_html(sid)
    components.html(h, height=hh, scrolling=True)
    st.download_button("⬇️ Chekni yuklab olish (.txt)", build_receipt(sid).encode("utf-8"), file_name=f"chek_{sid}.txt", key=f"dl_chek_{sid}")


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
    import_box(f"partners_{kind}", kind.lower() + "lar", pd.DataFrame({"Nomi": ["Namuna savdo"], "Telefon": ["+998901234567"]}), lambda df: imp_partners(df, kind))


def add_cart(p, code=None):
    for i in ss.cart:
        if i["id"] == int(p["id"]):
            i["qty"] += 1
            if code:
                i["codes"].append(code)
            return
    ss.cart.append({"id": int(p["id"]), "name": p["name"], "price": eff_price(p), "base": float(p["price"]), "qty": 1.0, "marked": bool(p["marked"]), "codes": [code] if code else []})


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


def hold_cart():
    if not ss.cart:
        return
    tot = sum(i["price"] * i["qty"] for i in ss.cart)
    ex("INSERT INTO held_sales (created,username,label,data,total) VALUES (:t,:u,:l,:d,:s)", t=now(), u=ss.user["username"],
       l=(ss.get("hold_lbl") or "").strip(), d=json.dumps(ss.cart, ensure_ascii=False, default=_jd), s=tot)
    log("Chek kutishga qo'yildi", m(tot))
    ss.cart, ss.hold_lbl = [], ""


def resume_held(hid):
    if ss.cart:
        ss.msg = ("warning", "Avval joriy savatni kutishga qo'ying yoki tozalang.")
        return
    r = q("SELECT data FROM held_sales WHERE id=:i", i=int(hid))
    if not r.empty:
        ss.cart = json.loads(r.iloc[0, 0])
        ex("DELETE FROM held_sales WHERE id=:i", i=int(hid))


def drop_held(hid):
    ex("DELETE FROM held_sales WHERE id=:i", i=int(hid))
    log("Kutayotgan chek o'chirildi", f"№{hid}")


def open_shift(u):
    r = q("SELECT * FROM shifts WHERE username=:u AND status='ochiq' ORDER BY id DESC LIMIT 1", u=u)
    return r.iloc[0] if not r.empty else None


if menu == "pos" and user["role"] == "kassir" and get_setting("shift_required", "1") == "1" and open_shift(user["username"]) is None:
    menu = "smena_needed"

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
            names = {int(r["id"]): f"{r['name']}   |   qoldiq: {r['stock']:g} {r['unit'] or ''}   |   {eff_price(r):,.0f} so'm" + ("   |   🔥 aksiya" if eff_price(r) < r["price"] else "") + ("   |   🏷️ markirovka" if r["marked"] else "")
                     for _, r in prods.iterrows()}
            pid = st.selectbox("🔍 Tovar (nomini yozib qidiring):", [None] + list(names), format_func=lambda x: "— tanlang —" if x is None else names[x])
            if pid:
                p = prods[prods["id"] == pid].iloc[0]
                incart = sum(i["qty"] for i in ss.cart if i["id"] == pid)
                a, b, c = st.columns(3)
                a.metric("Omborda", f"{p['stock']:g} {p['unit'] or ''}")
                b.metric("Narxi", m(eff_price(p)), delta=(f"-{p['price'] - eff_price(p):,.0f} aksiya" if eff_price(p) < p["price"] else None), delta_color="inverse")
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
                                ss.cart.append({"id": int(pid), "name": p["name"], "price": eff_price(p), "base": float(p["price"]), "qty": qty, "marked": False, "codes": []})
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
            pid_c, cname, due, due_date = None, "", total, None
            if nas:
                custs = q("SELECT id,name FROM partners WHERE kind='Mijoz' ORDER BY name")
                pid_c = pick("Mijoz:", custs, "id", "name", none="— tanlang —")
                nn = st.text_input("yoki yangi mijoz ismi")
                if nn.strip() and pid_c is None:
                    cname = nn.strip()
                due = st.number_input("Hozir to'lanadigan summa (qolgani nasiya):", min_value=0.0, max_value=total, value=0.0, step=1000.0)
                st.markdown(f"Nasiya (qarz): **{m(total - due)}**")
                due_date = st.date_input("📅 Qarz to'lash muddati", value=date.today() + timedelta(days=14))
            method, acc, given, change, blocked = None, None, 0.0, 0.0, False
            if due > 0:
                method = st.radio("To'lov turi:", ["Naqd", "Karta", "Hisob raqam"], horizontal=True)
                kind = {"Naqd": "Naqd kassa", "Karta": "Karta", "Hisob raqam": "Bank hisobi"}[method]
                ak = accs[accs["kind"] == kind].copy() if not accs.empty else accs
                if ak.empty:
                    st.error(f"«{kind}» hisobi yo'q. Bank va kassa → Hisoblar da qo'shing.")
                    blocked = True
                else:
                    ak["label"] = ak.apply(lambda r: r["name"] + (f" (**** {r['number'][-4:]})" if method == "Karta" and r["number"] else (f" ({r['number']})" if method == "Hisob raqam" and r["number"] else "")), axis=1)
                    acc = pick({"Naqd": "Naqd kassa:", "Karta": "Qaysi karta:", "Hisob raqam": "Qaysi hisob raqamga tushdi:"}[method], ak, "id", "label")
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
                            sid = c.execute(text("""INSERT INTO sales (created,cashier,payment,customer,total,partner_id,paid,debt,given,change_amt,account_id,due_date)
                                                    VALUES (:t,:u,:p,:c,:s,:pi,:pd,:db,:g,:ch,:a,:dd) RETURNING id"""),
                                            {"t": now(), "u": user["username"], "p": method or "Nasiya", "c": cn, "s": total, "pi": pid_c, "pd": due, "db": debt,
                                             "g": given if method == "Naqd" else 0, "ch": max(change, 0) if method == "Naqd" else 0, "a": acc,
                                             "dd": str(due_date) if nas and due_date else None}).scalar()
                            for i in ss.cart:
                                r = c.execute(text("UPDATE products SET stock = stock - :q WHERE id=:i AND stock >= :q"), {"q": i["qty"], "i": i["id"]})
                                if r.rowcount == 0:
                                    raise ValueError(f"{i['name']}: omborda yetarli emas")
                                for code in i["codes"]:
                                    r = c.execute(text("UPDATE mark_codes SET status='sotilgan', sale_id=:s WHERE code=:c AND product_id=:p AND status='omborda'"),
                                                  {"s": sid, "c": code, "p": i["id"]})
                                    if r.rowcount == 0:
                                        raise ValueError(f"{i['name']}: kod omborda yo'q")
                                c.execute(text("INSERT INTO sale_items (sale_id,product_id,name,qty,price,codes,base) VALUES (:s,:p,:n,:q,:pr,:cd,:bs)"),
                                          {"s": sid, "p": i["id"], "n": i["name"], "q": i["qty"], "pr": i["price"], "cd": ",".join(i["codes"]), "bs": i.get("base", i["price"])})
                            if debt > 0:
                                c.execute(text("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,:d,'Nasiya savdo',:u)"),
                                          {"t": now(), "p": pid_c, "a": debt, "d": f"Sotuv №{sid}", "u": user["username"]})
                            if due > 0:  # kassaga faqat sof tushum (qaytim ayirilgan) yoziladi
                                c.execute(text("INSERT INTO cash_moves (created,account_id,amount,doc,note,user_name) VALUES (:t,:a,:s,:d,:n,:u)"),
                                          {"t": now(), "a": acc, "s": due, "d": f"Sotuv №{sid}", "n": f"Savdo tushumi ({method})", "u": user["username"]})
                        ss.receipt = sid
                        log("Sotuv", f"№{sid}, {m(total)}, {method or 'Nasiya'}" + (f", nasiya {m(debt)}" if debt > 0 else ""))
                        ss.cart = []
                        st.rerun()
                    except Exception as e:
                        st.error(f"Xato: {e}")
            st.text_input("Kutish uchun izoh (mijoz ismi, ixtiyoriy)", key="hold_lbl")
            b1, b3, b2 = st.columns(3)
            b3.button("⏸ Kutishga qo'yish", on_click=hold_cart)
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
        _adm = user["role"] == "admin"
        hd = q("SELECT id,created,username,label,total FROM held_sales" + ("" if _adm else " WHERE username=:u") + " ORDER BY id DESC", **({} if _adm else {"u": user["username"]}))
        if not hd.empty:
            st.markdown(f"**⏸ Kutayotgan cheklar ({len(hd)})**")
            for r in hd.itertuples():
                x1, x2, x3 = st.columns([4, 1.6, 1])
                x1.markdown(f"**{r.label or 'Izohsiz'}** · {str(r.created)[11:16]} · {m(r.total)}" + (f" · {r.username}" if _adm else ""))
                x2.button("▶️ Olish", key=f"hr_{r.id}", on_click=resume_held, args=(int(r.id),))
                x3.button("🗑", key=f"hd_{r.id}", on_click=drop_held, args=(int(r.id),))
        if ss.receipt:
            st.markdown("**Oxirgi chek:**")
            show_receipt(ss.receipt)

elif menu == "smena_needed":
    st.warning("Sotuvni boshlash uchun avval smenani oching (kassadagi boshlang'ich pulni kiriting).")
    st.button("▶️ Smenani ochish", type="primary", on_click=go, args=(ss.nav_sec, "smena"))

elif menu == "smena":
    sh = open_shift(user["username"])
    if user["role"] == "admin":
        with st.expander("⚙️ Smena va xavfsizlik sozlamalari (administrator)"):
            st.checkbox("Kassirlar sotuvdan oldin smenani ochishi shart", value=get_setting("shift_required", "1") == "1", key="shreq",
                        on_change=lambda: set_setting("shift_required", "1" if ss.shreq else "0"))
            st.number_input("Harakatsizlikdan keyin avtomatik chiqish (daqiqa)", min_value=5, max_value=480, step=5, key="idlemin",
                            value=int(get_setting("idle_min", "30") or 30), on_change=lambda: set_setting("idle_min", str(int(ss.idlemin))))
    accs = acc_balances()
    cash_accs = accs[accs["kind"] == "Naqd kassa"]
    if sh is None:
        st.info("🔴 Smena yopiq. Sotuvni boshlash uchun smenani oching.")
        if cash_accs.empty:
            st.warning("Naqd kassa yo'q. Buxgalteriya → Kassalar bo'limida «Naqd kassa» qo'shing.")
        else:
            st.caption("Kassadagi hisob bo'yicha pul: " + ", ".join(f"{r['name']} — {m(r['balance'])}" for _, r in cash_accs.iterrows()))
            with st.form("sh_open"):
                acc = pick("Qaysi naqd kassada ishlaysiz:", cash_accs, "id", "name")
                oc = st.number_input("Kassadagi boshlang'ich pul (so'm): sanab chiqing", min_value=0.0, step=1000.0)
                if st.form_submit_button("▶️ Smenani ochish", type="primary"):
                    ex("INSERT INTO shifts (username,opened,account_id,open_cash,status) VALUES (:u,:t,:a,:o,'ochiq')", u=user["username"], t=now(), a=int(acc), o=oc)
                    log("Smena ochildi", f"boshlang'ich {m(oc)}")
                    st.rerun()
    else:
        t0, acc_id = sh["opened"], int(sh["account_id"])
        mvs = float(q("SELECT COALESCE(SUM(amount),0) FROM cash_moves WHERE account_id=:a AND user_name=:u AND created >= :t", a=acc_id, u=user["username"], t=t0).iloc[0, 0])
        expected = float(sh["open_cash"] or 0) + mvs
        sl = q(SALES_SQL + " WHERE cashier=:u AND created >= :t", u=user["username"], t=t0)
        st.success(f"🟢 Smena ochiq: {t0}")
        k1, k2, k3, k4 = st.columns(4)
        k1.metric("Boshlang'ich pul", m(float(sh["open_cash"] or 0)))
        k2.metric("Cheklar", len(sl))
        k3.metric("Savdo summasi", m(sl["total"].sum()))
        k4.metric("Kassada bo'lishi kerak (naqd)", m(expected))
        with st.form("sh_close"):
            counted = st.number_input("Kassada sanalgan pul (so'm)", min_value=0.0, step=1000.0, value=float(max(expected, 0)))
            others = accs[accs["id"] != acc_id]
            tgt = pick("Katta kassaga / hisobga topshirish (ixtiyoriy):", others, "id", "name", none="— topshirilmaydi —") if not others.empty else None
            hand = st.number_input("Topshiriladigan summa (so'm)", min_value=0.0, step=1000.0)
            note = st.text_input("Izoh")
            if st.form_submit_button("⏹ Smenani yopish", type="primary"):
                diff = counted - expected
                if hand > counted:
                    st.error("Topshiriladigan summa sanalgan puldan ko'p bo'lishi mumkin emas.")
                elif hand > 0 and tgt is None:
                    st.error("Qaysi hisobga topshirilishini tanlang.")
                else:
                    t = now()
                    sid_ = int(sh["id"])
                    with ENGINE.begin() as c:
                        c.execute(text("UPDATE shifts SET closed=:t, expected=:e, counted=:c, diff=:d, handed=:h, note=:n, status='yopiq' WHERE id=:i"),
                                  {"t": t, "e": expected, "c": counted, "d": diff, "h": hand, "n": note, "i": sid_})
                        mvq = "INSERT INTO cash_moves (created,account_id,amount,doc,note,user_name) VALUES (:t,:a,:s,:d,:n,:u)"
                        if abs(diff) > 0.5:
                            c.execute(text(mvq), {"t": t, "a": acc_id, "s": diff, "d": f"Smena farqi №{sid_}", "n": "Sanash farqi", "u": user["username"]})
                        if hand > 0:
                            c.execute(text(mvq), {"t": t, "a": acc_id, "s": -hand, "d": f"Smena topshirish №{sid_}", "n": note, "u": user["username"]})
                            c.execute(text(mvq), {"t": t, "a": int(tgt), "s": hand, "d": f"Smena topshirish №{sid_}", "n": note, "u": user["username"]})
                    log("Smena yopildi", f"kutilgan {m(expected)}, sanalgan {m(counted)}, farq {m(diff)}")
                    ss.imp_msg = f"✅ Smena yopildi. Farq: {m(diff)} ({'kam' if diff < -0.5 else 'ortiqcha' if diff > 0.5 else 'farq yo`q'})."
                    st.rerun()
    if ss.get("imp_msg"):
        st.success(ss.imp_msg)
        ss.imp_msg = None
    st.markdown("##### Smenalar tarixi")
    adm_ = user["role"] == "admin"
    hs = q("SELECT s.id, s.username, s.opened, s.closed, a.name AS acc, s.open_cash, s.expected, s.counted, s.diff, s.handed, s.status FROM shifts s "
           "LEFT JOIN accounts a ON a.id=s.account_id" + ("" if adm_ else " WHERE s.username=:u") + " ORDER BY s.id DESC LIMIT 200", **({} if adm_ else {"u": user["username"]}))
    show_df(hs, {"id": "№", "username": "Kassir", "opened": "Ochildi", "closed": "Yopildi", "acc": "Kassa", "open_cash": "Boshlang'ich", "expected": "Kutilgan",
                 "counted": "Sanalgan", "diff": "Farq", "handed": "Topshirilgan", "status": "Holati"},
            color=lambda r: "#FDECEC" if pd.notna(r["Farq"]) and r["Farq"] < -0.5 else ("#FFF8E1" if pd.notna(r["Farq"]) and r["Farq"] > 0.5 else ""))

elif menu == "sotuvlar":
    sales = q("SELECT id,created,cashier,payment,customer,total,COALESCE(paid, CASE WHEN payment='Nasiya' THEN 0 ELSE total END) AS paid_, COALESCE(debt, CASE WHEN payment='Nasiya' THEN total ELSE 0 END) AS debt_ FROM sales ORDER BY id DESC LIMIT 200")
    show_df(sales, {"id": "№", "created": "Vaqt", "cashier": "Kassir", "payment": "To'lov", "customer": "Mijoz", "total": "Summa", "paid_": "To'langan", "debt_": "Nasiya (qarz)"})
    if not sales.empty:
        sid = st.selectbox("Chek tarkibi:", sales["id"].tolist())
        show_df(q("SELECT name,qty,price,codes FROM sale_items WHERE sale_id=:s", s=int(sid)), {"name": "Tovar", "qty": "Miqdor", "price": "Narx", "codes": "Markirovka kodlari"})
        show_receipt(sid)

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
                if newp > 0 and user["role"] == "admin":
                    ex("UPDATE products SET price=:p WHERE id=:i", p=newp, i=int(pid))
                    log("Narx o'zgardi", f"{old['name']}: {old['price']:,.0f} → {newp:,.0f}")
                elif newp > 0:
                    ex("INSERT INTO price_requests (created,user_name,product_id,old_price,new_price,status) VALUES (:t,:u,:p,:o,:n,'kutilmoqda')",
                       t=now(), u=user["username"], p=int(pid), o=float(old["price"] or 0), n=newp)
                    log("Narx o'zgartirish so'rovi", f"{old['name']}: {old['price']:,.0f} → {newp:,.0f}")
                    st.info("Narx o'zgartirish so'rovi administratorga yuborildi.")
                if newb.strip():
                    ex("UPDATE products SET barcode=:b WHERE id=:i", b=newb.strip(), i=int(pid))
                    log("Shtrix-kod o'zgardi", old["name"])
                if arch and user["role"] != "admin":
                    st.warning("Arxivga olishni faqat administrator bajaradi.")
                elif arch:
                    ex("UPDATE products SET active=0 WHERE id=:i", i=int(pid))
                    log("Tovar arxivga olindi", old["name"])
                st.success("Saqlandi.")
    with top:
        t = q("SELECT * FROM products WHERE active=1 ORDER BY name")
        t["marked"] = t["marked"].map(lambda x: "Ha" if x else "")
        t["barcode"] = t["barcode"].fillna("")
        show_df(t[["id", "name", "unit", "barcode", "marked", "price", "cost", "stock"]], {**RN_P, "marked": "Markirovka"})

    import_box("tovar", "tovarlar", pd.DataFrame({"Nomi": ["Coca-Cola 1.5L"], "Birlik": ["dona"], "Shtrix-kod": ["4780000000017"], "Markirovka": ["Yo'q"], "Tan narxi": [9000], "Sotuv narxi": [12000]}), imp_products)

elif menu == "kirim":
    NEW = -1
    if ss.get("kirim_ok"):
        st.success(ss.kirim_ok)
        ss.kirim_ok = None
    sup = q("SELECT id,name FROM partners WHERE kind='Yetkazib beruvchi' ORDER BY name")
    prods = q("SELECT * FROM products WHERE active=1 ORDER BY name")
    snames, pnames = dict(zip(sup["id"], sup["name"])), dict(zip(prods["id"], prods["name"]))

    import_box("kirim", "kirim qatorlari", pd.DataFrame({"Tovar nomi": ["Coca-Cola 1.5L"], "Shtrix-kod": [""], "Soni": [24], "Tan narxi": [9000], "Sotuv narxi": [12000], "Birlik": ["dona"]}), imp_kirim)
    L, R = st.columns([3, 2], gap="large")
    with L:
        with st.container(border=True):
            st.markdown("##### 1️⃣ Yetkazib beruvchi (kimdan keldi?)")
            sp = st.selectbox("Yetkazib beruvchi", [None] + sup["id"].tolist() + [NEW], key="rc_sup",
                              format_func=lambda x: "— yetkazib beruvchisiz —" if x is None else ("➕ Yangi yetkazib beruvchi (nomini yozaman)" if x == NEW else snames[x]))
            new_sup = st.text_input("Yangi yetkazib beruvchi nomi", key="rc_newsup").strip() if sp == NEW else ""

            st.markdown("##### 2️⃣ Tovar va nechta keldi")
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

    with R:
        with st.container(border=True):
            st.markdown("##### 🧺 Kirim ro'yxati")
            if ss.rc:
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
                                    c.execute(text("INSERT INTO receipt_items (receipt_id,product_id,name,qty,cost,price) VALUES (:r,:p,:n,:q,:c,:pr)"),
                                              {"r": rid, "p": pid_, "n": r["name"], "q": r["qty"], "c": r["cost"], "pr": r["price"]})
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

            else:
                st.info("Ro'yxat bo'sh. Chapdan tovar qo'shing yoki Excel'dan yuklang.")

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
    st0 = q("""SELECT p.id, p.name, p.unit, p.marked, p.stock, p.cost, p.price, p.barcode,
        COALESCE((SELECT SUM(ri.qty) FROM receipt_items ri WHERE ri.product_id=p.id),0) AS received,
        COALESCE((SELECT SUM(si.qty) FROM sale_items si WHERE si.product_id=p.id),0) AS sold,
        (SELECT pa.name FROM receipt_items ri JOIN receipts r ON r.id=ri.receipt_id LEFT JOIN partners pa ON pa.id=r.partner_id
         WHERE ri.product_id=p.id ORDER BY r.id DESC, ri.id DESC LIMIT 1) AS supplier
        FROM products p WHERE p.active=1 ORDER BY p.name""")
    if st0.empty:
        st.info("Omborda tovar yo'q. Xaridlar → Omborga kirim orqali tovar kiriting.")
    else:
        c1, c2, c3, c4 = st.columns([2, 1, 1, 1])
        s_ = c1.text_input("🔍 Tovar nomi, yetkazib beruvchi yoki shtrix-kod")
        mk = c2.selectbox("Turi", ["Hammasi", "Markirovkali", "Oddiy"])
        only = c3.checkbox("Faqat qoldig'i borlar")
        low = c4.checkbox("Kam qoldiq (≤ 5)")
        v = st0
        if s_:
            hay = v["name"].fillna("") + " " + v["supplier"].fillna("") + " " + v["barcode"].fillna("")
            v = v[hay.str.contains(s_, case=False, regex=False)]
        if mk != "Hammasi":
            v = v[v["marked"] == (1 if mk == "Markirovkali" else 0)]
        if only:
            v = v[v["stock"] > 0]
        if low:
            v = v[v["stock"] <= 5]
        a, b, c = st.columns(3)
        a.metric("Tovar turlari", len(v))
        b.metric("Qoldiq bahosi (kelgan narxda)", m((v["stock"] * v["cost"].fillna(0)).sum()))
        c.metric("Qoldiq bahosi (sotish narxida)", m((v["stock"] * v["price"].fillna(0)).sum()))
        v = v.copy()
        v["turi"] = v["marked"].map(lambda x: "🏷️ Markirovkali" if x else "Oddiy")
        v["summa"] = v["stock"] * v["cost"].fillna(0)
        v["supplier"] = v["supplier"].fillna("—")
        show_df(v[["name", "supplier", "turi", "unit", "received", "sold", "stock", "cost", "price", "summa"]],
                {"name": "Tovar nomi", "supplier": "Yetkazib beruvchi", "turi": "Markirovka", "unit": "Birlik", "received": "Kelgan soni",
                 "sold": "Sotilgan", "stock": "Qoldiq", "cost": "Kelgan narxi", "price": "Sotish narxi", "summa": "Qoldiq summasi"},
                color=lambda r: "#FFC9C9" if r["Qoldiq"] <= 0 else ("#FFF3B0" if r["Qoldiq"] <= 5 else ("#D6E8FF" if "Markirovkali" in r["Markirovka"] else None)))
        st.caption("🟥 qoldiq yo'q   🟨 kam qoldiq (≤ 5)   🟦 markirovkali tovar")
        st.markdown("**Tovar harakati (kirim / sotuv)**")
        pid = pick("Tovar:", st0, "id", "name", key="mv")
        mv = q("""SELECT r.created AS vaqt, 'Kirim №' || r.id AS hujjat, ri.qty AS miqdor FROM receipt_items ri JOIN receipts r ON r.id=ri.receipt_id WHERE ri.product_id=:p
                  UNION ALL
                  SELECT s.created, 'Sotuv №' || s.id, -si.qty FROM sale_items si JOIN sales s ON s.id=si.sale_id WHERE si.product_id=:p
                  UNION ALL SELECT created, 'Yetkazib beruvchiga qaytarish №' || id, -qty FROM supplier_returns WHERE product_id=:p
                  UNION ALL SELECT created, 'Inventar / hisobdan chiqarish: ' || COALESCE(reason, ''), qty FROM stock_adj WHERE product_id=:p
                  ORDER BY 1 DESC""", p=int(pid))
        show_df(mv, {"vaqt": "Vaqt", "hujjat": "Hujjat", "miqdor": "Miqdor (+kirim / −sotuv)"})

elif menu == "jurnal":
    j = q("""SELECT r.created, r.id AS rid, pa.name AS supplier, ri.name, p.marked, ri.qty, p.unit, ri.cost, COALESCE(ri.price, p.price) AS price, ri.qty*ri.cost AS jami
             FROM receipt_items ri JOIN receipts r ON r.id=ri.receipt_id LEFT JOIN partners pa ON pa.id=r.partner_id
             LEFT JOIN products p ON p.id=ri.product_id ORDER BY r.id DESC, ri.id DESC LIMIT 2000""")
    if j.empty:
        st.info("Hali kirim yo'q. Xaridlar → Omborga kirim orqali birinchi kirimni kiriting.")
    else:
        j["supplier"] = j["supplier"].fillna("—")
        c1, c2 = st.columns(2)
        s_ = c1.text_input("🔍 Tovar nomi bo'yicha")
        sups = ["Hammasi"] + sorted(j["supplier"].unique().tolist())
        sp_ = c2.selectbox("Yetkazib beruvchi", sups)
        if s_:
            j = j[j["name"].str.contains(s_, case=False, na=False, regex=False)]
        if sp_ != "Hammasi":
            j = j[j["supplier"] == sp_]
        j = j.copy()
        j["turi"] = j["marked"].map(lambda x: "🏷️ Markirovkali" if x == 1 else "Oddiy")
        a, b = st.columns(2)
        a.metric("Kirim qatorlari", len(j))
        b.metric("Kirim summasi", m(j["jami"].sum()))
        show_df(j[["created", "rid", "supplier", "name", "turi", "qty", "unit", "cost", "price", "jami"]],
                {"created": "Sana", "rid": "Kirim №", "supplier": "Yetkazib beruvchi", "name": "Tovar nomi", "turi": "Markirovka", "qty": "Soni",
                 "unit": "Birlik", "cost": "Kelgan narxi", "price": "Sotish narxi", "jami": "Jami"})

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
        ul = q("""SELECT u.username, u.full_name, u.role, u.active,
            COALESCE((SELECT COUNT(*) FROM sales s WHERE s.cashier=u.username AND substr(s.created,1,10)=:d),0) AS ch_bugun,
            COALESCE((SELECT SUM(total) FROM sales s WHERE s.cashier=u.username AND substr(s.created,1,10)=:d),0) AS bugun,
            COALESCE((SELECT SUM(total) FROM sales s WHERE s.cashier=u.username AND substr(s.created,1,7)=:mo),0) AS oy,
            COALESCE((SELECT COUNT(*) FROM receipts r WHERE r.user_name=u.username AND substr(r.created,1,7)=:mo),0) AS kirim_oy
            FROM users u ORDER BY u.id""", d=now()[:10], mo=now()[:7])
        ul["role"] = ul["role"].map(ROLES)
        ul["active"] = ul["active"].map(lambda x: "Faol" if x else "O'chirilgan")
        st.markdown("##### 👥 Xodimlar ro'yxati va ko'rsatkichlari")
        show_df(ul, {"username": "Login", "full_name": "Ism-familiya", "role": "Rol", "active": "Holati", "ch_bugun": "Bugungi cheklar",
                     "bugun": "Bugungi savdo", "oy": "Shu oy savdo", "kirim_oy": "Shu oy kirim hujjatlari"})

elif menu == "audit":
    s = st.text_input("Foydalanuvchi yoki amal bo'yicha qidirish")
    a = q("SELECT created,user_name,action,details FROM audit ORDER BY id DESC LIMIT 500")
    if s:
        a = a[a.apply(lambda r: s.lower() in f"{r['user_name']} {r['action']} {r['details']}".lower(), axis=1)]
    show_df(a, {"created": "Vaqt", "user_name": "Kim", "action": "Amal", "details": "Tafsilot"})

elif menu == "mijoztolov":
    dd, accs = debtors(), acc_balances()
    if dd.empty:
        st.info("Qarzdor mijoz yo'q.")
    else:
        show_df(dd[["name", "phone", "balance", "overdue", "notdue", "oldest"]],
                {"name": "Mijoz", "phone": "Telefon", "balance": "Jami qarz", "overdue": "Muddati o'tgan", "notdue": "Muddati o'tmagan", "oldest": "Eng eski muddat"},
                color=lambda r: "#FFC9C9" if r["Muddati o'tgan"] > 0.5 else None)
        if accs.empty:
            st.warning("Avval Buxgalteriya → Kassalar (hisoblar) da hisob qo'shing.")
        else:
            with st.form("mt", clear_on_submit=True):
                cid = pick("Mijoz:", dd, "id", "name")
                amt = st.number_input("To'lov summasi (so'm)", min_value=0.0, step=1000.0)
                acc = pick("Qaysi hisobga tushdi (kassa / karta):", accs, "id", "name")
                note = st.text_input("Izoh")
                if st.form_submit_button("✅ To'lovni qabul qilish", type="primary"):
                    bal = float(dd.loc[dd["id"] == cid, "balance"].iloc[0])
                    if amt <= 0:
                        st.error("Summani kiriting.")
                    elif amt > bal + 0.5:
                        st.error(f"Mijozning qarzi {m(bal)}, undan ko'p qabul qilib bo'lmaydi.")
                    else:
                        t = now()
                        ex("INSERT INTO cash_moves (created,account_id,amount,partner_id,doc,note,user_name) VALUES (:t,:a,:s,:p,'Mijozdan to''lov',:n,:u)", t=t, a=int(acc), s=amt, p=int(cid), n=note, u=user["username"])
                        ex("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,'Mijozdan to''lov',:n,:u)", t=t, p=int(cid), a=-amt, n=note, u=user["username"])
                        log("Mijozdan to'lov", f"{dd.loc[dd['id'] == cid, 'name'].iloc[0]}: {m(amt)}")
                        st.success("To'lov qabul qilindi. Qarz kamaydi, hisobga pul tushdi.")

elif menu == "qaytarish":
    sl = q("SELECT id,created,customer,total,partner_id,COALESCE(debt, CASE WHEN payment='Nasiya' THEN total ELSE 0 END) AS debt_ FROM sales ORDER BY id DESC LIMIT 200")
    if sl.empty:
        st.info("Sotuvlar yo'q.")
    else:
        lab = {int(r.id): f"№{r.id} — {r.created} — {r.total:,.0f} so'm" + (f" — {r.customer}" if r.customer else "") for r in sl.itertuples()}
        sid = st.selectbox("Qaysi chekdan qaytariladi?", list(lab), format_func=lambda x: lab[x])
        srow = sl[sl["id"] == sid].iloc[0]
        items = q("SELECT id,product_id,name,qty,price,codes,COALESCE(returned,0) AS returned FROM sale_items WHERE sale_id=:s", s=int(sid))
        sold_codes = q("SELECT code,product_id FROM mark_codes WHERE sale_id=:s AND status='sotilgan'", s=int(sid))
        accs = acc_balances()
        with st.form("ret"):
            picks = []
            for it in items.itertuples():
                left = it.qty - it.returned
                if it.codes:
                    avail = sold_codes.loc[sold_codes["product_id"] == it.product_id, "code"].tolist()
                    sel = st.multiselect(f"{it.name} (markirovkali): qaytariladigan kodlar", avail, key=f"rt_c_{it.id}")
                    picks.append((it, float(len(sel)), sel))
                elif left > 0:
                    qn = st.number_input(f"{it.name}: sotilgan {it.qty:g}, qaytarilgan {it.returned:g}", min_value=0.0, max_value=float(left), value=0.0, step=1.0, key=f"rt_q_{it.id}")
                    picks.append((it, qn, []))
                else:
                    st.caption(f"{it.name}: to'liq qaytarilgan")
            acc = pick("Pul qaysi hisobdan qaytariladi:", accs, "id", "name", none="— hisob —") if not accs.empty else None
            go_ = st.form_submit_button("↩️ Qaytarishni tasdiqlash", type="primary")
        if go_:
            refund = sum(qn * it.price for it, qn, _ in picks)
            reduce, bal = 0.0, 0.0
            if pd.notna(srow["partner_id"]):
                bal = float(q("SELECT COALESCE(SUM(amount),0) FROM ledger WHERE partner_id=:p", p=int(srow["partner_id"])).iloc[0, 0])
                reduce = min(refund, max(bal, 0.0), float(srow["debt_"]))
            cash_back = refund - reduce
            have = float(accs.loc[accs["id"] == acc, "balance"].iloc[0]) if acc is not None else 0.0
            if refund <= 0:
                st.error("Qaytariladigan tovar yoki kod tanlanmagan.")
            elif cash_back > 0.5 and acc is None:
                st.error("Pul qaytariladigan hisobni tanlang.")
            elif cash_back > 0.5 and cash_back > have + 0.5:
                st.error(f"Hisobda yetarli pul yo'q: {m(have)}")
            else:
                try:
                    t = now()
                    with ENGINE.begin() as c:
                        for it, qn, sel in picks:
                            if qn <= 0:
                                continue
                            c.execute(text("UPDATE products SET stock = stock + :q WHERE id=:p"), {"q": qn, "p": int(it.product_id)})
                            c.execute(text("UPDATE sale_items SET returned = COALESCE(returned,0) + :q WHERE id=:i"), {"q": qn, "i": int(it.id)})
                            for code in sel:
                                c.execute(text("UPDATE mark_codes SET status='omborda', sale_id=NULL WHERE code=:c AND sale_id=:s"), {"c": code, "s": int(sid)})
                        pid_ = int(srow["partner_id"]) if pd.notna(srow["partner_id"]) else None
                        if reduce > 0:
                            c.execute(text("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,:d,'Tovar qaytarildi',:u)"),
                                      {"t": t, "p": pid_, "a": -reduce, "d": f"Qaytarish (chek №{sid})", "u": user["username"]})
                        if cash_back > 0.5:
                            c.execute(text("INSERT INTO cash_moves (created,account_id,amount,partner_id,doc,note,user_name) VALUES (:t,:a,:s,:p,:d,'Pul qaytarildi',:u)"),
                                      {"t": t, "a": int(acc), "s": -cash_back, "p": pid_, "d": f"Qaytarish (chek №{sid})", "u": user["username"]})
                    log("To'lovni qaytarish", f"chek №{sid}: {m(refund)} (qarzdan {m(reduce)}, pul {m(cash_back)})")
                    st.success(f"Qaytarildi: {m(refund)}. Tovar omborga qaytdi.")
                except Exception as e:
                    st.error(f"Xato: {e}")

elif menu == "kontr":
    pb = partner_balances()
    pid = pick("Kontragent:", pb, "id", "name", none="Barchasi") if not pb.empty else None
    d = q("""SELECT k.created, p.name AS partner, a.name AS acc, k.doc, k.note, k.amount FROM cash_moves k
             JOIN partners p ON p.id=k.partner_id JOIN accounts a ON a.id=k.account_id""" + (" WHERE k.partner_id=:p" if pid else "") + " ORDER BY k.id DESC LIMIT 500",
          **({"p": int(pid)} if pid else {}))
    a, b = st.columns(2)
    a.metric("Kirim (bizga to'langan)", m(d.loc[d["amount"] > 0, "amount"].sum()))
    b.metric("Chiqim (biz to'lagan)", m(-d.loc[d["amount"] < 0, "amount"].sum()))
    show_df(d, {"created": "Vaqt", "partner": "Kontragent", "acc": "Hisob", "doc": "Hujjat", "note": "Izoh", "amount": "Summa (+kirim / −chiqim)"},
            color=lambda r: "#D8F5D0" if r["Summa (+kirim / −chiqim)"] > 0 else "#FFE0C9")

elif menu in ("qarz_o", "qarz_n"):
    dd = debtors()
    col = "overdue" if menu == "qarz_o" else "notdue"
    v = dd[dd[col] > 0.5] if not dd.empty else dd
    if v.empty:
        st.success("Bunday qarzdor yo'q.")
    else:
        st.metric("Jami summa", m(v[col].sum()))
        show_df(v[["name", "phone", "balance", "overdue", "notdue", "oldest"]],
                {"name": "Mijoz", "phone": "Telefon", "balance": "Jami qarz", "overdue": "Muddati o'tgan", "notdue": "Muddati o'tmagan", "oldest": "Eng eski muddat"},
                color=(lambda r: "#FFC9C9") if menu == "qarz_o" else None)
        st.caption("Qarz muddati nasiya savdoda belgilanadi. To'lovlar eng eski qarzdan boshlab yopiladi.")

elif menu == "narxsorov":
    adm = user["role"] == "admin"
    rq = q("""SELECT r.id, r.created, r.user_name, p.name, r.old_price, r.new_price, r.status, r.decided_by FROM price_requests r JOIN products p ON p.id=r.product_id"""
           + ("" if adm else " WHERE r.user_name=:u") + " ORDER BY r.id DESC LIMIT 300", **({} if adm else {"u": user["username"]}))
    show_df(rq, {"id": "№", "created": "Vaqt", "user_name": "Kim so'radi", "name": "Tovar", "old_price": "Eski narx", "new_price": "Yangi narx", "status": "Holati", "decided_by": "Qaror qildi"},
            color=lambda r: {"kutilmoqda": "#FFF3B0", "tasdiqlandi": "#D8F5D0", "rad etildi": "#FFC9C9"}.get(r["Holati"]))
    pend = rq[rq["status"] == "kutilmoqda"]
    if adm and not pend.empty:
        with st.form("pr"):
            rid = st.selectbox("So'rov №", pend["id"].tolist(), format_func=lambda x: f"№{x} — {pend.loc[pend['id'] == x, 'name'].iloc[0]}: {pend.loc[pend['id'] == x, 'old_price'].iloc[0]:,.0f} → {pend.loc[pend['id'] == x, 'new_price'].iloc[0]:,.0f}")
            dec = st.radio("Qaror", ["✅ Tasdiqlash", "❌ Rad etish"], horizontal=True)
            if st.form_submit_button("Saqlash", type="primary"):
                r = q("SELECT * FROM price_requests WHERE id=:i", i=int(rid)).iloc[0]
                ok_ = dec.startswith("✅")
                if ok_:
                    ex("UPDATE products SET price=:p WHERE id=:i", p=float(r["new_price"]), i=int(r["product_id"]))
                ex("UPDATE price_requests SET status=:s, decided_by=:u, decided_at=:t WHERE id=:i", s="tasdiqlandi" if ok_ else "rad etildi", u=user["username"], t=now(), i=int(rid))
                log("Narx so'rovi " + ("tasdiqlandi" if ok_ else "rad etildi"), f"№{rid}")
                st.success("Saqlandi. Sahifani yangilang.")

elif menu == "stat":
    c1, c2 = st.columns(2)
    d1 = c1.date_input("Boshlanish", value=date.today().replace(day=1), key="sd1")
    d2 = c2.date_input("Tugash", value=date.today(), key="sd2")
    a_, b_ = f"{d1} 00:00:00", f"{d2} 23:59:59"
    us = q("SELECT username, full_name, role, active FROM users ORDER BY id")
    sl = q(SALES_SQL + " WHERE created >= :a AND created <= :b", a=a_, b=b_)
    rc = q("SELECT user_name, COUNT(*) AS n, COALESCE(SUM(total),0) AS s FROM receipts WHERE created >= :a AND created <= :b GROUP BY user_name", a=a_, b=b_)
    sg = (sl.groupby("cashier").agg(cheklar=("id", "count"), summa=("total", "sum"), tushum=("paid_", "sum"), nasiya=("debt_", "sum"))
          if not sl.empty else pd.DataFrame(columns=["cheklar", "summa", "tushum", "nasiya"]))
    t = us.merge(sg, left_on="username", right_index=True, how="left").merge(rc, left_on="username", right_on="user_name", how="left")
    for c_ in ["cheklar", "summa", "tushum", "nasiya", "n", "s"]:
        t[c_] = pd.to_numeric(t[c_], errors="coerce").fillna(0)
    t["ortacha"] = (t["summa"] / t["cheklar"]).where(t["cheklar"] > 0, 0)
    t["xodim"] = t["full_name"].fillna("").where(t["full_name"].fillna("") != "", t["username"])
    t["rol"] = t["role"].map(ROLES)
    k1, k2, k3, k4 = st.columns(4)
    k1.metric("Jami savdo", m(t["summa"].sum()))
    k2.metric("Cheklar soni", int(t["cheklar"].sum()))
    k3.metric("Kirim summasi", m(t["s"].sum()))
    k4.metric("Faol xodimlar", int(us["active"].sum()))
    st.markdown("##### 👥 Kim qancha savdo qilgan va kim tovar kirim qilgan")
    show_df(t[["xodim", "username", "rol", "cheklar", "summa", "tushum", "nasiya", "ortacha", "n", "s"]],
            {"xodim": "Xodim", "username": "Login", "rol": "Rol", "cheklar": "Cheklar", "summa": "Savdo summasi", "tushum": "Tushum (kassaga)",
             "nasiya": "Nasiyaga", "ortacha": "O'rtacha chek", "n": "Kirim hujjatlari", "s": "Kirim summasi"})
    g1, g2 = st.columns(2)
    g1.markdown("**Savdo summasi (xodimlar kesimida)**")
    g1.bar_chart(t.set_index("xodim")["summa"])
    g2.markdown("**Kirim summasi (xodimlar kesimida)**")
    g2.bar_chart(t.set_index("xodim")["s"])
    st.markdown("---")
    who = st.selectbox("Xodim kartochkasi", us["username"].tolist(),
                       format_func=lambda u_: f"{t.loc[t['username'] == u_, 'xodim'].iloc[0]} ({u_})")
    mine = sl[sl["cashier"] == who]
    h1, h2 = st.columns(2)
    with h1:
        st.markdown("**Kunlik savdo**")
        if mine.empty:
            st.info("Bu davrda sotuv yo'q.")
        else:
            st.bar_chart(mine.assign(kun=mine["created"].str[:10]).groupby("kun")["total"].sum())
            show_df(mine[["id", "created", "payment", "customer", "total"]].head(100), {"id": "Chek №", "created": "Vaqt", "payment": "To'lov", "customer": "Mijoz", "total": "Summa"})
    with h2:
        st.markdown("**Kirim qilgan tovarlari**")
        ki = q("""SELECT ri.name, SUM(ri.qty) AS qty, SUM(ri.qty*ri.cost) AS sm FROM receipt_items ri JOIN receipts r ON r.id=ri.receipt_id
                  WHERE r.user_name=:u AND r.created >= :a AND r.created <= :b GROUP BY ri.name ORDER BY sm DESC""", u=who, a=a_, b=b_)
        if ki.empty:
            st.info("Bu davrda kirim yo'q.")
        else:
            show_df(ki, {"name": "Tovar", "qty": "Jami soni", "sm": "Summa"})
            kd = q("""SELECT r.id, r.created, pa.name AS partner, r.total, r.paid FROM receipts r LEFT JOIN partners pa ON pa.id=r.partner_id
                      WHERE r.user_name=:u AND r.created >= :a AND r.created <= :b ORDER BY r.id DESC LIMIT 100""", u=who, a=a_, b=b_)
            show_df(kd, {"id": "Kirim №", "created": "Vaqt", "partner": "Yetkazib beruvchi", "total": "Summa", "paid": "To'langan"})

elif menu == "zaxira":
    from sqlalchemy import inspect as _insp
    st.markdown("Barcha ma'lumotlar bitta Excel fayliga yig'iladi (har bir jadval alohida varaqda). Parollar (xesh) faylga kiritilmaydi. "
                "Faylni xavfsiz joyda (Google Drive, flesh-xotira) saqlang. **Kamida haftada bir marta oling.**")
    st.caption(f"Oxirgi zaxira: {get_setting('last_backup', '') or 'hali olinmagan'}")
    if st.button("📦 Zaxira nusxa tayyorlash", type="primary"):
        buf, n = io.BytesIO(), 0
        with pd.ExcelWriter(buf, engine="openpyxl") as w:
            for t in sorted(_insp(ENGINE).get_table_names()):
                with ENGINE.connect() as c:
                    d = pd.read_sql(text(f"SELECT * FROM {t}"), c)
                if t == "users" and "pw" in d.columns:
                    d = d.drop(columns=["pw"])
                d.to_excel(w, sheet_name=t[:31], index=False)
                n += 1
        ss.backup_bytes = buf.getvalue()
        set_setting("last_backup", now())
        log("Zaxira nusxa olindi", f"{n} ta jadval")
        st.success(f"{n} ta jadval yig'ildi. Pastdagi tugma bilan yuklab oling.")
    if ss.get("backup_bytes"):
        st.download_button("⬇️ Zaxira faylini yuklab olish (.xlsx)", ss.backup_bytes, file_name=f"savdo_zaxira_{now()[:10]}.xlsx", mime=XLSX)

elif menu == "kurs":
    with st.form("kurs"):
        v = st.number_input("1 AQSh dollari = ... so'm", min_value=1.0, value=RATE, step=10.0)
        if st.form_submit_button("Saqlash", type="primary"):
            set_setting("usd_rate", v)
            log("Valyuta kursi o'zgardi", f"{v:,.0f}")
            st.success("Saqlandi. Sahifa yangilanganda sarlavhada ko'rinadi.")

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
    g, h, i = st.columns(3)
    _d = debtors()
    g.metric("Muddati o'tgan qarzdorlar", int((_d["overdue"] > 0.5).sum()) if not _d.empty else 0)
    h.metric("Narx so'rovlari (kutmoqda)", int(q("SELECT COUNT(*) FROM price_requests WHERE status='kutilmoqda'").iloc[0, 0]))
    i.metric("Hisoblardagi pul ($)", f"$ {ab['balance'].sum() / RATE:,.0f}" if not ab.empty else "$ 0")

    _sl = q("SELECT created, total, payment FROM sales WHERE created >= :d", d=str(date.today() - timedelta(days=13)))
    if not _sl.empty:
        st.markdown("**Oxirgi 14 kunlik savdo (so'm)**")
        _idx = [str(date.today() - timedelta(days=i)) for i in range(13, -1, -1)]
        st.bar_chart(_sl.assign(kun=_sl["created"].str[:10]).groupby("kun")["total"].sum().reindex(_idx, fill_value=0))
        g1, g2 = st.columns(2)
        _top = q("""SELECT si.name, SUM(si.qty*si.price) AS sm FROM sale_items si JOIN sales s ON s.id=si.sale_id
                    WHERE s.created >= :d GROUP BY si.name ORDER BY sm DESC LIMIT 7""", d=str(date.today() - timedelta(days=29)))
        g1.markdown("**Eng ko'p sotilgan tovarlar (30 kun)**")
        g1.bar_chart(_top.set_index("name")["sm"])
        g2.markdown("**To'lov turlari (14 kun)**")
        g2.bar_chart(_sl.groupby("payment")["total"].sum())

elif menu == "aksiya":
    prods = q("SELECT id,name,price FROM products WHERE active=1 ORDER BY name")
    top = st.container()
    if prods.empty:
        st.info("Avval tovar qo'shing.")
    else:
        with st.form("promo", clear_on_submit=True):
            st.markdown("**Yangi aksiya**")
            pid = pick("Tovar:", prods, "id", "name")
            kind = st.radio("Aksiya turi:", ["foiz", "narx"], horizontal=True, format_func=lambda x: "Chegirma (%)" if x == "foiz" else "Aksiya narxi (so'm)")
            val = st.number_input("Qiymat (foiz yoki so'm)", min_value=0.0, step=1.0)
            c1, c2 = st.columns(2)
            d1 = c1.date_input("Boshlanish", value=date.today())
            d2 = c2.date_input("Tugash", value=date.today() + timedelta(days=7))
            title = st.text_input("Nomi (masalan: Hafta aksiyasi)")
            if st.form_submit_button("Aksiyani yoqish", type="primary"):
                if val <= 0 or (kind == "foiz" and val > 100) or d2 < d1:
                    st.error("Qiymat yoki sanalar noto'g'ri.")
                else:
                    ex("INSERT INTO promos (product_id,title,kind,value,start_date,end_date,active) VALUES (:p,:t,:k,:v,:a,:b,1)",
                       p=int(pid), t=title.strip(), k=kind, v=val, a=str(d1), b=str(d2))
                    log("Aksiya yoqildi", f"{prods.loc[prods['id'] == pid, 'name'].iloc[0]}: {val:g} {'%' if kind == 'foiz' else 'so`m'} ({d1} – {d2})")
                    st.success("Aksiya yoqildi. Kassada avtomatik qo'llanadi.")
    pr = q("""SELECT x.id, x.title, p.name, x.kind, x.value, x.start_date, x.end_date, x.active FROM promos x JOIN products p ON p.id=x.product_id ORDER BY x.id DESC""")
    with top:
        if pr.empty:
            st.info("Aksiyalar yo'q.")
        else:
            t_ = now()[:10]
            pr["holat"] = pr.apply(lambda r: "O'chirilgan" if not r["active"] else ("Faol" if r["start_date"] <= t_ <= r["end_date"] else ("Kutilmoqda" if r["start_date"] > t_ else "Tugagan")), axis=1)
            pr["kind"] = pr["kind"].map({"foiz": "Chegirma %", "narx": "Aksiya narxi"})
            show_df(pr[["id", "title", "name", "kind", "value", "start_date", "end_date", "holat"]],
                    {"id": "№", "title": "Nomi", "name": "Tovar", "kind": "Turi", "value": "Qiymat", "start_date": "Boshlanish", "end_date": "Tugash", "holat": "Holati"})
            act = pr[pr["active"] == 1]
            if not act.empty:
                c1, c2 = st.columns([3, 1])
                x = c1.selectbox("To'xtatiladigan aksiya:", act["id"].tolist(), format_func=lambda i: f"№{i} — {act.loc[act['id'] == i, 'name'].iloc[0]}")
                if c2.button("⏹️ To'xtatish"):
                    ex("UPDATE promos SET active=0 WHERE id=:i", i=int(x))
                    log("Aksiya to'xtatildi", f"№{x}")
                    st.rerun()

elif menu == "taminotqayt":
    sup = q("SELECT id,name FROM partners WHERE kind='Yetkazib beruvchi' ORDER BY name")
    prods = q("SELECT * FROM products WHERE active=1 AND stock>0 ORDER BY name")
    if sup.empty or prods.empty:
        st.info("Yetkazib beruvchi va omborda qoldig'i bor tovar kerak.")
    else:
        sp = pick("Yetkazib beruvchi:", sup, "id", "name")
        pid = pick("Qaytariladigan tovar:", prods, "id", "name")
        p = prods[prods["id"] == pid].iloc[0]
        st.caption(f"Omborda: {p['stock']:g} {p['unit'] or ''}")
        sel = []
        if p["marked"]:
            cd = q("SELECT code FROM mark_codes WHERE product_id=:p AND status='omborda' ORDER BY id DESC LIMIT 2000", p=int(pid))
            sel = st.multiselect("Qaytariladigan markirovka kodlari", cd["code"].tolist())
            qty = float(len(sel))
        else:
            qty = st.number_input("Qaytariladigan miqdor:", min_value=0.0, max_value=float(p["stock"]), value=0.0, step=1.0)
        price = st.number_input("Qaytarish narxi (1 ta, so'm)", min_value=0.0, value=float(p["cost"] or 0), step=500.0)
        note = st.text_input("Sabab / izoh (masalan: nuqsonli)")
        st.markdown(f"**Summa: {m(qty * price)}** (yetkazib beruvchi oldidagi qarzimiz shuncha kamayadi)")
        if st.button("✅ Qaytarishni bajarish", type="primary"):
            if qty <= 0:
                st.error("Miqdorni kiriting.")
            else:
                try:
                    with ENGINE.begin() as c:
                        r = c.execute(text("UPDATE products SET stock = stock - :q WHERE id=:i AND stock >= :q"), {"q": qty, "i": int(pid)})
                        if r.rowcount == 0:
                            raise ValueError("Omborda yetarli emas")
                        for code in sel:
                            r = c.execute(text("UPDATE mark_codes SET status='qaytarildi' WHERE code=:c AND product_id=:p AND status='omborda'"), {"c": code, "p": int(pid)})
                            if r.rowcount == 0:
                                raise ValueError(f"Kod omborda yo'q: {code}")
                        rid = c.execute(text("INSERT INTO supplier_returns (created,partner_id,product_id,name,qty,price,user_name,note) VALUES (:t,:p,:pi,:n,:q,:pr,:u,:nt) RETURNING id"),
                                        {"t": now(), "p": int(sp), "pi": int(pid), "n": p["name"], "q": qty, "pr": price, "u": user["username"], "nt": note}).scalar()
                        c.execute(text("INSERT INTO ledger (created,partner_id,amount,doc,note,user_name) VALUES (:t,:p,:a,:d,:n,:u)"),
                                  {"t": now(), "p": int(sp), "a": qty * price, "d": f"Qaytarish №{rid}", "n": note or "Tovar qaytarildi", "u": user["username"]})
                    log("Yetkazib beruvchiga qaytarish", f"№{rid}, {p['name']} × {qty:g}, {m(qty * price)}")
                    st.success(f"Qaytarish №{rid} bajarildi.")
                except Exception as ex_:
                    st.error(f"Xato: {ex_}")
    show_df(q("""SELECT r.id, r.created, pa.name AS partner, r.name, r.qty, r.price, r.note FROM supplier_returns r LEFT JOIN partners pa ON pa.id=r.partner_id ORDER BY r.id DESC LIMIT 100"""),
            {"id": "№", "created": "Sana", "partner": "Yetkazib beruvchi", "name": "Tovar", "qty": "Soni", "price": "Narx", "note": "Izoh"})

elif menu == "inventar":
    st.caption("Markirovkali tovarlar qoldig'i kodlar soniga bog'liq, shuning uchun bu yerda ko'rsatilmaydi.")
    prods = q("SELECT id,name,unit,stock FROM products WHERE active=1 AND marked=0 ORDER BY name")
    if prods.empty:
        st.info("Tovarlar yo'q.")
    else:
        st.markdown("**1) Inventarizatsiya:** «Haqiqiy» ustuniga sanab chiqqan miqdorni yozing")
        df = prods.rename(columns={"id": "ID", "name": "Tovar", "unit": "Birlik", "stock": "Hisobda"})
        df["Haqiqiy"] = df["Hisobda"]
        ed = st.data_editor(df, hide_index=True, disabled=["ID", "Tovar", "Birlik", "Hisobda"], key="inv_ed")
        diff = ed[(ed["Haqiqiy"] - ed["Hisobda"]).abs() > 1e-9].copy()
        diff["Farq"] = diff["Haqiqiy"] - diff["Hisobda"]
        if diff.empty:
            st.info("Farq yo'q.")
        else:
            st.warning(f"{len(diff)} ta tovarda farq topildi:")
            show_df(diff[["Tovar", "Hisobda", "Haqiqiy", "Farq"]])
            if st.button("✅ Natijani qo'llash (qoldiqlarni to'g'rilash)", type="primary"):
                for _, r in diff.iterrows():
                    ex("UPDATE products SET stock = stock + :d WHERE id=:i", d=float(r["Farq"]), i=int(r["ID"]))
                    ex("INSERT INTO stock_adj (created,product_id,name,qty,reason,user_name) VALUES (:t,:p,:n,:q,'Inventarizatsiya',:u)", t=now(), p=int(r["ID"]), n=r["Tovar"], q=float(r["Farq"]), u=user["username"])
                    log("Inventarizatsiya", f"{r['Tovar']}: {r['Hisobda']:g} → {r['Haqiqiy']:g}")
                st.success("Qoldiqlar yangilandi.")
                st.rerun()
        st.markdown("---")
        st.markdown("**2) Hisobdan chiqarish** (buzilgan, muddati o'tgan, yo'qolgan)")
        with st.form("spis", clear_on_submit=True):
            pid = pick("Tovar:", prods, "id", "name")
            qty = st.number_input("Miqdori", min_value=0.0, step=1.0)
            why = st.selectbox("Sababi", ["Buzilgan", "Muddati o'tgan", "Yo'qolgan", "Boshqa"])
            if st.form_submit_button("Hisobdan chiqarish"):
                try:
                    with ENGINE.begin() as c:
                        r = c.execute(text("UPDATE products SET stock = stock - :q WHERE id=:i AND stock >= :q"), {"q": qty, "i": int(pid)})
                        if qty <= 0 or r.rowcount == 0:
                            raise ValueError("Miqdor noto'g'ri yoki omborda yetarli emas")
                        nm = prods.loc[prods["id"] == pid, "name"].iloc[0]
                        c.execute(text("INSERT INTO stock_adj (created,product_id,name,qty,reason,user_name) VALUES (:t,:p,:n,:q,:r,:u)"),
                                  {"t": now(), "p": int(pid), "n": nm, "q": -qty, "r": why, "u": user["username"]})
                    log("Hisobdan chiqarish", f"{nm} × {qty:g} ({why})")
                    st.success("Hisobdan chiqarildi.")
                except Exception as ex_:
                    st.error(f"Xato: {ex_}")
        show_df(q("SELECT created,name,qty,reason,user_name FROM stock_adj ORDER BY id DESC LIMIT 100"), {"created": "Sana", "name": "Tovar", "qty": "Miqdor (+/−)", "reason": "Sabab", "user_name": "Kim"})

elif menu == "nas_daftar":
    d = debtors()
    a, b, c = st.columns(3)
    a.metric("Jami nasiya (qarz)", m(d["balance"].sum()))
    b.metric("Shundan muddati o'tgan", m(d["overdue"].sum()))
    c.metric("Qarzdor mijozlar", len(d))
    s_ = st.text_input("🔍 Mijoz ismi yoki telefon")
    t = d[(d["name"].fillna("") + " " + d["phone"].fillna("")).str.contains(s_, case=False, regex=False)] if s_ and not d.empty else d
    show_df(t.sort_values("balance", ascending=False)[["name", "phone", "balance", "overdue", "notdue", "oldest"]],
            {"name": "Mijoz", "phone": "Telefon", "balance": "Jami qarz", "overdue": "Muddati o'tgan", "notdue": "Muddati o'tmagan", "oldest": "Eng eski muddat"})
    st.caption("Qarzni qabul qilish: Buxgalteriya → Mijozdan to'lov. Batafsil: Nasiya → Mijoz kartochkasi.")

elif menu == "nas_karta":
    cu = partner_balances("Mijoz")
    if cu.empty:
        st.info("Mijozlar yo'q.")
    else:
        cid = pick("Mijoz:", cu, "id", "name")
        led = q("SELECT created,doc,note,amount FROM ledger WHERE partner_id=:p ORDER BY created, id", p=int(cid))
        led["qoldiq"] = led["amount"].cumsum()
        dd = debtors()
        row = dd[dd["id"] == cid]
        bal = float(cu.loc[cu["id"] == cid, "balance"].iloc[0])
        given = led.loc[led["amount"] > 0, "amount"].sum()
        paid = -led.loc[led["amount"] < 0, "amount"].sum()
        lastp = led.loc[led["amount"] < 0, "created"].max() if (led["amount"] < 0).any() else "—"
        a, b, c, d_, e_ = st.columns(5)
        a.metric("Hozirgi qarz", m(max(bal, 0)))
        b.metric("Muddati o'tgan", m(float(row["overdue"].iloc[0]) if not row.empty else 0))
        c.metric("Jami nasiya olgan", m(given))
        d_.metric("Jami to'lagan", m(paid))
        e_.metric("Oxirgi to'lov", str(lastp)[:10])
        if not led.empty:
            st.markdown("**Qarz dinamikasi**")
            st.line_chart(led.set_index("created")["qoldiq"])
        led["debet"] = led["amount"].clip(lower=0)
        led["kredit"] = (-led["amount"]).clip(lower=0)
        out = led[["created", "doc", "note", "debet", "kredit", "qoldiq"]]
        show_df(out.iloc[::-1], {"created": "Sana", "doc": "Hujjat", "note": "Izoh", "debet": "Nasiya (+)", "kredit": "To'lov (−)", "qoldiq": "Qoldiq"})
        st.markdown("**Sotuvlar**")
        show_df(q("SELECT id,created,total,COALESCE(debt,0) AS debt,due_date FROM sales WHERE partner_id=:p ORDER BY id DESC", p=int(cid)),
                {"id": "Chek №", "created": "Sana", "total": "Summa", "debt": "Nasiya qismi", "due_date": "Muddat"})
        st.download_button("⬇️ Mijoz hisobini yuklab olish (CSV)", out.to_csv(index=False).encode("utf-8-sig"), file_name="mijoz_hisobi.csv", mime="text/csv")

elif menu == "nas_tahlil":
    d = debtors()
    if d.empty:
        st.info("Hozircha qarzdor mijoz yo'q.")
    else:
        a, b, c = st.columns(3)
        a.metric("Jami qarz", m(d["balance"].sum()))
        b.metric("Muddati o'tgan ulushi", f"{(d['overdue'].sum() / max(d['balance'].sum(), 1)) * 100:.0f}%")
        c.metric("O'rtacha qarz (mijozga)", m(d["balance"].mean()))
        g1, g2 = st.columns(2)
        g1.markdown("**Eng katta qarzdorlar (top 10)**")
        g1.bar_chart(d.nlargest(10, "balance").set_index("name")["balance"])
        ov = d[d["overdue"] > 0.5].copy()
        if not ov.empty:
            days = ov["oldest"].map(lambda x: (date.today() - date.fromisoformat(str(x)[:10])).days if x else 0)
            bins = pd.cut(days, [0, 7, 30, 60, 10000], labels=["1–7 kun", "8–30 kun", "31–60 kun", "60+ kun"])
            g2.markdown("**Muddati o'tgan qarz yoshi**")
            g2.bar_chart(ov.groupby(bins, observed=False)["overdue"].sum())
    lg = q("SELECT created, amount FROM ledger WHERE partner_id IN (SELECT id FROM partners WHERE kind='Mijoz')")
    if not lg.empty:
        lg["oy"] = lg["created"].str[:7]
        mm = pd.DataFrame({"Berilgan nasiya": lg[lg["amount"] > 0].groupby("oy")["amount"].sum(), "Qaytgan to'lov": (-lg[lg["amount"] < 0].groupby("oy")["amount"].sum())}).fillna(0)
        st.markdown("**Oylar bo'yicha: berilgan nasiya va qaytgan to'lov**")
        st.bar_chart(mm)

elif menu == "dokon":
    with st.form("shop"):
        st.markdown("**Do'kon ma'lumotlari** (chekda chiqadi)")
        n = st.text_input("Do'kon nomi", value=get_setting("shop_name", "SAV-DO"))
        ad = st.text_input("Manzil", value=get_setting("shop_addr", ""))
        ph = st.text_input("Telefon", value=get_setting("shop_phone", ""))
        inn = st.text_input("STIR (INN)", value=get_setting("shop_inn", ""))
        ft = st.text_input("Chek oxiridagi yozuv", value=get_setting("receipt_footer", "Xaridingiz uchun rahmat!"))
        if st.form_submit_button("Saqlash", type="primary"):
            for k_, v_ in [("shop_name", n), ("shop_addr", ad), ("shop_phone", ph), ("shop_inn", inn), ("receipt_footer", ft)]:
                set_setting(k_, v_.strip())
            log("Do'kon ma'lumotlari o'zgardi", n)
            st.success("Saqlandi.")
    st.caption("Har bir do'kon uchun bir xil kodning alohida nusxasi (alohida Streamlit ilova va alohida Neon baza) ishlatiladi, shunda ma'lumotlar aralashmaydi.")
