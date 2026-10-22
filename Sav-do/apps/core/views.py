from decimal import Decimal

from django.contrib.auth.decorators import login_required
from django.shortcuts import render

from apps.catalog.models import Product
from apps.inventory.models import Receipt, StockCount
from apps.inventory.services import stock_map


@login_required
def home(request):
    totals = stock_map()
    low = []
    for p in Product.objects.filter(is_active=True, min_stock__gt=0).select_related("base_unit"):
        stock = totals.get(p.pk, Decimal("0"))
        if stock <= p.min_stock:
            low.append((p, stock))
    low.sort(key=lambda row: row[1])
    ctx = {
        "product_count": Product.objects.filter(is_active=True).count(),
        "low_stock": low[:10],
        "low_total": len(low),
    }
    if request.user.can_manage_stock:
        ctx["draft_receipts"] = Receipt.objects.filter(status=Receipt.Status.DRAFT).count()
        ctx["draft_counts"] = StockCount.objects.filter(status=StockCount.Status.DRAFT).count()
        ctx["recent_receipts"] = Receipt.objects.select_related("warehouse")[:5]
    return render(request, "home.html", ctx)
