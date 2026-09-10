from datetime import date
from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from anagrafiche.models import Articolo, CategoriaArticolo, Fornitore, Ubicazione
from magazzino.models import Giacenza, Lotto, Movimento, RicevimentoLotto
from magazzino.models.protections import _stock_write


class StockModelTests(TestCase):
    def setUp(self):
        cat = CategoriaArticolo.objects.create(codice="MP", nome="Materie prime")
        self.article = Articolo.objects.create(codice="A", descrizione="Articolo", categoria=cat, unita_misura="KG")
        self.supplier = Fornitore.objects.create(codice="F", ragione_sociale="Fornitore")
        self.lot = Lotto.objects.create(articolo=self.article, fornitore=self.supplier, tipo="ACQUISTO", codice_lotto="L1")
        self.location = Ubicazione.objects.create(codice="MAG", nome="Magazzino")
        self.user = get_user_model().objects.create_user(username="operatore")

    def test_fornitore_obbligatorio_acquisto(self):
        with self.assertRaises(ValidationError):
            Lotto.objects.create(articolo=self.article, tipo="ACQUISTO", codice_lotto="L2")

    def test_produzione_non_ammette_fornitore(self):
        with self.assertRaises(ValidationError):
            Lotto.objects.create(articolo=self.article, fornitore=self.supplier, tipo="PRODUZIONE", codice_lotto="L2")

    def test_acquisto_duplicato_rifiutato(self):
        with self.assertRaises(ValidationError):
            Lotto.objects.create(articolo=self.article, fornitore=self.supplier, tipo="ACQUISTO", codice_lotto="L1")

    def test_stesso_codice_diverso_fornitore_ammesso(self):
        supplier = Fornitore.objects.create(codice="F2", ragione_sociale="Altro")
        lot = Lotto.objects.create(articolo=self.article, fornitore=supplier, tipo="ACQUISTO", codice_lotto="L1")
        self.assertNotEqual(lot.pk, self.lot.pk)

    def test_produzione_univoca_anche_con_fornitore_null(self):
        Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto="P1")
        # La colonna generata protegge il DB anche se full_clean non la valuta.
        with self.assertRaises((IntegrityError, ValidationError)), transaction.atomic():
            Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto="P1")

    def test_acquisto_e_produzione_stesso_codice_ammessi(self):
        Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto="L1")
        self.assertEqual(Lotto.objects.count(), 2)

    def test_date_invertite_rifiutate(self):
        with self.assertRaises(ValidationError):
            Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto="P1", data_produzione=date(2026, 9, 5), data_scadenza=date(2026, 9, 1))

    def test_lotto_non_modificabile(self):
        self.lot.note = "cambiamento"
        with self.assertRaises(ValidationError):
            self.lot.save()

    def test_fornitore_e_articolo_utilizzati_protetti(self):
        for obj in (self.supplier, self.article):
            with self.assertRaises(ProtectedError):
                obj.delete()

    def test_ricevimenti_multipli_stesso_lotto(self):
        for quantity in (2, 3):
            RicevimentoLotto.objects.create(lotto=self.lot, quantita_ricevuta=quantity)
        self.assertEqual(self.lot.ricevimenti.count(), 2)
        self.assertEqual(Giacenza.objects.count(), 0)  # il modello non movimenta stock

    def test_ricevimento_non_positivo(self):
        with self.assertRaises(ValidationError):
            RicevimentoLotto.objects.create(lotto=self.lot, quantita_ricevuta=0)

    def test_ricevimento_produzione_rifiutato(self):
        lot = Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto="P1")
        with self.assertRaises(ValidationError):
            RicevimentoLotto.objects.create(lotto=lot, quantita_ricevuta=1)

    def make_stock(self):
        # Fixture interna per test di schema, NON flusso applicativo.
        with _stock_write():
            return Giacenza.objects.create(lotto=self.lot, ubicazione=self.location, quantita=Decimal("5"), scaffale=" a ", piano=" 1 ")

    def test_stock_normalizzato(self):
        stock = self.make_stock()
        stock.refresh_from_db()
        self.assertEqual((stock.scaffale, stock.piano), ("A", "1"))

    def test_disattivazione_ubicazione_con_stock_rifiutata(self):
        self.make_stock()
        self.location.attiva = False
        with self.assertRaises(ValidationError):
            self.location.save()

    def test_ubicazione_utilizzata_protetta(self):
        self.make_stock()
        with self.assertRaises(ProtectedError):
            self.location.delete()

    def test_db_stock_non_negativo(self):
        stock = self.make_stock()
        with self.assertRaises(IntegrityError), transaction.atomic(), _stock_write():
            Giacenza.objects.filter(pk=stock.pk).update(quantita=-1)
        stock.refresh_from_db()
        self.assertEqual(stock.quantita, 5)

    def test_posizione_univoca(self):
        self.make_stock()
        with self.assertRaises(ValidationError), _stock_write():
            Giacenza.objects.create(lotto=self.lot, ubicazione=self.location, quantita=1, scaffale="A", piano="1")

    def test_direzioni_movimento_invalide(self):
        for kind in ("CARICO", "CONSUMO", "TRASFERIMENTO", "RETTIFICA"):
            move = Movimento(tipo=kind, lotto=self.lot, quantita=1, eseguito_da=self.user, note="test")
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                move.full_clean()

    def test_quantita_movimento_non_positiva(self):
        for quantity in (0, -1):
            move = Movimento(tipo="CARICO", lotto=self.lot, quantita=quantity, eseguito_da=self.user, ubicazione_destinazione=self.location)
            with self.subTest(quantity=quantity), self.assertRaises(ValidationError):
                move.full_clean()

    def test_trasferimento_stessa_posizione_rifiutato(self):
        move = Movimento(tipo="TRASFERIMENTO", lotto=self.lot, quantita=1, eseguito_da=self.user, ubicazione_origine=self.location, ubicazione_destinazione=self.location)
        with self.assertRaises(ValidationError):
            move.full_clean()
