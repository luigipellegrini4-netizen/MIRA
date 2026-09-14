from django.contrib.auth import get_user_model
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.utils import timezone

from produzione.services import GenealogyService


class SimpleGenealogyTests(TestCase):
    def setUp(self):
        self.actor = get_user_model().objects.create_superuser(username="trace", password="test")
        self.model = MigrationExecutor(connection).loader.project_state().apps.get_model
        m = self.model
        category = m("anagrafiche", "CategoriaArticolo").objects.create(codice="MOCA", nome="MOCA")
        self.article = m("anagrafiche", "Articolo").objects.create(codice="TEST", descrizione="Test", categoria=category, unita_misura="PZ")
        self.recipe = m("produzione", "Ricetta").objects.create(articolo=self.article, nome="Test", versione="1")
        self.location = m("anagrafiche", "Ubicazione").objects.create(codice="MAG", nome="Magazzino")
        self.supplier = m("anagrafiche", "Fornitore").objects.create(codice="F", ragione_sociale="Fornitore")
        self.raw, self.sl, self.rb, self.inv, self.pf, self.moca = [self.lot(code) for code in ("RAW", "SLV", "RBQB", "INV", "PF", "MOCA")]
        sl = self.session("SEMILAVORATO", self.sl)
        rb = self.session("ROBOQBO", self.rb)
        inv = self.session("INVASETTAMENTO", self.inv, rb)
        label = self.session("ETICHETTATURA", self.pf, inv)
        packaging = self.session("CONFEZIONAMENTO", self.pf, label)
        for source, dest in ((self.raw, sl), (self.sl, rb), (self.inv, label), (self.moca, packaging)):
            m("produzione", "PrelievoSessioneSemplificata").objects.create(
                sessione=dest, lotto=source, quantita_kg=10, registrato_da_id=self.actor.pk)
        client = m("vendite", "Cliente").objects.create(codice="C", ragione_sociale="Cliente finale")
        sale = m("vendite", "Vendita").objects.create(numero_documento="DDT-1", cliente=client, registrata_da_id=self.actor.pk)
        for quantity in (2, 3):
            movement = m("magazzino", "Movimento").objects.create(lotto=self.pf, tipo="VENDITA",
                quantita=quantity, ubicazione_origine=self.location, eseguito_da_id=self.actor.pk)
            m("vendite", "RigaVendita").objects.create(vendita=sale, movimento=movement)

    def lot(self, code):
        return self.model("magazzino", "Lotto").objects.create(articolo=self.article, codice_lotto=code,
            fornitore=self.supplier if code in {"RAW", "MOCA"} else None,
            tipo="ACQUISTO" if code in {"RAW", "MOCA"} else "PRODUZIONE")

    def session(self, kind, lot=None, parent=None):
        return self.model("produzione", "SessioneProduzioneSemplificata").objects.create(
            tipo=kind, ricetta=self.recipe, lotto=lot, lotto_origine=parent,
            stato="CHIUSA", aperta_da_id=self.actor.pk, chiusa_da_id=self.actor.pk, chiusa_il=timezone.now())

    def trace(self, lot, direction):
        return GenealogyService.trace(actor=self.actor, lotto=lot.pk, direzione=direction)

    def test_raw_reaches_finished_lot_and_customer(self):
        graph = self.trace(self.raw, "VALLE")
        self.assertEqual({r["id"] for r in graph["lotti"]}, {self.raw.pk, self.sl.pk, self.rb.pk, self.inv.pk, self.pf.pk})
        self.assertEqual(len(graph["vendite"]), 1)
        self.assertEqual(graph["vendite"][0]["quantita"], "5.000000")
        self.assertEqual(graph["vendite"][0]["cliente"], "Cliente finale")

    def test_packaging_moca_reaches_same_finished_lot(self):
        graph = self.trace(self.moca, "VALLE")
        self.assertEqual({r["id"] for r in graph["lotti"]}, {self.moca.pk, self.pf.pk})
        self.assertEqual(len(graph["vendite"]), 1)

    def test_upstream_contains_raw_and_packaging_moca(self):
        graph = self.trace(self.pf, "MONTE")
        self.assertEqual({r["lotto_id"] for r in graph["materiali_esterni"]}, {self.raw.pk, self.moca.pk})
        self.assertEqual(graph["vendite"], [])
        self.assertFalse(graph["ciclo_materiale_rilevato"])

    def test_ui_displays_downstream_customer_from_raw_material(self):
        self.client.force_login(self.actor)
        response = self.client.get(f"/lotti/{self.raw.pk}/?direzione=VALLE")
        self.assertContains(response, "Cliente finale")
        self.assertContains(response, "DDT-1")
        self.assertContains(response, "Dettaglio dei collegamenti")

    def test_unconsumed_labeling_branch_is_not_reported(self):
        parent = self.model("produzione", "SessioneProduzioneSemplificata").objects.get(tipo="INVASETTAMENTO")
        unrelated = self.lot("UNRELATED")
        self.session("ETICHETTATURA", unrelated, parent)
        graph = self.trace(self.inv, "VALLE")
        self.assertNotIn(unrelated.pk, {r["id"] for r in graph["lotti"]})

    def test_lot_limit_is_preserved(self):
        graph = GenealogyService.trace(actor=self.actor, lotto=self.raw.pk, direzione="VALLE", max_lotti=2)
        self.assertLessEqual(len(graph["lotti"]), 2)
        self.assertTrue(graph["troncato"])
        self.assertEqual(graph["vendite"], [])
