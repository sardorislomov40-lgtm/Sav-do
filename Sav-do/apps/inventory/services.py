from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from apps.catalog.models import ProductUnit

from .models import DocStatus, Receipt, StockCount, StockMovement

ZERO = Decimal("0")


class ServiceError(Exception):
    """Foydalanuvchiga ko'rsatiladigan biznes xato."""


def stock_map(warehouse=None, product_ids=None) -> dict:
    qs = StockMovement.objects.all()
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    if product_ids is not None:
        qs = qs.filter(product_id__in=list(product_ids))
    rows = qs.order_by().values("product_id").annotate(total=Sum("quantity"))
    return {r["product_id"]: r["total"] or ZERO for r in rows}


def product_stock(product, warehouse=None) -> Decimal:
    qs = StockMovement.objects.filter(product=product)
    if warehouse is not None:
        qs = qs.filter(warehouse=warehouse)
    return qs.aggregate(t=Sum("quantity"))["t"] or ZERO


def stock_by_warehouse(product):
    rows = (
        StockMovement.objects.filter(product=product).order_by()
        .values("warehouse__name").annotate(total=Sum("quantity")).order_by("warehouse__name")
    )
    return [(r["warehouse__name"], r["total"]) for r in rows if r["total"] != 0]


def check_quantity(quantity: Decimal, unit, label="Miqdor"):
    """Miqdor musbat bo'lishi va kasr faqat kg/litr kabi birliklarda mumkinligini tekshiradi."""
    if quantity <= 0:
        raise ServiceError(f"{label} noldan katta bo'lishi kerak.")
    if not unit.allows_fraction and quantity != quantity.to_integral_value():
        raise ServiceError(f"«{unit.name}» birligida kasr miqdor bo'lmaydi.")


@transaction.atomic
def post_receipt(receipt_id, user) -> Receipt:
    receipt = Receipt.objects.select_for_update().get(pk=receipt_id)
    if receipt.status != DocStatus.DRAFT:
        raise ServiceError("Bu hujjat allaqachon tasdiqlangan.")
    lines = list(receipt.lines.select_related("product", "product_unit__unit"))
    if not lines:
        raise ServiceError("Hujjatda tovar yo'q.")
    movements = []
    for line in lines:
        check_quantity(line.quantity, line.product_unit.unit, f"«{line.product.name}» miqdori")
        base_qty = line.quantity * line.product_unit.factor
        movements.append(StockMovement(
            product=line.product, warehouse=receipt.warehouse, quantity=base_qty,
            kind=StockMovement.Kind.RECEIPT, receipt=receipt, created_by=user,
            unit_cost=(line.unit_cost / line.product_unit.factor) if line.unit_cost else None,
        ))
    StockMovement.objects.bulk_create(movements)
    receipt.status = DocStatus.POSTED
    receipt.posted_at = timezone.now()
    receipt.save(update_fields=["status", "posted_at"])
    return receipt


@transaction.atomic
def post_stock_count(count_id, user) -> StockCount:
    count = StockCount.objects.select_for_update().get(pk=count_id)
    if count.status != DocStatus.DRAFT:
        raise ServiceError("Bu inventarizatsiya allaqachon tasdiqlangan.")
    lines = list(count.lines.select_related("product"))
    if not lines:
        raise ServiceError("Inventarizatsiyada tovar yo'q.")
    current = stock_map(warehouse=count.warehouse, product_ids=[l.product_id for l in lines])
    movements = []
    for line in lines:
        system = current.get(line.product_id, ZERO)
        line.system_qty = system
        line.save(update_fields=["system_qty"])
        diff = line.counted_qty - system
        if diff != 0:
            movements.append(StockMovement(
                product=line.product, warehouse=count.warehouse, quantity=diff,
                kind=StockMovement.Kind.STOCK_COUNT, stock_count=count, created_by=user,
            ))
    StockMovement.objects.bulk_create(movements)
    count.status = DocStatus.POSTED
    count.posted_at = timezone.now()
    count.save(update_fields=["status", "posted_at"])
    return count


def unit_for(product, unit_id=None) -> ProductUnit:
    """Tovarning sotish birligi (ko'rsatilmasa, asosiy birlik)."""
    qs = ProductUnit.objects.select_related("unit").filter(product=product)
    pu = qs.filter(pk=unit_id).first() if unit_id else qs.filter(unit=product.base_unit).first()
    if pu is None:
        pu = ProductUnit.objects.create(product=product, unit=product.base_unit, factor=1)
    return pu
