from datetime import datetime, timezone
from decimal import Decimal

from django.test import SimpleTestCase

from produzione.models import ControlloSessioneSemplificata as Control


class ControlOutcomeTests(SimpleTestCase):
    def test_empty_controls_are_incomplete_for_every_type(self):
        for kind in ("BATCH", "TANK", "SEMILAVORATO", "CARRELLO"):
            with self.subTest(kind=kind):
                control = Control(tipo=kind)
                self.assertEqual(control.esito, "Incompleto")
                self.assertFalse(control.conforme)

    def test_batch_requires_times_and_trace(self):
        control = Control(tipo="BATCH", esito_tracciato_termico="C")
        self.assertEqual(control.esito, "Incompleto")
        control.inizio = control.fine = datetime(2026, 9, 13, tzinfo=timezone.utc)
        self.assertEqual(control.esito, "C")

    def test_nc_and_na_take_precedence_over_missing_fields(self):
        for outcome in ("NC", "NA"):
            control = Control(tipo="CARRELLO", esito_pastorizzazione=outcome)
            self.assertEqual(control.esito, "NC")
            self.assertFalse(control.completo)

    def test_tank_limits_and_missing_measurement(self):
        for brix, ph, expected in (("42", None, "Incompleto"), ("40", None, "NC"),
                ("45", "4", "NC"), ("42", "4.1", "C"), ("42", "4.101", "NC")):
            control = Control(tipo="TANK", gradi_brix=Decimal(brix), ph=Decimal(ph) if ph else None)
            self.assertEqual(control.esito, expected)

    def test_both_treatments_required(self):
        for kind in ("SEMILAVORATO", "CARRELLO"):
            control = Control(tipo=kind, esito_pastorizzazione="C")
            self.assertEqual(control.esito, "Incompleto")
            control.esito_shock_vuoto = "C"
            self.assertEqual(control.esito, "C")
