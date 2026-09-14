from importlib import import_module
from types import SimpleNamespace
from decimal import Decimal

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.utils import timezone


class FillingQuantityRecoveryTests(TestCase):
    def setUp(self):
        self.apps = MigrationExecutor(connection).loader.project_state().apps
        model = self.apps.get_model
        user = model("auth", "User").objects.create(username="migration-check")
        category = model("anagrafiche", "CategoriaArticolo").objects.create(codice="PF", nome="Finiti")
        article = model("anagrafiche", "Articolo").objects.create(codice="CONF", descrizione="Confettura", categoria=category, unita_misura="PZ")
        recipe = model("produzione", "Ricetta").objects.create(articolo=article, nome="Confettura", versione="1")
        self.location = model("anagrafiche", "Ubicazione").objects.create(codice="MAG", nome="Magazzino")
        self.lot = model("magazzino", "Lotto").objects.create(articolo=article, codice_lotto="INV260913-01", tipo="PRODUZIONE")
        self.session = model("produzione", "SessioneProduzioneSemplificata").objects.create(
            tipo="INVASETTAMENTO", stato="CHIUSA", ricetta=recipe,
            lotto=self.lot, aperta_da=user, chiusa_da=user, chiusa_il=timezone.now(), quantita_finale_kg=138,
        )
        model("produzione", "RiepilogoSessioneSemplificata").objects.create(
            sessione=self.session, vasetti_buoni=600, peso_netto_g=230, registrato_da=user,
        )
        self.movements = model("magazzino", "Movimento")
        self.stocks = model("magazzino", "Giacenza")
        self.movement = self.movements.objects.create(
            lotto=self.lot, tipo="PRODUZIONE", quantita=138, eseguito_da=user,
            sessione_semplificata=self.session, ubicazione_destinazione=self.location,
        )
        self.stock = self.stocks.objects.create(lotto=self.lot, ubicazione=self.location, quantita=138)
        self.user = user

    def recover(self):
        import_module("produzione.migrations.0019_invasettamento_quantita_pezzi").correggi_quantita_invasettate(
            self.apps, SimpleNamespace(connection=connection),
        )

    def test_untouched_lot_is_corrected_once(self):
        self.recover()
        self.recover()
        self.stock.refresh_from_db()
        self.movement.refresh_from_db()
        self.assertEqual(self.stock.quantita, Decimal("600"))
        self.assertEqual(self.movement.quantita, Decimal("600"))

    def test_transferred_lot_keeps_both_positions(self):
        self.movements.objects.create(lotto=self.lot, tipo="TRASFERIMENTO", quantita=69,
            eseguito_da=self.user, ubicazione_origine=self.location, ubicazione_destinazione=self.location,
            scaffale_destinazione="B")
        self.stock.quantita = 69
        self.stock.save()
        other = self.stocks.objects.create(lotto=self.lot, ubicazione=self.location, scaffale="B", quantita=69)
        self.recover()
        self.stock.refresh_from_db()
        other.refresh_from_db()
        self.movement.refresh_from_db()
        self.assertEqual((self.stock.quantita, other.quantita, self.movement.quantita), (69, 69, 138))
