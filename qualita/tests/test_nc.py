from decimal import Decimal
from unittest.mock import patch
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from magazzino.models import Giacenza, Movimento
from magazzino.services import MovementService, Position
from magazzino.selectors import StockProposalService
from magazzino.tests.service_fixtures import ServiceFixtures
from qualita.models import NonConformita, AzioneNonConformita, VerificaNonConformita
from qualita.services import NonConformityService as NC
from qualita.nc_selectors import NonConformitySelector, quarantine_balances


class NonConformityTests(ServiceFixtures, TestCase):
    def case(self, managed=True, **kwargs):
        nc = NC.open(actor=kwargs.pop("actor", self.operator), descrizione="Anomalia da verificare", lotto=kwargs.pop("lotto", self.lot), **kwargs)
        return NC.take_charge(actor=self.quality, non_conformita=nc) if managed else nc

    def act(self, nc, kind="ALTRO", **kwargs):
        return NC.action(actor=kwargs.pop("actor", self.quality), non_conformita=nc, tipo_azione=kind,
                         descrizione="Azione correttiva documentata", **kwargs)

    def verify(self, nc, result="EFFICACE"):
        return NC.verify(actor=self.quality, non_conformita=nc, esito=result, descrizione="Verifica documentata")

    def close(self, nc):
        return NC.close(actor=self.quality, non_conformita=nc, note="Esito verificato e chiusura autorizzata")

    def quarantine(self, nc, amount="4"):
        return self.act(nc, "QUARANTENA", quantita=amount, origine=self.position, destinazione=self.destination)

    def test_open_does_not_move_stock(self):
        self.load()
        before = Movimento.objects.count()
        nc = self.case(managed=False)
        self.assertEqual(nc.stato, "APERTA")
        self.assertEqual(nc.aperta_da, self.operator)
        self.assertEqual(Movimento.objects.count(), before)

    def test_numbers_are_progressive(self):
        a, b = self.case(), self.case()
        self.assertEqual(b.numero, a.numero + 1)

    def test_failed_open_does_not_consume_number(self):
        first = self.case()
        with self.assertRaises(ValidationError):
            self.case(tipo="INVALID")
        self.assertEqual(self.case().numero, first.numero + 1)

    def test_all_operational_roles_can_open(self):
        for actor in (self.operator, self.production, self.quality, self.warehouse, self.manager):
            self.case(actor=actor, managed=False)
        with self.assertRaises(PermissionDenied):
            self.case(actor=self.administrator)

    def test_only_quality_manages(self):
        nc = self.case(managed=False)
        for actor in (self.operator, self.production, self.warehouse, self.manager, self.administrator):
            with self.assertRaises(PermissionDenied):
                NC.take_charge(actor=actor, non_conformita=nc)
            with self.assertRaises(PermissionDenied):
                self.act(nc, actor=actor)
            with self.assertRaises(PermissionDenied):
                NC.verify(actor=actor, non_conformita=nc, esito="EFFICACE", descrizione="Test")
            with self.assertRaises(PermissionDenied):
                NC.close(actor=actor, non_conformita=nc, note="Test")

    def test_action_requires_management(self):
        with self.assertRaises(ValidationError):
            self.act(self.case(managed=False))

    def test_quarantine_moves_and_reserves(self):
        self.load()
        nc = self.case()
        action = self.quarantine(nc)
        self.assertEqual(action.movimento.tipo, "QUARANTENA")
        self.assertEqual(action.movimento.eseguito_da, self.quality)
        self.assertEqual(Giacenza.objects.get(lotto=self.lot, ubicazione=self.location).quantita, 6)
        self.assertEqual(Giacenza.objects.get(lotto=self.lot, ubicazione=self.other).quantita, 4)
        self.assertEqual(sum(quarantine_balances(non_conformita=nc).values()), 4)

    def test_reintegration_releases_only_own_quarantine(self):
        self.load()
        nc = self.case()
        self.quarantine(nc)
        self.act(nc, "REINTEGRO", quantita="3", origine=self.destination, destinazione=self.position)
        self.assertEqual(sum(quarantine_balances(non_conformita=nc).values()), 1)
        self.assertEqual(Giacenza.objects.get(lotto=self.lot, ubicazione=self.location).quantita, 9)

    def test_reintegration_without_quarantine_rejected(self):
        self.load()
        with self.assertRaises(ValidationError):
            self.act(self.case(), "REINTEGRO", quantita="1", origine=self.position, destinazione=self.destination)

    def test_cannot_release_another_nc_quantity(self):
        self.load()
        first, second = self.case(), self.case()
        self.quarantine(first, "3")
        self.quarantine(second, "2")
        with self.assertRaises(ValidationError):
            self.act(second, "REINTEGRO", quantita="3", origine=self.destination, destinazione=self.position)
        with self.assertRaises(ValidationError):
            self.act(second, "SCARTO", quantita="3", origine=self.destination)
        self.assertEqual(sum(quarantine_balances(lotto=self.lot).values()), 5)

    def test_scrap_of_quarantined_quantity(self):
        self.load()
        nc = self.case()
        self.quarantine(nc)
        self.act(nc, "SCARTO", quantita="4", origine=self.destination)
        self.assertFalse(quarantine_balances(non_conformita=nc))
        self.assertEqual(sum(Giacenza.objects.values_list("quantita", flat=True)), 6)

    def test_scrap_can_remove_free_stock(self):
        self.load()
        action = self.act(self.case(), "SCARTO", quantita="2", origine=self.position)
        self.assertEqual(action.movimento.tipo, "SCARTO")
        self.assertEqual(Giacenza.objects.get(lotto=self.lot).quantita, 8)

    def test_mixed_free_and_quarantine_position(self):
        self.load()
        nc = self.case()
        self.quarantine(nc)
        MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="TRASFERIMENTO", quantita="2", origine=self.position, destinazione=self.destination)
        MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="2", origine=self.destination)
        with self.assertRaises(ValidationError):
            MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="1", origine=self.destination)
        self.assertEqual(sum(quarantine_balances(lotto=self.lot).values()), 4)

    def test_normal_operations_cannot_bypass_quarantine(self):
        self.load()
        self.quarantine(self.case())
        for kind, actor, target in (("CONSUMO", self.operator, None), ("TRASFERIMENTO", self.warehouse, self.position), ("RETTIFICA", self.manager, None)):
            with self.assertRaises(ValidationError):
                MovementService.register(actor=actor, lotto=self.lot, tipo=kind, quantita="1", origine=self.destination, destinazione=target, note="Tentativo")

    def test_proposal_excludes_quarantine(self):
        self.load()
        self.quarantine(self.case())
        proposal = StockProposalService.propose(actor=self.operator, articolo=self.article, quantita="10")
        self.assertEqual(proposal.mancante, 4)
        self.assertEqual(sum(line.quantita for line in proposal.righe), 6)

    def test_direct_quality_movements_rejected(self):
        self.load()
        for kind in ("QUARANTENA", "REINTEGRO", "SCARTO"):
            with self.assertRaises(ValidationError):
                MovementService.register(actor=self.quality, lotto=self.lot, tipo=kind, quantita="1", origine=self.position, destinazione=self.destination)

    def test_adjustment_not_an_nc_action(self):
        with self.assertRaises(ValidationError):
            self.act(self.case(), "RETTIFICA")

    def test_insufficient_stock_rolls_back_action(self):
        self.load("2")
        nc = self.case()
        with self.assertRaises(ValidationError):
            self.quarantine(nc, "3")
        self.assertFalse(nc.azioni.exists())
        self.assertEqual(Movimento.objects.count(), 1)
        self.assertEqual(Giacenza.objects.get(lotto=self.lot).quantita, 2)

    def test_action_save_failure_rolls_back_movement(self):
        self.load()
        nc = self.case()
        with patch.object(AzioneNonConformita, "save", side_effect=ValidationError("Errore simulato")):
            with self.assertRaises(ValidationError):
                self.quarantine(nc)
        self.assertEqual(Movimento.objects.count(), 1)
        self.assertEqual(Giacenza.objects.count(), 1)
        self.assertEqual(Giacenza.objects.get(lotto=self.lot).quantita, 10)

    def test_nonphysical_action_rejects_stock_arguments(self):
        with self.assertRaises(ValidationError):
            self.act(self.case(), quantita="2")

    def test_rework_requires_work_reference(self):
        with self.assertRaises(ValidationError):
            self.act(self.case(), "RILAVORAZIONE")

    def test_effective_verification_does_not_close(self):
        nc = self.case()
        self.act(nc)
        self.verify(nc)
        nc.refresh_from_db()
        self.assertEqual(nc.stato, "IN_GESTIONE")
        self.assertEqual(self.close(nc).stato, "CHIUSA")

    def test_closure_requires_latest_effective_verification(self):
        nc = self.case()
        self.act(nc)
        with self.assertRaises(ValidationError):
            self.close(nc)
        self.verify(nc)
        self.verify(nc, "NON_EFFICACE")
        with self.assertRaises(ValidationError):
            self.close(nc)
        self.verify(nc)
        self.close(nc)

    def test_new_action_invalidates_previous_verification(self):
        nc = self.case()
        self.act(nc)
        self.verify(nc)
        self.act(nc)
        with self.assertRaises(ValidationError):
            self.close(nc)

    def test_cannot_close_with_outstanding_quarantine(self):
        self.load()
        nc = self.case()
        self.quarantine(nc)
        self.verify(nc)
        with self.assertRaises(ValidationError):
            self.close(nc)
        self.act(nc, "SCARTO", quantita="4", origine=self.destination)
        self.verify(nc)
        self.close(nc)

    def test_verification_requires_action(self):
        with self.assertRaises(ValidationError):
            self.verify(self.case())

    def test_closed_nc_rejects_all_new_operations(self):
        nc = self.case()
        self.act(nc)
        self.verify(nc)
        nc = self.close(nc)
        for operation in (lambda: self.act(nc), lambda: self.verify(nc), lambda: self.close(nc), lambda: NC.take_charge(actor=self.quality, non_conformita=nc)):
            with self.assertRaises(ValidationError):
                operation()

    def test_history_is_immutable(self):
        nc = self.case()
        action = self.act(nc)
        verification = self.verify(nc)
        for obj in (nc, action, verification):
            for operation in (obj.save, obj.delete, lambda: type(obj).objects.all().update(note="x"), lambda: type(obj).objects.all().delete()):
                with self.assertRaises(ValidationError):
                    operation()

    def test_no_direct_model_write_permissions(self):
        for actor in (self.administrator, self.production, self.quality, self.operator):
            for model in ("nonconformita", "azionenonconformita", "verificanonconformita"):
                self.assertFalse(actor.has_perm(f"qualita.add_{model}"))
                self.assertFalse(actor.has_perm(f"qualita.change_{model}"))
        self.assertFalse(self.administrator.has_perm("qualita.view_nonconformita"))
        self.assertTrue(self.warehouse.has_perm("qualita.view_nonconformita"))

    def test_selector_includes_residual_quarantine(self):
        self.load()
        nc = self.case()
        self.quarantine(nc)
        detail = NonConformitySelector.detail(actor=self.warehouse, non_conformita=nc)
        self.assertEqual(Decimal(detail["quarantena_residua"][0]["quantita"]), 4)
        self.assertEqual(len(detail["azioni"]), 1)
        with self.assertRaises(PermissionDenied):
            NonConformitySelector.detail(actor=self.administrator, non_conformita=nc)

    def test_description_and_closure_reason_required(self):
        with self.assertRaises(ValidationError):
            NC.open(actor=self.operator, descrizione=" ")
        nc = self.case()
        with self.assertRaises(ValidationError):
            NC.close(actor=self.quality, non_conformita=nc, note=" ")
