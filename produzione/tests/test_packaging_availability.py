from decimal import Decimal
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.utils import timezone

from interfaccia.simple_production_forms import PackagingSummaryForm
from produzione.models import SessioneProduzioneSemplificata
from produzione.services import ProduzioneSemplificataService


class PackagingAvailabilityTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username="pack", password="test")
        m = MigrationExecutor(connection).loader.project_state().apps.get_model
        cat = m("anagrafiche", "CategoriaArticolo").objects.create(codice="PF", nome="Finiti")
        article = m("anagrafiche", "Articolo").objects.create(codice="CONF", descrizione="Confettura", categoria=cat, unita_misura="PZ")
        recipe = m("produzione", "Ricetta").objects.create(articolo=article, nome="Confettura", versione="1")
        location = m("anagrafiche", "Ubicazione").objects.create(codice="MAG", nome="Magazzino")
        self.lot = m("magazzino", "Lotto").objects.create(articolo=article, codice_lotto="260913", tipo="PRODUZIONE", stato_prodotto="PRODOTTO_FINITO")
        self.stock = m("magazzino", "Giacenza").objects.create(lotto=self.lot, ubicazione=location, quantita=600)
        sessions = m("produzione", "SessioneProduzioneSemplificata")
        source = sessions.objects.create(tipo="ETICHETTATURA", stato="CHIUSA", ricetta=recipe,
            lotto_codice="260913", lotto_prodotto=self.lot, quantita_finale_kg=600,
            aperta_da_id=self.actor.pk, chiusa_da_id=self.actor.pk, chiusa_il=timezone.now())
        session = sessions.objects.create(tipo="CONFEZIONAMENTO", stato="APERTA", ricetta=recipe,
            lotto_codice="260913", lotto_origine=source, aperta_da_id=self.actor.pk)
        self.session = SessioneProduzioneSemplificata.objects.get(pk=session.pk)

    def close(self, amount):
        return ProduzioneSemplificataService.chiudi_confezionamento(
            actor=self.actor, sessione=self.session, quantita_confezionata=Decimal(amount))

    def test_stock_reduction_limits_form_and_service(self):
        self.stock.quantita = 100
        self.stock.save()
        form = PackagingSummaryForm(session=self.session)
        self.assertEqual(form.remaining, 100)
        with self.assertRaises(ValidationError):
            self.close("600")
        self.assertEqual(self.close("100").quantita_finale_kg, 100)

    def test_stock_is_rechecked_after_form_was_opened(self):
        self.assertEqual(PackagingSummaryForm(session=self.session).remaining, 600)
        self.stock.quantita = 0
        self.stock.save()
        with self.assertRaises(ValidationError):
            self.close("1")
        self.session.refresh_from_db()
        self.assertEqual(self.session.stato, "APERTA")

    def test_current_packed_stock_limits_further_packaging(self):
        self.lot.quantita_confezionata = 550
        self.lot.save()
        self.stock.quantita_confezionata = 550
        self.stock.save()
        with self.assertRaises(ValidationError):
            self.close("51")
        self.close("50")
        self.lot.refresh_from_db()
        self.assertEqual(self.lot.quantita_confezionata, 600)

    def test_quarantined_quantity_is_excluded(self):
        key = (1, self.lot.pk, self.stock.ubicazione_id, "", "")
        with patch("produzione.services.packaging_availability.quarantine_balances", return_value={key: Decimal("500")}):
            self.assertEqual(PackagingSummaryForm(session=self.session).remaining, 100)
            with self.assertRaises(ValidationError):
                self.close("101")

    def test_zero_and_negative_are_rejected(self):
        for value in ("0", "-1"):
            with self.assertRaises(ValidationError):
                self.close(value)
