from decimal import Decimal
from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from qualita.rules import typed_value, evaluate


class QualityRulesTests(SimpleTestCase):
    def test_decimal_negative_and_zero(self):
        for value in ("-3.5", "0", Decimal("12.123456")):
            self.assertEqual(typed_value("DECIMALE", value)[1], Decimal(value))

    def test_invalid_numbers(self):
        for value in (True, 1.2, "NaN", "Infinity", "abc", "1.1234567", "1000000000000"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                typed_value("DECIMALE", value)

    def test_integers(self):
        self.assertEqual(typed_value("INTERO", "-2")[1], -2)
        for value in ("2.1", True, 2**63):
            with self.assertRaises(ValidationError):
                typed_value("INTERO", value)

    def test_boolean_false_is_a_value(self):
        self.assertEqual(typed_value("BOOLEANO", False), ("valore_booleano", False))
        for value in (0, 1, "false"):
            with self.assertRaises(ValidationError):
                typed_value("BOOLEANO", value)

    def test_text(self):
        self.assertEqual(typed_value("TESTO", " abc ")[1], "abc")
        with self.assertRaises(ValidationError):
            typed_value("TESTO", " ")

    def test_inclusive_limits(self):
        req = SimpleNamespace(parametro_controllo=SimpleNamespace(tipo_dato="DECIMALE"), valore_minimo=Decimal("2"), valore_massimo=Decimal("4"))
        for value, expected in ((1, False), (2, True), (4, True), (5, False)):
            self.assertEqual(evaluate(req, value), expected)
        with self.assertRaises(ValidationError):
            evaluate(req, 3, True)

    def test_text_requires_explicit_assessment(self):
        req = SimpleNamespace(parametro_controllo=SimpleNamespace(tipo_dato="TESTO"))
        with self.assertRaises(ValidationError):
            evaluate(req, "ok")
        self.assertFalse(evaluate(req, "difetto", False))
