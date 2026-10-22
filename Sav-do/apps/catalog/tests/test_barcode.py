import unittest
from decimal import Decimal

from apps.catalog.barcode import (build_internal_ean13, gs1_check_digit, is_internal_code,
                                  is_valid_gs1, validate_factory_code)
from apps.catalog.labels import LAYOUTS, LabelItem, build_labels_pdf


class BarcodeTests(unittest.TestCase):
    def test_known_ean13_is_valid(self):
        self.assertEqual(gs1_check_digit("400638133393"), 1)
        self.assertTrue(is_valid_gs1("4006381333931"))
        self.assertFalse(is_valid_gs1("4006381333932"))

    def test_internal_code_format(self):
        code = build_internal_ean13(1)
        self.assertEqual(len(code), 13)
        self.assertTrue(code.startswith("27"))
        self.assertTrue(is_internal_code(code))
        self.assertNotEqual(build_internal_ean13(1), build_internal_ean13(2))

    def test_internal_code_range(self):
        with self.assertRaises(ValueError):
            build_internal_ean13(0)
        with self.assertRaises(ValueError):
            build_internal_ean13(10**10)

    def test_factory_code_validation(self):
        self.assertEqual(validate_factory_code(" 4006381333931\n"), "4006381333931")
        self.assertEqual(validate_factory_code("ABC-123"), "ABC-123")
        for bad in ("4006381333932", "ab", "bu kod!", "x" * 40):
            with self.assertRaises(ValueError):
                validate_factory_code(bad)


class LabelTests(unittest.TestCase):
    def test_pdf_for_every_layout(self):
        items = [LabelItem("Sut 1 l", build_internal_ean13(5), Decimal("12500"), "dona", 3),
                 LabelItem("Нон 400 г", "ABC-123", None, "dona", 1)]
        for key in LAYOUTS:
            self.assertTrue(build_labels_pdf(items, key).startswith(b"%PDF"))

    def test_empty_and_too_many(self):
        with self.assertRaises(ValueError):
            build_labels_pdf([])
        with self.assertRaises(ValueError):
            build_labels_pdf([LabelItem("X", "ABC-123", None, "", 2001)])
