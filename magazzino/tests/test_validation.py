from decimal import Decimal
from types import SimpleNamespace

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.models.stock import normalizza_codice


class StockValidationTests(SimpleTestCase):
    def test_normalizzazione_posizioni(self):
        self.assertEqual(normalizza_codice(" a01 "), "A01")
        self.assertEqual(normalizza_codice(None), "")

    def test_giacenza_normalizza_codici(self):
        stock = Giacenza(scaffale=" ab ", piano=" p1 ")
        stock.clean()
        self.assertEqual((stock.scaffale, stock.piano), ("AB", "P1"))

    def test_blocco_scrittura_giacenza(self):
        with self.assertRaises(ValidationError):
            Giacenza(quantita=Decimal("1")).save()

    def test_blocco_update_giacenza(self):
        with self.assertRaises(ValidationError):
            Giacenza.objects.all().update(quantita=0)

    def test_blocco_bulk_create_giacenza(self):
        with self.assertRaises(ValidationError):
            Giacenza.objects.bulk_create([Giacenza()])

    def test_blocco_scrittura_movimento(self):
        with self.assertRaises(ValidationError):
            Movimento(quantita=1).save()

    def test_blocco_modifica_storico(self):
        with self.assertRaises(ValidationError):
            Movimento.objects.all().update(note="modifica")

    def test_blocco_cancellazione_storico(self):
        with self.assertRaises(ValidationError):
            Lotto.objects.all().delete()

    def test_rettifica_rifiuta_soli_spazi(self):
        with self.assertRaises(ValidationError):
            Movimento(tipo="RETTIFICA", note="   ").clean()

    def test_codici_senza_ubicazione_rifiutati(self):
        with self.assertRaises(ValidationError):
            Movimento(tipo="CARICO", scaffale_origine="A").clean()

    def test_admin_stock_readonly_anche_per_superuser(self):
        request = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
        for model in (Giacenza, Movimento, Lotto):
            instance = admin.site._registry[model]
            self.assertFalse(instance.has_add_permission(request))
            self.assertFalse(instance.has_change_permission(request))
            self.assertFalse(instance.has_delete_permission(request))
