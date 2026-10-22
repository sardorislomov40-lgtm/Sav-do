from collections import namedtuple

from django.db import transaction

from .barcode import normalize_code
from .labels import LabelItem
from .models import Barcode, Product, ProductUnit, next_internal_code

Found = namedtuple("Found", "product product_unit barcode")


def base_product_unit(product: Product) -> ProductUnit:
    pu, _ = ProductUnit.objects.select_related("unit").get_or_create(
        product=product, unit=product.base_unit, defaults={"factor": 1}
    )
    return pu


def find_by_barcode(raw_code: str):
    """Skaner o'qigan kod bo'yicha (tovar, birlik) topadi; topilmasa None."""
    code = normalize_code(raw_code)
    if not code:
        return None
    bc = (
        Barcode.objects.select_related("product__base_unit", "product_unit__unit")
        .filter(code=code, product__is_active=True)
        .first()
    )
    if bc is None:
        return None
    pu = bc.product_unit or base_product_unit(bc.product)
    return Found(bc.product, pu, bc)


@transaction.atomic
def create_internal_barcode(product: Product) -> Barcode:
    """Kodsiz tovarga ichki EAN-13 ("27..." bilan boshlanadigan) yaratadi."""
    existing = product.barcodes.filter(kind=Barcode.Kind.INTERNAL).first()
    if existing:
        return existing
    return Barcode.objects.create(code=next_internal_code(), product=product, kind=Barcode.Kind.INTERNAL)


def build_label_items(product_ids, copies=1):
    """Etiketka uchun elementlar. copies: bitta son yoki {product_id: son}.
    Qaytaradi: (items, kodsiz_tovarlar_nomlari)."""
    products = {
        p.pk: p
        for p in Product.objects.filter(pk__in=product_ids).prefetch_related(
            "barcodes__product_unit__unit", "units__unit"
        )
    }
    items, skipped = [], []
    for pid in product_ids:
        p = products.get(pid)
        if p is None:
            continue
        barcodes = list(p.barcodes.all())
        if not barcodes:
            skipped.append(p.name)
            continue
        bc = barcodes[0]
        pu = bc.product_unit or p.base_product_unit
        n = copies.get(pid, 1) if isinstance(copies, dict) else copies
        items.append(
            LabelItem(
                name=p.name, code=bc.code, price=pu.retail_price if pu else None,
                unit=pu.unit.short_name if pu else "", copies=max(1, int(n)),
            )
        )
    return items, skipped
