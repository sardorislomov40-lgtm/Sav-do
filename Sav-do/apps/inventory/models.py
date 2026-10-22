from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.catalog.models import Product, ProductUnit


class Warehouse(models.Model):
    name = models.CharField("Nomi", max_length=80, unique=True)
    address = models.CharField("Manzil", max_length=200, blank=True)
    is_default = models.BooleanField("Asosiy", default=False)
    is_active = models.BooleanField("Faol", default=True)

    class Meta:
        ordering = ["-is_default", "name"]
        verbose_name = "Ombor"
        verbose_name_plural = "Omborlar"

    def __str__(self):
        return self.name


class DocStatus(models.TextChoices):
    DRAFT = "draft", "Qoralama"
    POSTED = "posted", "Tasdiqlangan"


class NumberedDocument(models.Model):
    """Ketma-ket raqamli hujjat: K-000001, I-000001. Raqam birinchi saqlashdan keyin beriladi."""

    NUMBER_PREFIX = "D"
    Status = DocStatus

    number = models.CharField(max_length=20, unique=True, null=True, blank=True, editable=False)
    warehouse = models.ForeignKey(Warehouse, verbose_name="Ombor", on_delete=models.PROTECT, related_name="+")
    status = models.CharField(max_length=10, choices=DocStatus.choices, default=DocStatus.DRAFT)
    note = models.CharField("Izoh", max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)
    posted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        abstract = True
        ordering = ["-id"]

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        if not self.number:
            self.number = f"{self.NUMBER_PREFIX}-{self.pk:06d}"
            type(self).objects.filter(pk=self.pk).update(number=self.number)

    @property
    def is_draft(self):
        return self.status == DocStatus.DRAFT

    def __str__(self):
        return self.number or f"{self.NUMBER_PREFIX}-?"


class Receipt(NumberedDocument):
    """Kirim hujjati: ta'minotchidan tovar qabul qilish."""

    NUMBER_PREFIX = "K"
    supplier = models.CharField("Ta'minotchi", max_length=150, blank=True)
    date = models.DateField("Sana", default=timezone.localdate)

    class Meta(NumberedDocument.Meta):
        verbose_name = "Kirim hujjati"
        verbose_name_plural = "Kirim hujjatlari"

    @property
    def total(self):
        return sum((line.total for line in self.lines.all()), 0)


class ReceiptLine(models.Model):
    receipt = models.ForeignKey(Receipt, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    product_unit = models.ForeignKey(ProductUnit, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField("Miqdor", max_digits=14, decimal_places=3, default=1)
    unit_cost = models.DecimalField("Tannarx (birlik uchun)", max_digits=14, decimal_places=2, default=0)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["receipt", "product_unit"], name="uniq_line_unit_per_receipt")]

    @property
    def total(self):
        return self.quantity * self.unit_cost

    @property
    def base_quantity(self):
        return self.quantity * self.product_unit.factor


class StockCount(NumberedDocument):
    """Inventarizatsiya: sanalgan haqiqiy qoldiq. Faqat ro'yxatdagi tovarlar tuzatiladi."""

    NUMBER_PREFIX = "I"

    class Meta(NumberedDocument.Meta):
        verbose_name = "Inventarizatsiya"
        verbose_name_plural = "Inventarizatsiyalar"


class StockCountLine(models.Model):
    stock_count = models.ForeignKey(StockCount, on_delete=models.CASCADE, related_name="lines")
    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="+")
    counted_qty = models.DecimalField("Sanalgan (asosiy birlikda)", max_digits=14, decimal_places=3, default=0)
    system_qty = models.DecimalField("Tizimda (tasdiqlash vaqtida)", max_digits=14, decimal_places=3, null=True, blank=True)

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["stock_count", "product"], name="uniq_product_per_count")]


class StockMovement(models.Model):
    """Qoldiq harakati. Qoldiq = harakatlar yig'indisi. Yozuvlar o'zgartirilmaydi:
    xatoni to'g'rilash uchun yangi (tuzatish) harakat qo'shiladi."""

    class Kind(models.TextChoices):
        RECEIPT = "receipt", "Kirim"
        STOCK_COUNT = "stock_count", "Inventarizatsiya"
        ADJUSTMENT = "adjustment", "Tuzatish"
        SALE = "sale", "Sotuv"
        RETURN = "return", "Qaytarish"
        WRITE_OFF = "write_off", "Hisobdan chiqarish"

    product = models.ForeignKey(Product, on_delete=models.PROTECT, related_name="movements")
    warehouse = models.ForeignKey(Warehouse, on_delete=models.PROTECT, related_name="movements")
    quantity = models.DecimalField("Miqdor (asosiy birlikda, ±)", max_digits=14, decimal_places=3)
    kind = models.CharField(max_length=12, choices=Kind.choices)
    unit_cost = models.DecimalField("Tannarx (asosiy birlik uchun)", max_digits=16, decimal_places=4, null=True, blank=True)
    receipt = models.ForeignKey(Receipt, null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    stock_count = models.ForeignKey(StockCount, null=True, blank=True, on_delete=models.PROTECT, related_name="movements")
    note = models.CharField(max_length=300, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-id"]
        indexes = [models.Index(fields=["product", "warehouse"])]
        constraints = [models.CheckConstraint(condition=~models.Q(quantity=0), name="movement_quantity_not_zero")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValueError("Qoldiq harakatlari o'zgartirilmaydi; yangi tuzatish harakati qo'shing.")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Qoldiq harakatlarini o'chirib bo'lmaydi.")
