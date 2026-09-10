from datetime import date
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase

from magazzino.models import Giacenza, Lotto, Movimento, RicevimentoLotto
from magazzino.services import Allocation, MovementService, ReceivingService
from .service_fixtures import ServiceFixtures


class ReceivingTests(ServiceFixtures, TestCase):
    def test_first_receipt_creates_lot_receipt_and_load(self):
        result = self.receive(numero_ddt="DDT-1")
        self.assertEqual(result.ricevimento.lotto_id, result.lotto.pk)
        self.assertEqual(result.movimenti[0].lotto_id, result.lotto.pk)
        self.assertEqual(result.ricevimento.numero_ddt, "DDT-1")
        self.assertEqual(Giacenza.objects.get().quantita, 10)

    def test_second_receipt_reuses_lot(self):
        first, second = self.receive(), self.receive(amount="3")
        self.assertEqual(first.lotto.pk, second.lotto.pk)
        self.assertNotEqual(first.ricevimento.pk, second.ricevimento.pk)
        self.assertEqual(Giacenza.objects.get().quantita, 13)
        self.assertEqual(RicevimentoLotto.objects.count(), 2)

    def test_receipt_split_across_locations(self):
        result = ReceivingService.receive(actor=self.warehouse, articolo=self.article, fornitore=self.supplier,
                                         codice_lotto="SPLIT", quantita_ricevuta="10",
                                         destinazioni=[Allocation(self.position, "3"), Allocation(self.destination, "7")])
        self.assertEqual(len(result.movimenti), 2)
        self.assertEqual(Giacenza.objects.get(ubicazione=self.location).quantita, 3)
        self.assertEqual(Giacenza.objects.get(ubicazione=self.other).quantita, 7)

    def test_incoherent_allocation_has_no_effect(self):
        with self.assertRaises(ValidationError):
            ReceivingService.receive(actor=self.warehouse, articolo=self.article, fornitore=self.supplier,
                                     codice_lotto="BAD", quantita_ricevuta="10", destinazioni=[Allocation(self.position, "9")])
        self.assertFalse(Lotto.objects.filter(codice_lotto="BAD").exists())
        self.assertFalse(RicevimentoLotto.objects.exists())

    def test_second_load_failure_rolls_back_everything(self):
        original = MovementService.register
        calls = []

        def fail_second(**kwargs):
            calls.append(kwargs)
            if len(calls) == 2:
                raise ValidationError("Errore sul secondo carico")
            return original(**kwargs)

        with patch.object(MovementService, "register", side_effect=fail_second), self.assertRaises(ValidationError):
            ReceivingService.receive(actor=self.warehouse, articolo=self.article, fornitore=self.supplier,
                                     codice_lotto="ROLLBACK", quantita_ricevuta="10",
                                     destinazioni=[Allocation(self.position, "3"), Allocation(self.destination, "7")])
        self.assertFalse(Lotto.objects.filter(codice_lotto="ROLLBACK").exists())
        self.assertFalse(RicevimentoLotto.objects.exists())
        self.assertFalse(Movimento.objects.exists())
        self.assertFalse(Giacenza.objects.exists())

    def test_technical_lot_when_traceability_disabled(self):
        self.article.tracciabilita_lotto = False
        self.article.save()
        result = self.receive(code=None)
        self.assertTrue(result.lotto.codice_lotto.startswith("TECH-"))
        self.assertEqual(result.lotto.fornitore, self.supplier)
        second = self.receive(code=result.lotto.codice_lotto)
        self.assertEqual(result.lotto.pk, second.lotto.pk)

    def test_missing_supplier_lot_rejected_for_traced_article(self):
        with self.assertRaises(ValidationError):
            self.receive(code=" ")

    def test_existing_expiry_cannot_be_changed(self):
        self.receive(data_scadenza=date(2027, 1, 1))
        with self.assertRaises(ValidationError):
            self.receive(data_scadenza=date(2027, 2, 1))
        self.assertEqual(RicevimentoLotto.objects.count(), 1)
        self.assertEqual(Giacenza.objects.get().quantita, 10)

    def test_omitted_expiry_preserves_existing(self):
        first = self.receive(data_scadenza=date(2027, 1, 1))
        second = self.receive()
        self.assertEqual(first.lotto.data_scadenza, second.lotto.data_scadenza)

    def test_same_iso_date_reuses_existing_lot(self):
        first = self.receive(data_scadenza=date(2027, 1, 1))
        second = self.receive(data_scadenza="2027-01-01")
        self.assertEqual(first.lotto.pk, second.lotto.pk)

    def test_invalid_document_rolls_back_new_lot(self):
        with self.assertRaises(ValidationError):
            self.receive(numero_colli=0)
        self.assertFalse(Lotto.objects.filter(codice_lotto="NEW").exists())

    def test_unknown_document_field_rejected(self):
        with self.assertRaises(ValidationError):
            self.receive(campo_sconosciuto="x")

    def test_inactive_supplier_rejected(self):
        self.supplier.attivo = False
        self.supplier.save()
        with self.assertRaises(ValidationError):
            self.receive()

    def test_inactive_article_rejected(self):
        self.article.attivo = False
        self.article.save()
        with self.assertRaises(ValidationError):
            self.receive()

    def test_operator_cannot_receive(self):
        with self.assertRaises(PermissionDenied):
            ReceivingService.receive(actor=self.operator, articolo=self.article, fornitore=self.supplier,
                                     codice_lotto="NEW", quantita_ricevuta="1", destinazioni=[Allocation(self.position, "1")])
