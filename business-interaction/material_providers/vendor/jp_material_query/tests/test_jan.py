# -*- coding: utf-8 -*-
import unittest

from jpmaterial.jan import is_valid_jan13, normalize_jan, validate_jan


class JanTests(unittest.TestCase):
    def test_normalize(self):
        self.assertEqual(normalize_jan(" 4571608-537527 "), "4571608537527")
        self.assertEqual(normalize_jan(4571608537527), "4571608537527")

    def test_historical_jan_valid(self):
        self.assertTrue(is_valid_jan13("4571608537527"))
        self.assertTrue(validate_jan("4571608537527")[0])

    def test_invalid_check_digit(self):
        ok, reason = validate_jan("4571608537528")
        self.assertFalse(ok)
        self.assertIn("校验位", reason)

    def test_length(self):
        ok, reason = validate_jan("12345")
        self.assertFalse(ok)
        self.assertIn("13", reason)

    def test_empty(self):
        self.assertFalse(validate_jan("")[0])
