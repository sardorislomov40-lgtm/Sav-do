from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from apps.accounts.models import User
from apps.catalog.models import Barcode, Product, ProductUnit, Unit
from apps.inventory.models import (Receipt, ReceiptLine, StockCount, StockCountLine, StockMovement, Warehouse)
from apps.inventory.services import (ServiceError, post_receipt, post_stock_count, product_stock, stock_map)

D = Decimal


class StockTestBase(TestCase):
    def setUp(self):
        self.user = User.objects.create_user("omborchi", password="x12345", role=User.Role.STOREKEEPER)
        self.wh = Warehouse.objects.create(name="Asosiy", is_default=True)
        self.piece = Unit.objects.create(name="Dona", short_name="dona", allows_fraction=False)
        self.kg = Unit.objects.create(name="Kilogramm", short_name="kg", allows_fraction=True)
        self.box = Unit.objects.create(name="Quti", short_name="quti", allows_fraction=False)
        self.milk = Product.objects.create(name="Sut", base_unit=self.piece)
        self.milk_piece = ProductUnit.objects.create(product=self.milk, unit=self.piece, factor=1)
        self.milk_box = ProductUnit.objects.create(product=self.milk, unit=self.box, factor=12)
        self.flour = Product.objects.create(name="Un", base_unit=self.kg)
        self.flour_kg = ProductUnit.objects.create(product=self.flour, unit=self.kg, factor=1)

    def receipt(self, *lines):
        r = Receipt.objects.create(warehouse=self.wh, created_by=self.user)
        for product, pu, qty, cost in lines:
            ReceiptLine.objects.create(receipt=r, product=product, product_unit=pu, quantity=D(qty), unit_cost=D(cost))
        return r


class ReceiptTests(StockTestBase):
    def test_number_assigned(self):
        self.assertEqual(self.receipt().number, "K-%06d" % 1)

    def test_post_converts_boxes_to_base_units_and_cost(self):
        r = self.receipt((self.milk, self.milk_box, "2", "12000"), (self.flour, self.flour_kg, "25.5", "6000"))
        post_receipt(r.pk, self.user)
        self.assertEqual(product_stock(self.milk), D("24"))
        self.assertEqual(product_stock(self.flour), D("25.5"))
        self.assertEqual(StockMovement.objects.get(product=self.milk).unit_cost, D("1000"))
        r.refresh_from_db()
        self.assertEqual(r.status, Receipt.Status.POSTED)

    def test_cannot_post_twice_or_empty(self):
        r = self.receipt((self.milk, self.milk_piece, "5", "1000"))
        post_receipt(r.pk, self.user)
        with self.assertRaises(ServiceError):
            post_receipt(r.pk, self.user)
        with self.assertRaises(ServiceError):
            post_receipt(self.receipt().pk, self.user)
        self.assertEqual(product_stock(self.milk), D("5"))

    def test_fraction_rejected_for_piece_units(self):
        r = self.receipt((self.milk, self.milk_piece, "1.5", "1000"))
        with self.assertRaises(ServiceError):
            post_receipt(r.pk, self.user)
        self.assertEqual(StockMovement.objects.count(), 0)

    def test_movements_are_immutable(self):
        post_receipt(self.receipt((self.milk, self.milk_piece, "5", "1000")).pk, self.user)
        m = StockMovement.objects.get()
        m.quantity = 99
        with self.assertRaises(ValueError):
            m.save()
        with self.assertRaises(ValueError):
            m.delete()


class StockCountTests(StockTestBase):
    def test_count_adjusts_to_counted_quantity(self):
        post_receipt(self.receipt((self.milk, self.milk_piece, "10", "1000")).pk, self.user)
        count = StockCount.objects.create(warehouse=self.wh, created_by=self.user)
        StockCountLine.objects.create(stock_count=count, product=self.milk, counted_qty=D("7"))
        StockCountLine.objects.create(stock_count=count, product=self.flour, counted_qty=D("3.5"))
        post_stock_count(count.pk, self.user)
        totals = stock_map(warehouse=self.wh)
        self.assertEqual(totals[self.milk.pk], D("7"))
        self.assertEqual(totals[self.flour.pk], D("3.5"))
        self.assertEqual(count.lines.get(product=self.milk).system_qty, D("10"))

    def test_equal_count_creates_no_movement(self):
        post_receipt(self.receipt((self.milk, self.milk_piece, "4", "1")).pk, self.user)
        count = StockCount.objects.create(warehouse=self.wh, created_by=self.user)
        StockCountLine.objects.create(stock_count=count, product=self.milk, counted_qty=D("4"))
        before = StockMovement.objects.count()
        post_stock_count(count.pk, self.user)
        self.assertEqual(StockMovement.objects.count(), before)


class ScanFlowTests(StockTestBase):
    def setUp(self):
        super().setUp()
        Barcode.objects.create(code="ABC-PIECE", product=self.milk)
        Barcode.objects.create(code="ABC-BOX", product=self.milk, product_unit=self.milk_box)
        self.client.force_login(self.user)
        self.receipt_obj = Receipt.objects.create(warehouse=self.wh, created_by=self.user)

    def test_scanning_twice_increments_quantity(self):
        url = reverse("inventory:receipt_scan", args=[self.receipt_obj.pk])
        self.assertEqual(self.client.post(url, {"code": "ABC-PIECE"}).status_code, 200)
        self.client.post(url, {"code": "ABC-PIECE"})
        self.client.post(url, {"code": "ABC-BOX"})
        self.assertEqual(self.receipt_obj.lines.get(product_unit=self.milk_piece).quantity, D("2"))
        self.assertEqual(self.receipt_obj.lines.get(product_unit=self.milk_box).quantity, D("1"))

    def test_unknown_code_reports_error_and_adds_nothing(self):
        url = reverse("inventory:receipt_scan", args=[self.receipt_obj.pk])
        resp = self.client.post(url, {"code": "NOPE-1"})
        self.assertContains(resp, "topilmadi")
        self.assertEqual(self.receipt_obj.lines.count(), 0)

    def test_posted_receipt_cannot_be_edited(self):
        self.client.post(reverse("inventory:receipt_scan", args=[self.receipt_obj.pk]), {"code": "ABC-PIECE"})
        post_receipt(self.receipt_obj.pk, self.user)
        resp = self.client.post(reverse("inventory:receipt_scan", args=[self.receipt_obj.pk]), {"code": "ABC-PIECE"})
        self.assertContains(resp, "tasdiqlangan")
        self.assertEqual(self.receipt_obj.lines.get().quantity, D("1"))

    def test_count_scan_adds_box_factor(self):
        count = StockCount.objects.create(warehouse=self.wh, created_by=self.user)
        self.client.post(reverse("inventory:count_scan", args=[count.pk]), {"code": "ABC-BOX"})
        self.client.post(reverse("inventory:count_scan", args=[count.pk]), {"code": "ABC-PIECE"})
        self.assertEqual(count.lines.get(product=self.milk).counted_qty, D("13"))
