from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from magazzino.models import Giacenza, Movimento
from magazzino.services import Allocation
from produzione.models import (UnitaLavorazione, RisorsaLavorazione, PartecipazioneUnitaLavorazione,
    RisorsaProduttiva, TipoLavorazione, RequisitoFaseUnitaTipoLavorazione)
from produzione.services import WorkUnitService, ResourceService, WorkExecutionService, OutputService, ProductionCycleService
from qualita.services import QualityService
from .unit_fixtures import setup_units


class UnitTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        setup_units(cls)

    def unit(self, **kwargs):
        return WorkUnitService.create(actor=kwargs.pop("actor", self.operator), lavorazione_origine=self.origin,
                                      lotto=self.inv_lot, **kwargs)

    def participate(self, unit, work):
        return WorkUnitService.participate(actor=self.operator, unita_lavorazione=unit, lavorazione=work)

    def finish(self, work):
        return WorkExecutionService.complete(actor=self.operator, lavorazione=work)

    def start(self, work):
        return WorkExecutionService.start(actor=self.operator, lavorazione=work)

    def close(self, unit):
        return WorkUnitService.close(actor=self.operator, unita_lavorazione=unit)

    def output(self, amount="10"):
        return OutputService.register(actor=self.operator, lavorazione=self.origin, requisito_output=self.output_req,
            lotto=self.inv_lot, quantita=amount, destinazioni=[Allocation(self.destination, amount)])

    def process(self, units):
        self.start(self.heat)
        for unit in units:
            self.participate(unit, self.heat)
        self.finish(self.heat)
        self.start(self.cool)
        for unit in units:
            self.participate(unit, self.cool)
        QualityService.record(actor=self.operator, lavorazione=self.cool, controllo_richiesto=self.quality_req, valore=True)
        self.finish(self.cool)

    def test_two_carts_full_route_then_output(self):
        first = self.unit(codice="U1", quantita="4", risorsa_produttiva=self.cart)
        second = self.unit(codice="U2", quantita="6")
        self.assertFalse(Giacenza.objects.exists())
        self.process([first, second])
        self.assertFalse(Movimento.objects.exists())
        self.close(first)
        self.close(second)
        self.output()
        self.finish(self.origin)
        self.assertEqual(PartecipazioneUnitaLavorazione.objects.count(), 4)
        self.assertEqual(Giacenza.objects.get(lotto=self.inv_lot).quantita, Decimal("10"))
        self.assertEqual(Movimento.objects.count(), 1)
        self.assertEqual(ProductionCycleService.complete(actor=self.production, ciclo=self.cycle).stato, "COMPLETATO")

    def test_quantity_and_resource_optional(self):
        unit = self.unit()
        self.assertIsNone(unit.quantita)
        self.assertIsNone(unit.risorsa_produttiva)

    def test_invalid_quantities(self):
        for amount in ("0", "-1", True, 1.5, "NaN"):
            with self.assertRaises(ValidationError):
                self.unit(quantita=amount)

    def test_same_cart_cannot_hold_two_active_units(self):
        self.unit(risorsa_produttiva=self.cart)
        with self.assertRaises(ValidationError):
            self.unit(risorsa_produttiva=self.cart)
        self.assertEqual(UnitaLavorazione.objects.count(), 1)

    def test_resource_reusable_after_unit_closed(self):
        unit = self.unit(risorsa_produttiva=self.cart)
        self.process([unit])
        self.close(unit)
        self.assertIsNotNone(self.unit(risorsa_produttiva=self.cart).pk)

    def test_inactive_resource_rejected(self):
        self.cart.attiva = False
        self.cart.save()
        with self.assertRaises(ValidationError):
            self.unit(risorsa_produttiva=self.cart)

    def test_resource_cannot_be_disabled_while_occupied(self):
        self.unit(risorsa_produttiva=self.cart)
        self.cart.attiva = False
        with self.assertRaises(ValidationError):
            self.cart.save()

    def test_purchase_lot_not_valid_origin(self):
        with self.assertRaises(ValidationError):
            WorkUnitService.create(actor=self.operator, lavorazione_origine=self.origin, lotto=self.lot)

    def test_closed_origin_rejects_new_unit(self):
        unit = self.unit()
        self.process([unit])
        self.close(unit)
        self.output()
        self.finish(self.origin)
        with self.assertRaises(ValidationError):
            self.unit()

    def test_required_units_missing(self):
        self.output()
        with self.assertRaisesMessage(ValidationError, "almeno un'unità"):
            self.finish(self.origin)

    def test_incomplete_route_blocks_unit_closure(self):
        unit = self.unit()
        with self.assertRaises(ValidationError):
            self.close(unit)

    def test_active_unit_blocks_origin(self):
        unit = self.unit()
        self.process([unit])
        self.output()
        with self.assertRaisesMessage(ValidationError, "Chiudere l'unità"):
            self.finish(self.origin)

    def test_each_unit_must_complete_route(self):
        first, second = self.unit(), self.unit()
        self.process([first])
        self.close(first)
        with self.assertRaises(ValidationError):
            self.close(second)

    def test_route_order_enforced(self):
        unit = self.unit()
        self.start(self.cool)
        with self.assertRaisesMessage(ValidationError, "precedenti"):
            self.participate(unit, self.cool)

    def test_phase_requires_participation(self):
        self.start(self.heat)
        with self.assertRaisesMessage(ValidationError, "partecipazione"):
            self.finish(self.heat)

    def test_quality_blocks_treatment_and_origin(self):
        unit = self.unit()
        self.start(self.heat)
        self.participate(unit, self.heat)
        self.finish(self.heat)
        self.start(self.cool)
        self.participate(unit, self.cool)
        with self.assertRaises(ValidationError):
            self.finish(self.cool)
        QualityService.record(actor=self.operator, lavorazione=self.cool, controllo_richiesto=self.quality_req, valore=False)
        with self.assertRaises(ValidationError):
            self.finish(self.cool)
        with self.assertRaises(ValidationError):
            self.close(unit)

    def test_cannot_participate_in_two_running_works(self):
        unit = self.unit()
        other = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.heat_kind)
        self.start(self.heat)
        self.start(other)
        self.participate(unit, self.heat)
        with self.assertRaises(ValidationError):
            self.participate(unit, other)

    def test_participation_cannot_be_added_retroactively(self):
        first, second = self.unit(), self.unit()
        self.start(self.heat)
        self.participate(first, self.heat)
        self.finish(self.heat)
        with self.assertRaises(ValidationError):
            self.participate(second, self.heat)

    def test_closed_unit_cannot_be_reopened(self):
        unit = self.unit()
        self.process([unit])
        unit = self.close(unit)
        unit.stato = "ATTIVA"
        with self.assertRaises(ValidationError):
            unit.save()
        with self.assertRaises(ValidationError):
            self.close(unit)

    def test_quantity_above_existing_output_rejected(self):
        self.output("5")
        self.unit(quantita="4")
        with self.assertRaises(ValidationError):
            self.unit(quantita="2")

    def test_output_must_cover_known_unit_quantities(self):
        unit = self.unit(quantita="6")
        self.process([unit])
        self.close(unit)
        self.output("5")
        with self.assertRaisesMessage(ValidationError, "superano"):
            self.finish(self.origin)

    def test_resource_assignment_has_no_stock_effect(self):
        record = ResourceService.assign(actor=self.operator, lavorazione=self.origin, risorsa_produttiva=self.machine)
        self.assertEqual(record.risorsa_produttiva, self.machine)
        self.assertFalse(Movimento.objects.exists())
        with self.assertRaises(ValidationError):
            ResourceService.assign(actor=self.operator, lavorazione=self.origin, risorsa_produttiva=self.machine)

    def test_used_resource_identity_frozen(self):
        ResourceService.assign(actor=self.operator, lavorazione=self.origin, risorsa_produttiva=self.machine)
        self.machine.tipo = "ALTRO"
        with self.assertRaises(ValidationError):
            self.machine.save()

    def test_roles(self):
        for actor in (self.administrator, self.quality, self.warehouse, self.manager):
            with self.assertRaises(PermissionDenied):
                self.unit(actor=actor)
            with self.assertRaises(PermissionDenied):
                ResourceService.assign(actor=actor, lavorazione=self.origin, risorsa_produttiva=self.machine)
        self.unit(actor=self.production)

    def test_config_permissions(self):
        self.assertTrue(self.administrator.has_perm("produzione.add_risorsaproduttiva"))
        self.assertTrue(self.production.has_perm("produzione.add_requisitofaseunitatipolavorazione"))
        self.assertFalse(self.operator.has_perm("produzione.add_risorsaproduttiva"))
        self.assertFalse(self.production.has_perm("produzione.add_unitalavorazione"))
        self.assertTrue(self.quality.has_perm("produzione.view_unitalavorazione"))

    def test_history_protected(self):
        unit = self.unit()
        self.start(self.heat)
        participation = self.participate(unit, self.heat)
        resource = ResourceService.assign(actor=self.operator, lavorazione=self.heat, risorsa_produttiva=self.machine)
        for obj in (unit, participation, resource):
            with self.assertRaises(ValidationError):
                obj.delete()
            with self.assertRaises(ValidationError):
                obj.save()
            with self.assertRaises(ValidationError):
                type(obj).objects.all().update(note="Alterato")

    def test_used_route_frozen(self):
        self.heat_route.obbligatorio = False
        with self.assertRaises(ValidationError):
            self.heat_route.save()
        with self.assertRaises(ValidationError):
            self.cool_route.delete()

    def test_treatment_configuration_frozen_by_route(self):
        self.heat_kind.nome = "Altro"
        with self.assertRaises(ValidationError):
            self.heat_kind.save()

    def test_generating_work_cannot_be_treatment(self):
        with self.assertRaises(ValidationError):
            self.participate(self.unit(), self.origin)

    def test_unconfigured_treatment_rejected_when_route_exists(self):
        kind = TipoLavorazione.objects.create(codice="EXTRA", nome="Extra", genera_lotto=False)
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=kind)
        self.start(work)
        with self.assertRaises(ValidationError):
            self.participate(self.unit(), work)

    def test_route_rejects_generating_phase(self):
        source = TipoLavorazione.objects.create(codice="NEW_SOURCE", nome="Origine")
        with self.assertRaises(ValidationError):
            RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=source, tipo_fase=self.origin_kind)

    def test_route_rejects_non_generating_origin(self):
        source = TipoLavorazione.objects.create(codice="NEW_SOURCE", nome="Origine", genera_lotto=False)
        with self.assertRaises(ValidationError):
            RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=source, tipo_fase=self.heat_kind)

    def test_route_rejects_same_type(self):
        with self.assertRaises(ValidationError):
            RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=self.origin_kind, tipo_fase=self.origin_kind)

    def test_route_unique_order_and_phase(self):
        source = TipoLavorazione.objects.create(codice="NEW_SOURCE", nome="Origine")
        RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=source, tipo_fase=self.heat_kind, ordine=10)
        for phase, order in ((self.heat_kind, 20), (self.cool_kind, 10)):
            with self.assertRaises(ValidationError):
                RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=source, tipo_fase=phase, ordine=order)

    def test_selector_displays_each_phase_and_protects_access(self):
        from produzione.selectors import UnitSelector
        unit = self.unit()
        detail = UnitSelector.detail(actor=self.quality, unita_lavorazione=unit)
        self.assertEqual([r["completata"] for r in detail["percorso"]], [False, False])
        self.process([unit])
        detail = UnitSelector.detail(actor=self.quality, unita_lavorazione=unit)
        self.assertEqual([r["completata"] for r in detail["percorso"]], [True, True])
        with self.assertRaises(PermissionDenied):
            UnitSelector.detail(actor=self.administrator, unita_lavorazione=unit)

    def test_participation_can_use_another_open_cycle(self):
        cycle = ProductionCycleService.create(actor=self.production, articolo=self.article)
        work = WorkExecutionService.plan(actor=self.production, ciclo=cycle, tipo_lavorazione=self.heat_kind)
        self.start(work)
        self.participate(self.unit(), work)
        self.finish(work)

    def test_interrupted_treatment_requires_new_completed_attempt(self):
        unit = self.unit()
        self.start(self.heat)
        self.participate(unit, self.heat)
        WorkExecutionService.interrupt(actor=self.operator, lavorazione=self.heat, note="Interruzione tecnica")
        with self.assertRaises(ValidationError):
            self.close(unit)
        repeat = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.heat_kind)
        self.start(repeat)
        self.participate(unit, repeat)
        self.finish(repeat)
        self.assertEqual(unit.partecipazioni.count(), 2)

    def test_interruption_and_repeat_do_not_erase_nonconformity(self):
        unit = self.unit()
        self.start(self.heat)
        self.participate(unit, self.heat)
        self.finish(self.heat)
        self.start(self.cool)
        self.participate(unit, self.cool)
        QualityService.record(actor=self.operator, lavorazione=self.cool, controllo_richiesto=self.quality_req, valore=False)
        WorkExecutionService.interrupt(actor=self.operator, lavorazione=self.cool, note="Esito negativo")
        repeat = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.cool_kind)
        self.start(repeat)
        self.participate(unit, repeat)
        QualityService.record(actor=self.operator, lavorazione=repeat, controllo_richiesto=self.quality_req, valore=True)
        self.finish(repeat)
        with self.assertRaisesMessage(ValidationError, "non conformità storica"):
            self.close(unit)
