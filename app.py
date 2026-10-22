import pandas as pd
import streamlit as st

# Sahifa sozlamalari
st.set_page_config(
    page_title="Sav-do ERP", page_icon="🛒", layout="wide"
)

st.title("🛒 Sav-do ERP Tizimi")
st.markdown(
    "Do'kon va ombor uchun boshqaruv hamda savdo (kassa) oynasi."
)

# Xotirada vaqtinchalik baza (Keyinchalik Neon PostgreSQL ga ulanadi)
if "products" not in st.session_state:
    st.session_state.products = pd.DataFrame(
        {
            "ID": [1, 2, 3],
            "Tovar nomi": [
                "Coca-Cola 1.5L",
                "Non (Obi non)",
                "Qand (Kg)",
            ],
            "Birlik": ["dona", "dona", "kg"],
            "Sotuv narxi": [12000, 4000, 14000],
            "Qoldiq": [50, 30, 100],
        }
    )

if "cart" not in st.session_state:
    st.session_state.cart = []

# Chap taraf menyu
menu = st.sidebar.selectbox(
    "Bo'limni tanlang",
    [
        "🛒 Kassa (Savdo)",
        "📦 Tovarlar katalogi",
        "📥 Omborga kirim",
        "📊 Hisobotlar",
    ],
)

# -------------------------------------------------------------------------
# 1. KASSA (SAVDO OYNASI)
# -------------------------------------------------------------------------
if menu == "🛒 Kassa (Savdo)":
  st.subheader("💳 Tezkor savdo oynasi")

  df = st.session_state.products

  col1, col2 = st.columns([2, 1])

  with col1:
    st.markdown("### Tovarlar ro'yxati")
    # Qidirish
    search = st.text_input("🔍 Tovar nomini yozib qidiring...")
    if search:
      filtered_df = df[
          df["Tovar nomi"].str.contains(search, case=False, na=False)
      ]
    else:
      filtered_df = df

    st.dataframe(filtered_df, use_container_width=True)

    # Savatga qo'shish
    selected_id = st.selectbox(
        "Savatga qo'shish uchun Tovar ID raqamini tanlang:",
        df["ID"].tolist(),
    )
    qty = st.number_input("Miqdori:", min_value=1.0, value=1.0, step=1.0)

    if st.button("➕ Savatga qo'shish", type="primary"):
      tovar = df[df["ID"] == selected_id].iloc[0]
      st.session_state.cart.append(
          {
              "ID": tovar["ID"],
              "Tovar": tovar["Tovar nomi"],
              "Narxi": tovar["Sotuv narxi"],
              "Miqdori": qty,
              "Jami": tovar["Sotuv narxi"] * qty,
          }
      )
      st.success(f"{tovar['Tovar nomi']} savatga qo'shildi!")

  with col2:
    st.markdown("### 🛍️ Savat")
    if len(st.session_state.cart) > 0:
      cart_df = pd.DataFrame(st.session_state.cart)
      st.dataframe(
          cart_df[["Tovar", "Miqdori", "Jami"]], use_container_width=True
      )

      total_sum = cart_df["Jami"].sum()
      st.markdown(f"### Jami summa: **{total_sum:,.0f} so'm**")

      payment_type = st.radio(
          "To'lov turi:", ["Naqd pul", "Plastik karta", "Nasiya"]
      )

      if st.button("✅ Savatni yakunlash (Chek chiqarish)", type="success"):
        # Qoldiqni kamaytirish
        for item in st.session_state.cart:
          idx = st.session_state.products[
              st.session_state.products["ID"] == item["ID"]
          ].index[0]
          st.session_state.products.loc[idx, "Qoldiq"] -= item["Miqdori"]

        st.balloons()
        st.success(
            f"Savdo muvaffaqiyatli yakunlandi! To'lov turi: {payment_type}"
        )
        st.session_state.cart = []
        st.rerun()

      if st.button("🗑️ Savatni tozalash"):
        st.session_state.cart = []
        st.rerun()
    else:
      st.info("Savat hozircha bo'sh.")

# -------------------------------------------------------------------------
# 2. TOVARLAR KATALOGI
# -------------------------------------------------------------------------
elif menu == "📦 Tovarlar katalogi":
  st.subheader("📦 Tovarlarni boshqarish va qo'shish")

  df = st.session_state.products
  st.dataframe(df, use_container_width=True)

  st.markdown("---")
  st.markdown("### Yangi tovar qo'shish")
  with st.form("add_product_form"):
    new_name = st.text_input("Tovar nomi:")
    new_unit = st.selectbox("O'lchov birligi:", ["dona", "kg", "quti", "metr"])
    new_price = st.number_input("Sotish narxi (so'm):", min_value=0.0, value=1000.0)
    new_qty = st.number_input("Boshlang'ich qoldiq:", min_value=0.0, value=10.0)

    submit = st.form_submit_button("Saqlash")
    if submit and new_name:
      new_id = int(df["ID"].max() + 1) if not df.empty else 1
      new_row = pd.DataFrame(
          {
              "ID": [new_id],
              "Tovar nomi": [new_name],
              "Birlik": [new_unit],
              "Sotuv narxi": [new_price],
              "Qoldiq": [new_qty],
          }
      )
      st.session_state.products = pd.concat(
          [df, new_row], ignore_index=True
      )
      st.success("Yangi tovar muvaffaqiyatli qo'shildi!")
      st.rerun()

# -------------------------------------------------------------------------
# 3. OMBORGA KIRIM
# -------------------------------------------------------------------------
elif menu == "📥 Omborga kirim":
  st.subheader("📥 Tovarlarni omborga kirim qilish")
  df = st.session_state.products

  with st.form("stock_in_form"):
    prod_id = st.selectbox(
        "Tovarni tanlang:",
        df["ID"].tolist(),
        format_func=lambda x: df[df["ID"] == x]["Tovar nomi"].values[0],
    )
    add_qty = st.number_input(
        "Kirim qilinadigan miqdor:", min_value=1.0, value=10.0
    )

    submit_in = st.form_submit_button("Kirim qilish")
    if submit_in:
      idx = st.session_state.products[
          st.session_state.products["ID"] == prod_id
      ].index[0]
      st.session_state.products.loc[idx, "Qoldiq"] += add_qty
      st.success("Ombor qoldig'i muvaffaqiyatli yangilandi!")
      st.rerun()

# -------------------------------------------------------------------------
# 4. HISOBOTLAR
# -------------------------------------------------------------------------
elif menu == "📊 Hisobotlar":
  st.subheader("📊 Umumiy ombor va qoldiq hisoboti")
  df = st.session_state.products

  total_items = df["Qoldiq"].sum()
  total_value = (df["Qoldiq"] * df["Sotuv narxi"]).sum()

  col1, col2 = st.columns(2)
  col1.metric("Ombordagi jami tovar miqdori", f"{total_items:,.1f}")
  col2.metric("Tovarlarning umumiy bahosi", f"{total_value:,.0f} so'm")

  st.markdown("### Tovar qoldiqlari jadvali")
  st.dataframe(df, use_container_width=True)
