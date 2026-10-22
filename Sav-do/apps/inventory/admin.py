from django.contrib import admin

from .models import Receipt, ReceiptLine, StockCount, StockCountLine, StockMovement, Warehouse


@admin.register(Warehouse)
class WarehouseAdmin(admin.ModelAdmin):
    list_display = ("name", "is_default", "is_active")


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(StockMovement)
class StockMovementAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "product", "warehouse", "quantity", "kind")
    list_filter = ("kind", "warehouse")
    search_fields = ("product__name",)


class ReceiptLineInline(admin.TabularInline):
    model = ReceiptLine
    extra = 0


@admin.register(Receipt)
class ReceiptAdmin(ReadOnlyAdmin):
    list_display = ("number", "warehouse", "supplier", "date", "status")
    inlines = [ReceiptLineInline]


class StockCountLineInline(admin.TabularInline):
    model = StockCountLine
    extra = 0


@admin.register(StockCount)
class StockCountAdmin(ReadOnlyAdmin):
    list_display = ("number", "warehouse", "status", "created_at")
    inlines = [StockCountLineInline]
