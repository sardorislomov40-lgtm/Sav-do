from django.urls import reverse

# (nomi, qisqa nomi, url nomi, faol bo'lish prefiksi, kim ko'radi, pastki panelda ko'rinsinmi)
NAV = [
    ("Bosh sahifa", "Bosh", "home", "home", "any", True),
    ("Tovarlar", "Tovarlar", "catalog:product_list", "catalog:", "any", True),
    ("Qoldiq", "Qoldiq", "inventory:stock_list", "inventory:stock", "any", True),
    ("Kirim", "Kirim", "inventory:receipt_list", "inventory:receipt", "stock", True),
    ("Inventarizatsiya", "Sanoq", "inventory:count_list", "inventory:count", "stock", True),
    ("Harakatlar jurnali", "Jurnal", "inventory:movement_list", "inventory:movement", "stock", False),
]


def roles(request):
    user = request.user
    if not user.is_authenticated:
        return {}
    view = getattr(getattr(request, "resolver_match", None), "view_name", "") or ""
    nav = []
    for label, short, url_name, prefix, who, bottom in NAV:
        if who == "stock" and not user.can_manage_stock:
            continue
        active = view == prefix if prefix == "home" else view.startswith(prefix)
        nav.append({"label": label, "short": short, "url": reverse(url_name), "active": active, "bottom": bottom})
    return {
        "is_admin": user.is_admin_role,
        "can_stock": user.can_manage_stock,
        "can_edit_prices": user.can_edit_prices,
        "nav": nav,
    }
