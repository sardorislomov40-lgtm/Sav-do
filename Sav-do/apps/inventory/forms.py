from django import forms

from apps.core.forms import StyledFormMixin

from .models import Receipt, StockCount, Warehouse


class _WarehouseFormMixin(StyledFormMixin):
    def _setup_warehouse(self):
        qs = Warehouse.objects.filter(is_active=True)
        self.fields["warehouse"].queryset = qs
        self.fields["warehouse"].empty_label = None
        default = qs.filter(is_default=True).first() or qs.first()
        if default and not self.is_bound:
            self.initial.setdefault("warehouse", default.pk)


class ReceiptForm(_WarehouseFormMixin, forms.ModelForm):
    class Meta:
        model = Receipt
        fields = ["warehouse", "supplier", "date", "note"]
        widgets = {"date": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_warehouse()


class StockCountForm(_WarehouseFormMixin, forms.ModelForm):
    class Meta:
        model = StockCount
        fields = ["warehouse", "note"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._setup_warehouse()
