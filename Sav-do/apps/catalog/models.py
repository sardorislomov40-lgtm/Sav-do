from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction

from .barcode import build_internal_ean13


class Unit(models.Model):
    name = models.CharField("Nomi", max_length=40, unique=True)
    short_name = models.CharField("Qisqa nomi", max_length=12)
    allows_fraction = models.BooleanField(
        "Kasr miqdor mumkin", default=False, help_text="kg, litr, metr kabi birliklar uchun yoqing"
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "O'lchov birligi"
        verbose_name_plural = "O'lchov birliklari"

    def __str__(self):
        return self.name


class Category(models.Model):
    name = models.CharField("Nomi", max_length=80)
    parent = models.ForeignKey(
        "self", verbose_name="Ota kategoriya", null=True, blank=True,
        on_delete=models.PROTECT, related_name="children",
    )

    class Meta:
        ordering = ["name"]
        verbose_name = "Kategoriya"
        verbose_name_plural = "Kategoriyalar"
        constraints = [models.UniqueConstraint(fields=["parent", "name"], name="uniq_category_name_per_parent")]

    def __str__(self):
        return f"{self.parent} / {self.name}" if self.parent_id else self.name


class Product(models.Model):
    name = models.CharField("Nomi", max_length=200, db_index=True)
    category = models.ForeignKey(
        Category, verbose_name="Kategoriya", null=True, blank=True,
        on_delete=models.SET_NULL, related_name="products",
    )
    base_unit = models.ForeignKey(
        Unit, verbose_name="Asosiy birlik", on_delete=models.PROTECT, related_name="+",
        help_text="Qoldiq shu birlikda yuritiladi. Keyin o'zgartirib bo'lmaydi.",
    )
    sku = models.CharField("Ichki artikul", max_length=40, blank=True)
    min_stock = models.DecimalField(
        "Minimal qoldiq", max_digits=14, decimal_places=3, default=0,
        validators=[MinValueValidator(0)], help_text="Shundan kamaysa, ogohlantiriladi",
    )
    is_active = models.BooleanField("Faol", default=True)
    note = models.TextField("Izoh", blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Tovar"
        verbose_name_plural = "Tovarlar"
        constraints = [
            models.UniqueConstraint(
                fields=["sku"], condition=~models.Q(sku=""), name="uniq_product_sku_when_set"
            )
        ]

    def __str__(self):
        return self.name

    @property
    def base_product_unit(self):
        """Asosiy birlik narxlari (prefetch bilan ham ishlaydi)."""
        return next((pu for pu in self.units.all() if pu.unit_id == self.base_unit_id), None)


class ProductUnit(models.Model):
    """Tovarni sotish birligi va uning narxlari. Asosiy birlikning koeffitsiyenti doim 1."""

    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="units")
    unit = models.ForeignKey(Unit, verbose_name="Birlik", on_delete=models.PROTECT, related_name="+")
    factor = models.DecimalField(
        "Asosiy birlikda necha", max_digits=14, decimal_places=3, default=1,
        validators=[MinValueValidator(Decimal("0.001"))],
        help_text="Masalan: 1 quti = 12 dona bo'lsa, 12",
    )
    retail_price = models.DecimalField("Chakana narx", max_digits=14, decimal_places=2, default=0,
                                       validators=[MinValueValidator(0)])
    wholesale_price = models.DecimalField("Ulgurji narx", max_digits=14, decimal_places=2, default=0,
                                          validators=[MinValueValidator(0)])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["product", "unit"], name="uniq_unit_per_product")]
        verbose_name = "Tovar birligi"
        verbose_name_plural = "Tovar birliklari"

    def __str__(self):
        return f"{self.product} — {self.unit.short_name}"

    @property
    def is_base(self):
        return self.unit_id == self.product.base_unit_id

    def clean(self):
        if self.product_id and self.unit_id == self.product.base_unit_id and self.factor != 1:
            raise ValidationError("Asosiy birlikning koeffitsiyenti 1 bo'lishi kerak")


class Barcode(models.Model):
    class Kind(models.TextChoices):
        FACTORY = "factory", "Zavod kodi"
        INTERNAL = "internal", "Ichki kod"

    code = models.CharField(
        "Kod", max_length=32, unique=True,
        error_messages={"unique": "Bu kod boshqa tovarga biriktirilgan."},
    )
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="barcodes")
    product_unit = models.ForeignKey(
        ProductUnit, verbose_name="Birlik", null=True, blank=True, on_delete=models.CASCADE,
        related_name="barcodes", help_text="Bo'sh bo'lsa, asosiy birlik (masalan, dona)",
    )
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.FACTORY)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["id"]
        verbose_name = "Shtrix-kod"
        verbose_name_plural = "Shtrix-kodlar"

    def __str__(self):
        return self.code


class InternalCodeCounter(models.Model):
    """Ichki EAN-13 kodlar uchun yagona hisoblagich (bitta qator, pk=1)."""

    last_number = models.BigIntegerField(default=0)


@transaction.atomic
def next_internal_code() -> str:
    counter, _ = InternalCodeCounter.objects.select_for_update().get_or_create(pk=1)
    while True:
        counter.last_number += 1
        code = build_internal_ean13(counter.last_number)
        if not Barcode.objects.filter(code=code).exists():
            break
    counter.save(update_fields=["last_number"])
    return code
