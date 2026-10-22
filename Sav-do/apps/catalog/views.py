from django.contrib import messages
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.decorators import any_role, stock_staff
from apps.inventory.models import StockMovement
from apps.inventory.services import stock_by_warehouse, stock_map

from .forms import CategoryForm, ProductForm, ProductUnitFormSet, BarcodeFormSet
from .labels import DEFAULT_LAYOUT, LAYOUTS, build_labels_pdf
from .models import Category, Product
from .services import build_label_items, create_internal_barcode

PAGE_SIZE = 30


def _product_queryset(request):
    q = request.GET.get("q", "").strip()
    qs = Product.objects.select_related("category", "base_unit").prefetch_related("units")
    if request.GET.get("archived") != "1":
        qs = qs.filter(is_active=True)
    category = request.GET.get("category", "")
    if category.isdigit():
        qs = qs.filter(category_id=int(category))
    if q:
        qs = qs.filter(
            Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcodes__code__icontains=q)
        ).distinct()
    return qs, q, category


@any_role
def product_list(request):
    qs, q, category = _product_queryset(request)
    page = Paginator(qs, PAGE_SIZE).get_page(request.GET.get("page"))
    totals = stock_map(product_ids=[p.pk for p in page])
    rows = []
    for p in page:
        pu = p.base_product_unit
        stock = totals.get(p.pk, 0)
        rows.append({
            "product": p, "stock": stock,
            "retail": pu.retail_price if pu else None,
            "wholesale": pu.wholesale_price if pu else None,
            "low": p.min_stock > 0 and stock <= p.min_stock,
        })
    ctx = {
        "rows": rows, "page": page, "q": q, "category": category,
        "archived": request.GET.get("archived") == "1",
        "categories": Category.objects.all(),
        "layouts": LAYOUTS, "default_layout": DEFAULT_LAYOUT,
    }
    template = "catalog/_product_list.html" if request.headers.get("HX-Request") else "catalog/product_list.html"
    return render(request, template, ctx)


@any_role
def product_detail(request, pk):
    product = get_object_or_404(
        Product.objects.select_related("category", "base_unit").prefetch_related(
            "units__unit", "barcodes__product_unit__unit"
        ),
        pk=pk,
    )
    return render(request, "catalog/product_detail.html", {
        "product": product,
        "stock_rows": stock_by_warehouse(product),
        "movements": StockMovement.objects.filter(product=product).select_related("warehouse")[:15],
        "layouts": LAYOUTS, "default_layout": DEFAULT_LAYOUT,
    })


@stock_staff
def product_form_view(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else None
    can_prices = request.user.can_edit_prices
    prefix_units, prefix_codes = "units", "codes"
    if request.method == "POST":
        form = ProductForm(request.POST, instance=product, can_edit_prices=can_prices)
        owner = product or Product()
        unit_fs = ProductUnitFormSet(request.POST, instance=owner, prefix=prefix_units,
                                     queryset=_extra_units(product))
        unit_fs.can_edit_prices = can_prices
        unit_fs.base_unit_id = product.base_unit_id if product else _int_or_none(request.POST.get("base_unit"))
        code_fs = BarcodeFormSet(request.POST, instance=owner, prefix=prefix_codes)
        valid = [form.is_valid(), unit_fs.is_valid(), code_fs.is_valid()]
        if all(valid):
            with transaction.atomic():
                saved = form.save()
                unit_fs.instance = code_fs.instance = saved
                unit_fs.save()
                code_fs.save()
                if form.cleaned_data.get("make_internal_code") and not saved.barcodes.exists():
                    create_internal_barcode(saved)
            messages.success(request, f"«{saved.name}» saqlandi.")
            return redirect("catalog:product_detail", pk=saved.pk)
    else:
        form = ProductForm(instance=product, can_edit_prices=can_prices)
        owner = product or Product()
        unit_fs = ProductUnitFormSet(instance=owner, prefix=prefix_units, queryset=_extra_units(product))
        unit_fs.can_edit_prices = can_prices
        code_fs = BarcodeFormSet(instance=owner, prefix=prefix_codes)
    return render(request, "catalog/product_form.html", {
        "form": form, "unit_fs": unit_fs, "code_fs": code_fs, "product": product,
    })


def _extra_units(product):
    """Asosiy birlikdan tashqari birliklar (quti, qop va h.k.)."""
    from .models import ProductUnit

    if product is None:
        return ProductUnit.objects.none()
    return ProductUnit.objects.filter(product=product).exclude(unit_id=product.base_unit_id).select_related("unit")


def _int_or_none(value):
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


@stock_staff
@require_POST
def product_generate_barcode(request, pk):
    product = get_object_or_404(Product, pk=pk)
    code = create_internal_barcode(product)
    messages.success(request, f"Ichki shtrix-kod: {code.code}")
    return redirect("catalog:product_detail", pk=product.pk)


@any_role
@require_POST
def labels_pdf(request):
    ids = [int(i) for i in request.POST.getlist("product") if i.isdigit()]
    if not ids:
        messages.error(request, "Etiketka uchun tovar tanlanmadi.")
        return redirect(request.META.get("HTTP_REFERER") or "catalog:product_list")
    raw_copies = request.POST.get("copies") or "1"
    copies = int(raw_copies) if raw_copies.isdigit() and int(raw_copies) > 0 else 1
    pdf = _labels_response(request, ids, copies, request.POST.get("layout") or DEFAULT_LAYOUT)
    return pdf or redirect(request.META.get("HTTP_REFERER") or "catalog:product_list")


def _labels_response(request, ids, copies, layout):
    items, skipped = build_label_items(ids, copies)
    if skipped:
        messages.warning(request, "Shtrix-kodi yo'q tovarlar o'tkazib yuborildi: " + ", ".join(skipped[:5]))
    if not items:
        messages.error(request, "Chop etish uchun shtrix-kodli tovar yo'q. Avval kod yarating.")
        return None
    try:
        data = build_labels_pdf(items, layout)
    except ValueError as exc:
        messages.error(request, str(exc))
        return None
    response = HttpResponse(data, content_type="application/pdf")
    response["Content-Disposition"] = 'inline; filename="etiketka.pdf"'
    return response


@any_role
def product_search(request):
    """HTMX: hujjatga tovar qo'shish uchun qidiruv natijalari."""
    q = request.GET.get("q", "").strip()
    mode = request.GET.get("mode", "receipt")
    doc = request.GET.get("doc", "")
    products = []
    if len(q) >= 2:
        products = (
            Product.objects.filter(is_active=True)
            .filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcodes__code__icontains=q))
            .select_related("base_unit").distinct()[:8]
        )
    return render(request, "partials/_product_search.html",
                  {"products": products, "mode": mode, "doc": doc, "q": q})


@stock_staff
def category_list(request):
    form = CategoryForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        form.save()
        messages.success(request, "Kategoriya qo'shildi.")
        return redirect("catalog:category_list")
    categories = Category.objects.select_related("parent").annotate(n=Count("products"))
    return render(request, "catalog/category_list.html", {"form": form, "categories": categories})


@stock_staff
@require_POST
def category_delete(request, pk):
    category = get_object_or_404(Category, pk=pk)
    if category.products.exists() or category.children.exists():
        messages.error(request, "Ichida tovar yoki ichki kategoriya bor, o'chirib bo'lmaydi.")
    else:
        category.delete()
        messages.success(request, "Kategoriya o'chirildi.")
    return redirect("catalog:category_list")
