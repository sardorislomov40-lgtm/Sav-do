from decimal import Decimal

from django import forms
from django.core.exceptions import ValidationError
from django.forms import BaseInlineFormSet, inlineformset_factory

from apps.core.forms import StyledFormMixin

from .barcode import validate_factory_code
from .models import Barcode, Category, Product, ProductUnit, Unit


class ProductForm(StyledFormMixin, forms.ModelForm):
    retail_price = forms.DecimalField(
        label="Chakana narx", min_value=0, max_digits=14, decimal_places=2, required=False, initial=0
    )
    wholesale_price = forms.DecimalField(
        label="Ulgurji narx", min_value=0, max_digits=14, decimal_places=2, required=False, initial=0
    )
    make_internal_code = forms.BooleanField(
        label="Tovarda kod yo'q: ichki shtrix-kod yaratilsin", required=False
    )

    class Meta:
        model = Product
        fields = ["name", "category", "base_unit", "sku", "min_stock", "is_active", "note"]
        widgets = {"note": forms.Textarea(attrs={"rows": 2})}

    def __init__(self, *args, can_edit_prices=True, **kwargs):
        super().__init__(*args, **kwargs)
        self.can_edit_prices = can_edit_prices
        self.fields["base_unit"].queryset = Unit.objects.all()
        if self.instance.pk:
            # Qoldiq asosiy birlikda yuritiladi: harakatlar boshlangach o'zgartirilmaydi
            self.fields["base_unit"].disabled = True
            del self.fields["make_internal_code"]
            pu = self.instance.base_product_unit
            if pu:
                self.initial["retail_price"] = pu.retail_price
                self.initial["wholesale_price"] = pu.wholesale_price
        if not can_edit_prices:
            self.fields["retail_price"].disabled = True
            self.fields["wholesale_price"].disabled = True
            self.fields["retail_price"].help_text = "Narxni faqat Admin o'zgartiradi"

    def clean_name(self):
        return " ".join(self.cleaned_data["name"].split())

    def save(self, commit=True):
        product = super().save(commit=True)
        retail = self.cleaned_data.get("retail_price") or Decimal("0")
        wholesale = self.cleaned_data.get("wholesale_price") or Decimal("0")
        pu, created = ProductUnit.objects.get_or_create(
            product=product, unit=product.base_unit,
            defaults={"factor": 1, "retail_price": retail, "wholesale_price": wholesale},
        )
        if not created and self.can_edit_prices:
            pu.retail_price, pu.wholesale_price = retail, wholesale
            pu.save(update_fields=["retail_price", "wholesale_price"])
        return product


class ProductUnitForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = ProductUnit
        fields = ["unit", "factor", "retail_price", "wholesale_price"]


class BaseProductUnitFormSet(BaseInlineFormSet):
    base_unit_id = None
    can_edit_prices = True

    def add_fields(self, form, index):
        super().add_fields(form, index)
        if not self.can_edit_prices:
            form.fields["retail_price"].disabled = True
            form.fields["wholesale_price"].disabled = True

    def clean(self):
        super().clean()
        seen = set()
        for form in self.forms:
            data = getattr(form, "cleaned_data", {})
            unit = data.get("unit")
            if unit is None or data.get("DELETE"):
                continue
            if unit.pk == self.base_unit_id:
                raise ValidationError("Asosiy birlik yuqorida kiritilgan, uni bu yerga qo'shmang.")
            if unit.pk in seen:
                raise ValidationError(f"«{unit.name}» birligi ikki marta kiritilgan.")
            seen.add(unit.pk)


ProductUnitFormSet = inlineformset_factory(
    Product, ProductUnit, form=ProductUnitForm, formset=BaseProductUnitFormSet,
    extra=1, can_delete=True,
)


class BarcodeForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Barcode
        fields = ["code", "product_unit"]

    def clean_code(self):
        try:
            return validate_factory_code(self.cleaned_data["code"])
        except ValueError as exc:
            raise ValidationError(str(exc))


class BaseBarcodeFormSet(BaseInlineFormSet):
    def add_fields(self, form, index):
        super().add_fields(form, index)
        field = form.fields["product_unit"]
        field.queryset = (
            ProductUnit.objects.filter(product=self.instance).select_related("unit")
            if self.instance.pk
            else ProductUnit.objects.none()
        )
        field.empty_label = "Asosiy birlik"
        field.label_from_instance = lambda pu: f"{pu.unit.name} (×{pu.factor.normalize():f})"


BarcodeFormSet = inlineformset_factory(
    Product, Barcode, form=BarcodeForm, formset=BaseBarcodeFormSet, extra=2, can_delete=True,
)


class CategoryForm(StyledFormMixin, forms.ModelForm):
    class Meta:
        model = Category
        fields = ["name", "parent"]
