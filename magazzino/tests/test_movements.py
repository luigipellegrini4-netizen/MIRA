from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError
from django.test import TestCase

from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.services import MovementService, Position
from magazzino.services.movements import InsufficientStock
from .service_fixtures import ServiceFixtures


class MovementTests(ServiceFixtures, TestCase):
    def test_carico_creates_and_increments_stock(self):
        self.load("2")
        self.load("3")
        self.assertEqual(Giacenza.objects.get().quantita, 5)
        self.assertEqual(Movimento.objects.count(), 2)

    def test_transfer_decrements_source_and_increments_target(self):
        self.load()
        move = MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="TRASFERIMENTO", quantita="3", origine=self.position, destinazione=self.destination)
        self.assertEqual(Giacenza.objects.get(ubicazione=self.location).quantita, 7)
        self.assertEqual(Giacenza.objects.get(ubicazione=self.other).quantita, 3)
        self.assertEqual(move.quantita, Decimal("3"))

    def test_transfer_between_shelves_same_location(self):
        self.load()
        MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="TRASFERIMENTO", quantita="4", origine=self.position, destinazione=Position(self.location.pk, "B", "1"))
        self.assertEqual(Giacenza.objects.get(scaffale="A").quantita, 6)
        self.assertEqual(Giacenza.objects.get(scaffale="B").quantita, 4)

    def test_consumption_by_operator(self):
        self.load()
        MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="4", origine=self.position)
        self.assertEqual(Giacenza.objects.get().quantita, 6)

    def test_full_consumption_keeps_zero_row(self):
        self.load()
        MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="10", origine=self.position)
        self.assertEqual(Giacenza.objects.get().quantita, 0)

    def test_insufficient_stock_has_no_partial_effect(self):
        self.load()
        with self.assertRaises(InsufficientStock):
            MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="TRASFERIMENTO", quantita="11", origine=self.position, destinazione=self.destination)
        self.assertEqual(Giacenza.objects.get().quantita, 10)
        self.assertEqual(Movimento.objects.count(), 1)

    def test_missing_source_is_not_created(self):
        with self.assertRaises(InsufficientStock):
            MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="1", origine=self.position)
        self.assertFalse(Giacenza.objects.exists())
        self.assertFalse(Movimento.objects.exists())

    def test_target_write_error_rolls_back_source_and_movement(self):
        self.load()
        original_save = Giacenza.save

        def fail_target(obj, *args, **kwargs):
            if obj.ubicazione_id == self.other.pk:
                raise IntegrityError("Errore simulato dopo salvataggio origine")
            return original_save(obj, *args, **kwargs)

        with patch.object(Giacenza, "save", fail_target), self.assertRaises(IntegrityError):
            MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="TRASFERIMENTO", quantita="3", origine=self.position, destinazione=self.destination)
        self.assertEqual(Giacenza.objects.get().quantita, 10)
        self.assertEqual(Movimento.objects.count(), 1)
        with self.assertRaises(ValidationError):  # il contesto interno è stato ripristinato
            Giacenza.objects.all().update(quantita=1)

    def test_overflow_rejected_before_any_write(self):
        self.load("999999999999.999999")
        with self.assertRaises(ValidationError):
            self.load("0.000001")
        self.assertEqual(Giacenza.objects.get().quantita, Decimal("999999999999.999999"))
        self.assertEqual(Movimento.objects.count(), 1)

    def test_rettifica_positive_and_negative_require_manager(self):
        MovementService.register(actor=self.manager, lotto=self.lot, tipo="RETTIFICA", quantita="5", destinazione=self.position, note="Conteggio fisico iniziale")
        MovementService.register(actor=self.manager, lotto=self.lot, tipo="RETTIFICA", quantita="2", origine=self.position, note="Differenza inventariale")
        self.assertEqual(Giacenza.objects.get().quantita, 3)

    def test_rettifica_requires_reason(self):
        for note in ("", "  "):
            with self.subTest(note=note), self.assertRaises(ValidationError):
                MovementService.register(actor=self.manager, lotto=self.lot, tipo="RETTIFICA", quantita="1", destinazione=self.position, note=note)

    def test_warehouse_quality_operator_and_admin_cannot_adjust(self):
        for actor in (self.warehouse, self.quality, self.operator, self.administrator):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                MovementService.register(actor=actor, lotto=self.lot, tipo="RETTIFICA", quantita="1", destinazione=self.position, note="Conteggio")

    def test_admin_cannot_receive(self):
        with self.assertRaises(PermissionDenied):
            MovementService.register(actor=self.administrator, lotto=self.lot, tipo="CARICO", quantita="1", destinazione=self.position)

    def test_inactive_actor_denied(self):
        self.warehouse.is_active = False
        with self.assertRaises(PermissionDenied):
            self.load()

    def test_invalid_directions_rejected(self):
        for kind, source, target in (("CARICO", self.position, self.destination), ("CONSUMO", None, self.position), ("TRASFERIMENTO", self.position, self.position), ("RETTIFICA", self.position, self.destination)):
            with self.subTest(kind=kind), self.assertRaises(ValidationError):
                MovementService.register(actor=self.manager, lotto=self.lot, tipo=kind, quantita="1", origine=source, destinazione=target, note="Test")
        self.assertFalse(Movimento.objects.exists())

    def test_inactive_destination_rejected_using_fresh_database_state(self):
        self.other.attiva = False
        self.other.save()
        with self.assertRaises(ValidationError):
            self.load(position=self.destination)

    def test_unknown_lot_or_location_rejected(self):
        with self.assertRaises(ValidationError):
            MovementService.register(actor=self.warehouse, lotto=999999, tipo="CARICO", quantita="1", destinazione=self.position)
        with self.assertRaises(ValidationError):
            self.load(position=Position(999999))

    def test_carico_rejects_production_lot(self):
        lot = Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto="P1")
        with self.assertRaises(ValidationError):
            self.load(lot=lot)

    def test_future_workflows_not_bypassed(self):
        for kind in ("PRODUZIONE", "QUARANTENA", "REINTEGRO", "SCARTO", "VENDITA", "TYPO"):
            with self.subTest(kind=kind), self.assertRaises((ValidationError, PermissionDenied)):
                MovementService.register(actor=self.quality, lotto=self.lot, tipo=kind, quantita="1", destinazione=self.position)
