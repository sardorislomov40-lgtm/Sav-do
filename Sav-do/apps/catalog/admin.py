from django.contrib import admin

from .models import Barcode, Category, Product, ProductUnit, Unit


@admin.register(Unit)
class UnitAdmin(admin.ModelAdmin):
    list_display = ("name", "short_name", "allows_fraction")


@admin.register(Category)
class CategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "parent")


class ProductUnitInline(admin.TabularInline):
    model = ProductUnit
    extra = 0


class BarcodeInline(admin.TabularInline):
    model = Barcode
    extra = 0


@admin.register(Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ("name", "category", "base_unit", "is_active")
    list_filter = ("is_active", "category")
    search_fields = ("name", "sku", "barcodes__code")
    inlines = [ProductUnitInline, BarcodeInline]
