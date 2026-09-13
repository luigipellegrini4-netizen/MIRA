from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from produzione.tests.test_packaging_availability import PackagingAvailabilityTests


class PackagingAuditTests(TestCase):
    setUp = PackagingAvailabilityTests.setUp

    def test_audit_reports_ambiguous_stock_without_modifying_it(self):
        self.lot.stato_prodotto = "PRODOTTO_FINITO"
        self.lot.quantita_confezionata = 200
        self.lot.save()
        output = StringIO()
        call_command("verifica_confezionamento", stdout=output)
        self.assertIn("DA VERIFICARE", output.getvalue())
        self.assertIn("sessioni confezionamento 0, totale sul lotto 200", output.getvalue())
        self.assertIn("per posizione", output.getvalue())
        self.assertIn("MAG / - / -: 600", output.getvalue())
        self.lot.refresh_from_db()
        self.stock.refresh_from_db()
        self.assertEqual(self.lot.quantita_confezionata, 200)
        self.assertEqual(self.stock.quantita, 600)

    def test_empty_scope_is_reported(self):
        output = StringIO()
        call_command("verifica_confezionamento", stdout=output)
        self.assertIn("Controllati 0 lotti", output.getvalue())
