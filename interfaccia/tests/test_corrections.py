from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from anagrafiche.models import Articolo
from interfaccia.correction_services import AdministrativeCorrectionService
from interfaccia.models import CorrezioneAmministrativa
from magazzino.models import Giacenza, Movimento, RicevimentoLotto
from magazzino.services import MovementService, Position
from produzione.services.demo_seed import seed_demo
from vendite.models import Cliente, RettificaRigaVendita, RigaVendita, Vendita


class CorrectionTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_demo()

    def test_only_administrator_can_open_corrections(self):
        hub = reverse("ui:corrections")
        tables = reverse("ui:correction_tables")
        self.client.force_login(self.demo["users"]["operatore"])
        self.assertEqual(self.client.get(hub).status_code, 403)
        self.assertEqual(self.client.get(tables).status_code, 403)
        self.client.force_login(self.demo["users"]["admin"])
        self.assertEqual(self.client.get(hub).status_code, 200)
        self.assertEqual(self.client.get(tables).status_code, 200)
        self.assertEqual(self.client.get(reverse(
            "ui:correction_table", args=["magazzino", "movimento"],
        )).status_code, 200)
        self.assertEqual(self.client.get(reverse(
            "ui:correct_catalog_record", args=["anagrafiche", "articolo", self.demo["articles"]["FRAGOLE"].pk],
        )).status_code, 200)

    def test_stock_correction_preserves_original_movement(self):
        admin = self.demo["users"]["admin"]
        lot = self.demo["lots"]["F_A"]
        stock = Giacenza.objects.get(lotto=lot, ubicazione=self.demo["locations"]["MAG"])
        original = list(lot.movimenti.values_list("pk", flat=True))
        movement = AdministrativeCorrectionService.correct_stock(
            actor=admin, giacenza=stock, verso="DIMINUZIONE", quantita=Decimal("2"),
            motivazione="Conteggio fisico inferiore di due kg",
        )
        stock.refresh_from_db()
        self.assertEqual(stock.quantita, Decimal("38"))
        self.assertEqual(movement.tipo, Movimento.Tipo.RETTIFICA)
        self.assertTrue(all(lot.movimenti.filter(pk=pk).exists() for pk in original))
        self.assertTrue(CorrezioneAmministrativa.objects.filter(
            modello="magazzino.Giacenza", record_id=str(stock.pk),
        ).exists())

    def test_catalog_change_requires_reason_and_records_values(self):
        admin = self.demo["users"]["admin"]
        article = self.demo["articles"]["FRAGOLE"]
        AdministrativeCorrectionService.correct_catalog_record(
            actor=admin, model=Articolo, record_id=article.pk,
            motivazione="Descrizione corretta dal documento del fornitore",
            descrizione="Fragole gelo selezionate",
        )
        article.refresh_from_db()
        audit = CorrezioneAmministrativa.objects.get(
            modello="anagrafiche.Articolo", record_id=str(article.pk),
        )
        self.assertEqual(article.descrizione, "Fragole gelo selezionate")
        self.assertEqual(audit.valori_precedenti["descrizione"], "FRAGOLE GELO")
        self.assertEqual(audit.valori_nuovi["descrizione"], article.descrizione)

    def test_historical_receipt_can_be_annotated_without_overwriting(self):
        admin = self.demo["users"]["admin"]
        receipt = self.demo["lots"]["F_A"].ricevimenti.get()
        old_ddt = receipt.numero_ddt
        AdministrativeCorrectionService.correct_catalog_record(
            actor=admin, model=RicevimentoLotto, record_id=receipt.pk,
            motivazione="Numero DDT riportato erroneamente",
            annotazione="Il DDT corretto è DDT-456",
        )
        receipt.refresh_from_db()
        self.assertEqual(receipt.numero_ddt, old_ddt)
        self.assertTrue(CorrezioneAmministrativa.objects.filter(
            modello="magazzino.RicevimentoLotto", record_id=str(receipt.pk),
        ).exists())

    def test_sale_line_correction_keeps_original_and_updates_net_quantity(self):
        admin = self.demo["users"]["admin"]
        lot = self.demo["lots"]["F_A"]
        stock = Giacenza.objects.get(lotto=lot, ubicazione=self.demo["locations"]["MAG"])
        customer = Cliente.objects.create(codice="TEST_CLI_CORR", ragione_sociale="Cliente test")
        sale = Vendita.objects.create(
            numero_documento="TEST_DOC_CORR", cliente=customer, registrata_da=admin,
        )
        original = MovementService.register(
            actor=admin, lotto=lot, tipo=Movimento.Tipo.VENDITA, quantita=Decimal("5"),
            origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano),
            note="Vendita di prova", correzione_amministrativa=True,
        )
        line = RigaVendita.objects.create(vendita=sale, movimento=original)
        AdministrativeCorrectionService.correct_sales_line(
            actor=admin, riga=line, nuova_quantita=Decimal("3"), giacenza=stock,
            motivazione="Due kg registrati in più nel documento",
        )
        stock.refresh_from_db()
        original.refresh_from_db()
        self.assertEqual(original.quantita, Decimal("5"))
        self.assertEqual(line.quantita_effettiva, Decimal("3"))
        self.assertEqual(stock.quantita, Decimal("37"))
        self.assertEqual(RettificaRigaVendita.objects.get(riga=line).differenza, Decimal("-2"))
        self.assertTrue(CorrezioneAmministrativa.objects.filter(
            modello="vendite.RigaVendita", record_id=str(line.pk),
        ).exists())
