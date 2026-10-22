from decimal import Decimal, InvalidOperation
from math import ceil

from django.contrib import messages
from django.db.models import Q
from django.core.paginator import Paginator
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import any_role, stock_staff
from apps.catalog.labels import DEFAULT_LAYOUT, LAYOUTS
from apps.catalog.models import Product
from apps.catalog.services import find_by_barcode
from apps.catalog.views import _labels_response

from .forms import ReceiptForm, StockCountForm
from .models import Receipt, ReceiptLine, StockCount, StockCountLine, StockMovement, Warehouse
from .services import (ServiceError, ZERO, check_quantity, post_receipt, post_stock_count,
                       stock_map, unit_for)


def parse_decimal(value, default=None):
    try:
        d = Decimal(str(value).strip().replace(",", ".").replace(" ", ""))
    except InvalidOperation:
        return default
    return d if d.is_finite() else default


# ---------------------------------------------------------------- Qoldiq
@any_role
def stock_list(request):
    warehouses = Warehouse.objects.filter(is_active=True)
    wid = request.GET.get("warehouse", "")
    warehouse = warehouses.filter(pk=wid).first() if wid.isdigit() else None
    q = request.GET.get("q", "").strip()
    only = request.GET.get("only", "has")  # has | low | all

    products = Product.objects.filter(is_active=True).select_related("base_unit")
    if q:
        products = products.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcodes__code__icontains=q)
        ).distinct()
    totals = stock_map(warehouse=warehouse)
    rows = []
    for p in products:
        stock = totals.get(p.pk, ZERO)
        low = p.min_stock > 0 and stock <= p.min_stock
        if only == "has" and stock == 0:
            continue
        if only == "low" and not low:
            continue
        rows.append({"product": p, "stock": stock, "low": low})
    page = Paginator(rows, 40).get_page(request.GET.get("page"))
    ctx = {"page": page, "warehouses": warehouses, "warehouse": warehouse, "q": q, "only": only}
    return render(request, "inventory/stock_list.html", ctx)


@stock_staff
def movement_list(request):
    qs = StockMovement.objects.select_related("product__base_unit", "warehouse", "created_by")
    kind = request.GET.get("kind", "")
    if kind in StockMovement.Kind.values:
        qs = qs.filter(kind=kind)
    q = request.GET.get("q", "").strip()
    if q:
        qs = qs.filter(product__name__icontains=q)
    page = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "inventory/movement_list.html",
                  {"page": page, "kind": kind, "q": q, "kinds": StockMovement.Kind.choices})


# ---------------------------------------------------------------- Kirim
def _receipt_ctx(receipt, error=None):
    lines = receipt.lines.select_related("product__base_unit", "product_unit__unit").order_by("-id")
    return {"receipt": receipt, "lines": lines, "error": error, "editable": receipt.is_draft,
            "total": sum((l.total for l in lines), ZERO)}


def _receipt_partial(request, receipt, error=None):
    return render(request, "inventory/_receipt_lines.html", _receipt_ctx(receipt, error))


def _last_cost(product, product_unit):
    last = (StockMovement.objects.filter(product=product, kind=StockMovement.Kind.RECEIPT,
                                         unit_cost__isnull=False).order_by("-id").first())
    return (last.unit_cost * product_unit.factor).quantize(Decimal("0.01")) if last else ZERO


def _add_receipt_line(receipt, product, pu):
    line, created = ReceiptLine.objects.get_or_create(
        receipt=receipt, product_unit=pu,
        defaults={"product": product, "quantity": Decimal("1"), "unit_cost": _last_cost(product, pu)},
    )
    if not created:
        line.quantity += 1
        line.save(update_fields=["quantity"])


@stock_staff
def receipt_list(request):
    qs = Receipt.objects.select_related("warehouse")
    status = request.GET.get("status", "")
    if status in Receipt.Status.values:
        qs = qs.filter(status=status)
    page = Paginator(qs, 30).get_page(request.GET.get("page"))
    return render(request, "inventory/receipt_list.html", {"page": page, "status": status})


@stock_staff
def receipt_create(request):
    form = ReceiptForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        receipt = form.save(commit=False)
        receipt.created_by = request.user
        receipt.save()
        return redirect("inventory:receipt_detail", pk=receipt.pk)
    return render(request, "inventory/doc_form.html",
                  {"form": form, "title": "Yangi kirim hujjati", "back": "inventory:receipt_list"})


