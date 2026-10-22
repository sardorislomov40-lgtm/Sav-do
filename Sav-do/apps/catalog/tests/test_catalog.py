from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.barcode import is_internal_code
from apps.catalog.models import Barcode, Product, ProductUnit, Unit, next_internal_code
from apps.catalog.services import create_internal_barcode, find_by_barcode


def make_unit(name="Dona", short="dona", fraction=False):
    return Unit.objects.get_or_create(name=name, defaults={"short_name": short, "allows_fraction": fraction})[0]


def make_product(name="Sut", unit=None, **kw):
    unit = unit or make_unit()
    product = Product.objects.create(name=name, base_unit=unit, **kw)
    ProductUnit.objects.create(product=product, unit=unit, factor=1, retail_price=1000, wholesale_price=800)
    return product


class InternalBarcodeTests(TestCase):
    def test_codes_are_unique_and_sequential(self):
        a, b = next_internal_code(), next_internal_code()
        self.assertNotEqual(a, b)
        self.assertTrue(is_internal_code(a) and is_internal_code(b))

    def test_create_internal_barcode_is_idempotent(self):
        p = make_product()
        first = create_internal_barcode(p)
        self.assertEqual(first.kind, Barcode.Kind.INTERNAL)
        self.assertEqual(create_internal_barcode(p).pk, first.pk)

    def test_scan_finds_box_unit_by_barcode(self):
        piece, box = make_unit(), make_unit("Quti", "quti")
        p = make_product(unit=piece)
        pu_box = ProductUnit.objects.create(product=p, unit=box, factor=12)
        Barcode.objects.create(code="ABC-BOX", product=p, product_unit=pu_box)
        Barcode.objects.create(code="ABC-PIECE", product=p)
        self.assertEqual(find_by_barcode(" ABC-BOX\n").product_unit.factor, 12)
        self.assertEqual(find_by_barcode("ABC-PIECE").product_unit.factor, 1)
        self.assertIsNone(find_by_barcode("NOPE-1"))


class PermissionTests(TestCase):
    def setUp(self):
        self.cashier = User.objects.create_user("kassir", password="x12345", role=User.Role.CASHIER)
        self.keeper = User.objects.create_user("omborchi", password="x12345", role=User.Role.STOREKEEPER)
        self.admin = User.objects.create_user("admin1", password="x12345", role=User.Role.ADMIN)
        make_unit()

    def test_anonymous_redirected_to_login(self):
        resp = self.client.get(reverse("catalog:product_list"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn("/login/", resp["Location"])

    def test_cashier_can_view_but_not_edit(self):
        self.client.force_login(self.cashier)
        self.assertEqual(self.client.get(reverse("catalog:product_list")).status_code, 200)
        self.assertEqual(self.client.get(reverse("catalog:product_create")).status_code, 403)
        self.assertEqual(self.client.get(reverse("inventory:receipt_list")).status_code, 403)

    def test_storekeeper_can_create_product_but_prices_stay_zero(self):
        self.client.force_login(self.keeper)
        unit = Unit.objects.get(name="Dona")
        data = {
            "name": "Non", "base_unit": unit.pk, "min_stock": "0", "is_active": "on",
            "retail_price": "5000", "wholesale_price": "4000", "make_internal_code": "on",
            "units-TOTAL_FORMS": "0", "units-INITIAL_FORMS": "0", "units-MIN_NUM_FORMS": "0", "units-MAX_NUM_FORMS": "1000",
            "codes-TOTAL_FORMS": "0", "codes-INITIAL_FORMS": "0", "codes-MIN_NUM_FORMS": "0", "codes-MAX_NUM_FORMS": "1000",
        }
        resp = self.client.post(reverse("catalog:product_create"), data)
        self.assertEqual(resp.status_code, 302, getattr(resp, "context", None) and resp.context["form"].errors)
        p = Product.objects.get(name="Non")
        self.assertEqual(p.base_product_unit.retail_price, 0)  # omborchi narx qo'ya olmaydi
        self.assertTrue(p.barcodes.filter(kind=Barcode.Kind.INTERNAL).exists())

    def test_admin_sets_prices(self):
        self.client.force_login(self.admin)
        unit = Unit.objects.get(name="Dona")
        data = {
            "name": "Non", "base_unit": unit.pk, "min_stock": "0", "is_active": "on",
            "retail_price": "5000", "wholesale_price": "4000",
            "units-TOTAL_FORMS": "0", "units-INITIAL_FORMS": "0", "units-MIN_NUM_FORMS": "0", "units-MAX_NUM_FORMS": "1000",
            "codes-TOTAL_FORMS": "1", "codes-INITIAL_FORMS": "0", "codes-MIN_NUM_FORMS": "0", "codes-MAX_NUM_FORMS": "1000",
            "codes-0-code": "4006381333931",
        }
        self.assertEqual(self.client.post(reverse("catalog:product_create"), data).status_code, 302)
        p = Product.objects.get(name="Non")
        self.assertEqual(p.base_product_unit.retail_price, 5000)
        self.assertEqual(p.barcodes.get().code, "4006381333931")

    def test_bad_check_digit_rejected(self):
        self.client.force_login(self.admin)
        unit = Unit.objects.get(name="Dona")
        data = {
            "name": "Non", "base_unit": unit.pk, "min_stock": "0", "retail_price": "1", "wholesale_price": "1",
            "units-TOTAL_FORMS": "0", "units-INITIAL_FORMS": "0", "units-MIN_NUM_FORMS": "0", "units-MAX_NUM_FORMS": "1000",
            "codes-TOTAL_FORMS": "1", "codes-INITIAL_FORMS": "0", "codes-MIN_NUM_FORMS": "0", "codes-MAX_NUM_FORMS": "1000",
            "codes-0-code": "4006381333932",
        }
        self.assertEqual(self.client.post(reverse("catalog:product_create"), data).status_code, 200)
        self.assertFalse(Product.objects.filter(name="Non").exists())
