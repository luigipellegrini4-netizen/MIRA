from decimal import Decimal
from types import SimpleNamespace
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from produzione.services.azienda_common import totals, count, managed_guard
from produzione.models.azienda import azienda_write, in_scope
from qualita.rules import evaluate, typed_value


class AziendaRulesTests(SimpleTestCase):
    def test_rejects_are_in_yield_and_caps_are_additional(self):
        result = totals(buoni=90, scarti=5, capsule_difettose=2, peso_g="100", teorico="10")
        self.assertEqual(result["vasetti"], 95)
        self.assertEqual(result["capsule"], 97)
        self.assertEqual(result["massa_reale"], Decimal("9.5"))
        self.assertEqual(result["massa_buona"], Decimal("9"))
        self.assertEqual(result["resa"], Decimal("95"))

    def test_all_rejected_has_yield_but_no_good_stock(self):
        result = totals(buoni=0, scarti=100, capsule_difettose=0, peso_g="100", teorico="10")
        self.assertEqual(result["resa"], 100)
        self.assertEqual(result["massa_buona"], 0)

    def test_invalid_counts(self):
        for value in (-1, True, "2", 1.5, 2147483648):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                count(value, "Pezzi")

    def test_zero_jars_rejected(self):
        with self.assertRaises(ValidationError):
            totals(buoni=0, scarti=0, capsule_difettose=3, peso_g="100", teorico="10")

    def test_unrepresentable_totals_are_validation_errors(self):
        with self.assertRaises(ValidationError):
            totals(buoni=2147483647, scarti=0, capsule_difettose=0, peso_g="999999999999", teorico="0.000001")

    def test_invalid_weight_and_denominator(self):
        for field in ("peso_g", "teorico"):
            for value in ("0", "-1", "NaN", "Infinity", 1.1):
                args = dict(buoni=1, scarti=0, capsule_difettose=0, peso_g="100", teorico="10")
                args[field] = value
                with self.subTest(field=field, value=value), self.assertRaises(ValidationError):
                    totals(**args)

    def test_brix_strict_bounds(self):
        req = SimpleNamespace(parametro_controllo=SimpleNamespace(tipo_dato="DECIMALE"),
            valore_minimo=Decimal(40), valore_massimo=Decimal(45), minimo_esclusivo=True, massimo_esclusivo=True)
        for value, expected in (("40", False), ("40.000001", True), ("44.999999", True), ("45", False)):
            with self.subTest(value=value):
                self.assertEqual(evaluate(req, Decimal(value)), expected)

    def test_ph_inclusive(self):
        req = SimpleNamespace(parametro_controllo=SimpleNamespace(tipo_dato="DECIMALE"),
            valore_minimo=None, valore_massimo=Decimal("4.1"), minimo_esclusivo=False, massimo_esclusivo=False)
        self.assertTrue(evaluate(req, Decimal("4.1")))
        self.assertFalse(evaluate(req, Decimal("4.100001")))

    def test_na_is_preserved_but_not_conforming(self):
        req = SimpleNamespace(parametro_controllo=SimpleNamespace(tipo_dato="ESITO"))
        for value in ("C", "NC", "NA"):
            self.assertEqual(typed_value("ESITO", value), ("valore_testo", value))
            self.assertEqual(evaluate(req, value), value == "C")
        with self.assertRaises(ValidationError):
            evaluate(req, "NA", True)

    def test_scope_is_specific_nested_and_restored_on_failure(self):
        work = SimpleNamespace(pk=1, tipo_lavorazione=SimpleNamespace(fase_operativa="ROBOQBO"))
        with self.assertRaises(ValidationError):
            managed_guard(work)
        with azienda_write(1):
            managed_guard(work)
            try:
                with azienda_write(2):
                    self.assertTrue(in_scope(1) and in_scope(2))
                    raise ValueError()
            except ValueError:
                pass
            self.assertFalse(in_scope(2))
        self.assertFalse(in_scope(1))