@stock_staff
def receipt_detail(request, pk):
    receipt = get_object_or_404(Receipt.objects.select_related("warehouse", "created_by"), pk=pk)
    ctx = _receipt_ctx(receipt)
    ctx.update({"layouts": LAYOUTS, "default_layout": DEFAULT_LAYOUT})
    return render(request, "inventory/receipt_detail.html", ctx)


def _draft_receipt_or_error(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    if not receipt.is_draft:
        return receipt, _receipt_partial(request, receipt, "Hujjat tasdiqlangan, o'zgartirib bo'lmaydi.")
    return receipt, None


@stock_staff
@require_POST
def receipt_scan(request, pk):
    receipt, blocked = _draft_receipt_or_error(request, pk)
    if blocked:
        return blocked
    code = request.POST.get("code", "")
    found = find_by_barcode(code)
    if found is None:
        return _receipt_partial(request, receipt,
                                f"«{code.strip()}» kodli tovar topilmadi. Avval tovarni «Tovarlar» bo'limida qo'shing.")
    _add_receipt_line(receipt, found.product, found.product_unit)
    return _receipt_partial(request, receipt)


@stock_staff
@require_POST
def receipt_add_product(request, pk):
    receipt, blocked = _draft_receipt_or_error(request, pk)
    if blocked:
        return blocked
    product = get_object_or_404(Product, pk=request.POST.get("product_id") or 0, is_active=True)
    _add_receipt_line(receipt, product, unit_for(product, request.POST.get("unit_id")))
    return _receipt_partial(request, receipt)


@stock_staff
@require_POST
def receipt_line_update(request, pk, line_id):
    receipt, blocked = _draft_receipt_or_error(request, pk)
    if blocked:
        return blocked
    line = get_object_or_404(ReceiptLine.objects.select_related("product_unit__unit"), pk=line_id, receipt=receipt)
    qty = parse_decimal(request.POST.get("quantity"))
    cost = parse_decimal(request.POST.get("unit_cost"), ZERO)
    try:
        if qty is None:
            raise ServiceError("Miqdorni raqam bilan kiriting.")
        check_quantity(qty, line.product_unit.unit, f"«{line.product.name}» miqdori")
        if cost < 0:
            raise ServiceError("Tannarx manfiy bo'lmaydi.")
    except ServiceError as exc:
        return _receipt_partial(request, receipt, str(exc))
    line.quantity, line.unit_cost = qty, cost
    line.save(update_fields=["quantity", "unit_cost"])
    return _receipt_partial(request, receipt)


@stock_staff
@require_POST
def receipt_line_delete(request, pk, line_id):
    receipt, blocked = _draft_receipt_or_error(request, pk)
    if blocked:
        return blocked
    ReceiptLine.objects.filter(pk=line_id, receipt=receipt).delete()
    return _receipt_partial(request, receipt)


@stock_staff
@require_POST
def receipt_post(request, pk):
    try:
        receipt = post_receipt(pk, request.user)
        messages.success(request, f"{receipt.number} tasdiqlandi, qoldiq yangilandi.")
    except ServiceError as exc:
        messages.error(request, str(exc))
    return redirect("inventory:receipt_detail", pk=pk)


@stock_staff
@require_POST
def receipt_remove(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    if not receipt.is_draft:
        messages.error(request, "Tasdiqlangan hujjatni o'chirib bo'lmaydi.")
        return redirect("inventory:receipt_detail", pk=pk)
    receipt.delete()
    messages.success(request, "Qoralama o'chirildi.")
    return redirect("inventory:receipt_list")


@stock_staff
@require_POST
def receipt_labels(request, pk):
    receipt = get_object_or_404(Receipt, pk=pk)
    copies, ids = {}, []
    for line in receipt.lines.select_related("product_unit__unit"):
        ids.append(line.product_id)
        unit = line.product_unit.unit
        copies[line.product_id] = copies.get(line.product_id, 0) + (
            1 if unit.allows_fraction else min(500, ceil(line.quantity))
        )
    ids = list(dict.fromkeys(ids))
    response = _labels_response(request, ids, copies, request.POST.get("layout") or DEFAULT_LAYOUT) if ids else None
    return response or redirect("inventory:receipt_detail", pk=pk)


# ---------------------------------------------------------------- Inventarizatsiya
def _count_ctx(count, error=None):
    lines = list(count.lines.select_related("product__base_unit").order_by("-id"))
    current = stock_map(warehouse=count.warehouse, product_ids=[l.product_id for l in lines]) if count.is_draft else {}
    rows = []
    for l in lines:
        system = current.get(l.product_id, ZERO) if count.is_draft else (l.system_qty or ZERO)
        rows.append({"line": l, "system": system, "diff": l.counted_qty - system})
    return {"count": count, "rows": rows, "error": error, "editable": count.is_draft}


def _count_partial(request, count, error=None):
    return render(request, "inventory/_count_lines.html", _count_ctx(count, error))


def _draft_count_or_error(request, pk):
    count = get_object_or_404(StockCount, pk=pk)
    if not count.is_draft:
        return count, _count_partial(request, count, "Inventarizatsiya tasdiqlangan, o'zgartirib bo'lmaydi.")
    return count, None


@stock_staff
def count_list(request):
    page = Paginator(StockCount.objects.select_related("warehouse"), 30).get_page(request.GET.get("page"))
    return render(request, "inventory/count_list.html", {"page": page})


@stock_staff
def count_create(request):
    form = StockCountForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        count = form.save(commit=False)
        count.created_by = request.user
        count.save()
        return redirect("inventory:count_detail", pk=count.pk)
    return render(request, "inventory/doc_form.html",
                  {"form": form, "title": "Yangi inventarizatsiya", "back": "inventory:count_list"})


@stock_staff
def count_detail(request, pk):
    count = get_object_or_404(StockCount.objects.select_related("warehouse"), pk=pk)
    return render(request, "inventory/count_detail.html", _count_ctx(count))


@stock_staff
@require_POST
def count_scan(request, pk):
    count, blocked = _draft_count_or_error(request, pk)
    if blocked:
        return blocked
    code = request.POST.get("code", "")
    found = find_by_barcode(code)
    if found is None:
        return _count_partial(request, count, f"«{code.strip()}» kodli tovar topilmadi.")
    line, _ = StockCountLine.objects.get_or_create(stock_count=count, product=found.product)
    line.counted_qty += found.product_unit.factor  # quti skanerlansa, quti ichidagi donalar qo'shiladi
    line.save(update_fields=["counted_qty"])
    return _count_partial(request, count)


@stock_staff
@require_POST
def count_add_product(request, pk):
    count, blocked = _draft_count_or_error(request, pk)
    if blocked:
        return blocked
    product = get_object_or_404(Product, pk=request.POST.get("product_id") or 0, is_active=True)
    StockCountLine.objects.get_or_create(stock_count=count, product=product)
    return _count_partial(request, count)


@stock_staff
@require_POST
def count_line_update(request, pk, line_id):
    count, blocked = _draft_count_or_error(request, pk)
    if blocked:
        return blocked
    line = get_object_or_404(StockCountLine.objects.select_related("product__base_unit"), pk=line_id, stock_count=count)
    qty = parse_decimal(request.POST.get("counted_qty"))
    if qty is None or qty < 0:
        return _count_partial(request, count, "Sanalgan miqdorni 0 yoki undan katta raqam bilan kiriting.")
    if not line.product.base_unit.allows_fraction and qty != qty.to_integral_value():
        return _count_partial(request, count, f"«{line.product.base_unit.name}» birligida kasr miqdor bo'lmaydi.")
    line.counted_qty = qty
    line.save(update_fields=["counted_qty"])
    return _count_partial(request, count)


@stock_staff
@require_POST
def count_line_delete(request, pk, line_id):
    count, blocked = _draft_count_or_error(request, pk)
    if blocked:
        return blocked
    StockCountLine.objects.filter(pk=line_id, stock_count=count).delete()
    return _count_partial(request, count)


@stock_staff
@require_POST
def count_post(request, pk):
    try:
        count = post_stock_count(pk, request.user)
        messages.success(request, f"{count.number} tasdiqlandi, qoldiq sanoq bo'yicha tuzatildi.")
    except ServiceError as exc:
        messages.error(request, str(exc))
    return redirect("inventory:count_detail", pk=pk)


@stock_staff
@require_POST
def count_remove(request, pk):
    count = get_object_or_404(StockCount, pk=pk)
    if not count.is_draft:
        messages.error(request, "Tasdiqlangan hujjatni o'chirib bo'lmaydi.")
        return redirect("inventory:count_detail", pk=pk)
    count.delete()
    messages.success(request, "Qoralama o'chirildi.")
    return redirect("inventory:count_list")
