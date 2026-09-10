from datetime import date
from decimal import Decimal
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.test import RequestFactory
from django.contrib import admin

from anagrafiche.models import Articolo
from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.services import Allocation, LotGenerationService, MovementService
from magazzino.tests.service_fixtures import ServiceFixtures
from produzione.models import (CicloProduzione, Lavorazione, TipoLavorazione, Ricetta,
                               RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione,
                               InputLavorazione, OutputLavorazione)
from produzione.services import ProductionCycleService, WorkExecutionService, InputService, OutputService


class ExecutionServicesTests(ServiceFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.product = Articolo.objects.create(codice="PRODOTTO", descrizione="Prodotto", categoria=cls.category, unita_misura="KG")
        cls.kind = TipoLavorazione.objects.create(codice="MIX", nome="Miscelazione")
        cls.input_req = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, nome="Materia prima", articolo=cls.article)
        cls.output_req = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, nome="Prodotto", articolo=cls.product, prefisso_lotto="INT")
        cls.recipe = Ricetta.objects.create(articolo=cls.product, nome="Formula", versione="1")
        cls.cycle = ProductionCycleService.create(actor=cls.production, articolo=cls.product)
        cls.work = WorkExecutionService.plan(actor=cls.production, ciclo=cls.cycle, tipo_lavorazione=cls.kind, ricetta=cls.recipe)

    def start(self):
        self.work = WorkExecutionService.start(actor=self.operator, lavorazione=self.work)

    def consume(self, amount="5", origins=None):
        return InputService.register(actor=self.operator, lavorazione=self.work, requisito_input=self.input_req,
                                     lotto=self.lot, quantita=amount, origini=origins or [Allocation(self.position, amount)])

    def produce(self, amount="4", **kwargs):
        return OutputService.register(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req,
                                      articolo=self.product, quantita=amount, destinazioni=[Allocation(self.destination, amount)], **kwargs)

    def record_materials(self):
        self.start()
        self.load()
        consumed = self.consume()
        produced = self.produce()
        return consumed, produced

    def test_operator_cannot_create_cycle(self):
        with self.assertRaises(PermissionDenied):
            ProductionCycleService.create(actor=self.operator, articolo=self.product)

    def test_pure_admin_cannot_plan_production(self):
        with self.assertRaises(PermissionDenied):
            ProductionCycleService.create(actor=self.administrator, articolo=self.product)

    def test_responsible_can_create_cycle(self):
        cycle = ProductionCycleService.create(actor=self.production, articolo=self.product)
        self.assertEqual(cycle.stato, "PIANIFICATO")
        self.assertEqual(cycle.creato_da, self.production)

    def test_operator_cannot_plan_work(self):
        with self.assertRaises(PermissionDenied):
            WorkExecutionService.plan(actor=self.operator, ciclo=self.cycle, tipo_lavorazione=self.kind)

    def test_batch_count_creates_distinct_work_records(self):
        works = WorkExecutionService.plan_batches(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind, ricetta=self.recipe, numero_batch=3)
        self.assertEqual(len({w.pk for w in works}), 3)
        self.assertTrue(all(w.stato == "PIANIFICATA" and w.ricetta_id == self.recipe.pk for w in works))

    def test_invalid_batch_count_is_rejected(self):
        for number in (0, -1, True, 1.5):
            with self.subTest(number=number), self.assertRaises(ValidationError):
                WorkExecutionService.plan_batches(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind, ricetta=self.recipe, numero_batch=number)

    def test_start_work_also_starts_cycle(self):
        self.start()
        self.cycle.refresh_from_db()
        self.assertEqual(self.work.stato, "IN_CORSO")
        self.assertEqual(self.cycle.stato, "IN_CORSO")
        self.assertEqual(self.work.eseguita_da, self.operator)
        self.assertIsNotNone(self.work.data_ora_inizio)

    def test_start_twice_does_not_reset_time(self):
        self.start()
        started_at = self.work.data_ora_inizio
        with self.assertRaises(ValidationError):
            self.start()
        self.work.refresh_from_db()
        self.assertEqual(self.work.data_ora_inizio, started_at)

    def test_reschedule_planned_work_and_cycle(self):
        ProductionCycleService.reschedule(actor=self.production, ciclo=self.cycle, data=date(2027, 1, 1))
        WorkExecutionService.reschedule(actor=self.production, lavorazione=self.work, ricetta=None, note="Nuova pianificazione")
        self.work.refresh_from_db()
        self.cycle.refresh_from_db()
        self.assertIsNone(self.work.ricetta_id)
        self.assertEqual(self.cycle.data, date(2027, 1, 1))

    def test_running_work_cannot_be_rescheduled(self):
        self.start()
        with self.assertRaises(ValidationError):
            WorkExecutionService.reschedule(actor=self.production, lavorazione=self.work, note="Modifica")

    def test_disabled_recipe_prevents_start(self):
        self.recipe.attiva = False
        self.recipe.save()
        with self.assertRaises(ValidationError):
            self.start()

    def test_input_consumes_and_links_movement(self):
        self.start()
        self.load()
        result = self.consume()
        self.assertEqual(result.movimenti[0].input_lavorazione_id, result.registrazione.pk)
        self.assertEqual(Giacenza.objects.get(lotto=self.lot).quantita, 5)

    def test_input_can_consume_from_two_locations(self):
        self.start()
        self.load("3")
        self.load("2", position=self.destination)
        result = self.consume(origins=[Allocation(self.position, "3"), Allocation(self.destination, "2")])
        self.assertEqual(len(result.movimenti), 2)
        self.assertFalse(Giacenza.objects.filter(quantita__gt=0).exists())

    def test_input_failure_rolls_back_record_and_first_consumption(self):
        self.start()
        self.load("3")
        with self.assertRaises(ValidationError):
            self.consume(origins=[Allocation(self.position, "3"), Allocation(self.destination, "2")])
        self.assertFalse(InputLavorazione.objects.exists())
        self.assertEqual(Giacenza.objects.get().quantita, 3)
        self.assertEqual(Movimento.objects.count(), 1)

    def test_input_wrong_requirement_rolls_back(self):
        self.start()
        self.load()
        kind = TipoLavorazione.objects.create(codice="ALTRO", nome="Altro")
        req = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Altro", articolo=self.article)
        with self.assertRaises(ValidationError):
            InputService.register(actor=self.operator, lavorazione=self.work, requisito_input=req,
                                  lotto=self.lot, quantita="1", origini=[Allocation(self.position, "1")])
        self.assertFalse(InputLavorazione.objects.exists())

    def test_output_creates_lot_record_and_stock(self):
        self.start()
        result = self.produce()
        self.assertEqual(result.lotto.lavorazione_origine_id, self.work.pk)
        self.assertEqual(result.movimenti[0].output_lavorazione_id, result.registrazione.pk)
        self.assertEqual(Giacenza.objects.get(lotto=result.lotto).quantita, 4)

    def test_output_split_across_locations(self):
        self.start()
        result = OutputService.register(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req,
                                        articolo=self.product, quantita="4", destinazioni=[Allocation(self.position, "1"), Allocation(self.destination, "3")])
        self.assertEqual(len(result.movimenti), 2)
        self.assertEqual(Giacenza.objects.get(lotto=result.lotto, ubicazione=self.other).quantita, 3)

    def test_output_failure_rolls_back_new_lot_and_record(self):
        self.start()
        with patch.object(MovementService, "register", side_effect=ValidationError("Errore simulato")), self.assertRaises(ValidationError):
            self.produce()
        self.assertFalse(self.work.lotti_generati.exists())
        self.assertFalse(OutputLavorazione.objects.exists())
        self.assertFalse(Giacenza.objects.exists())

    def test_prepare_identity_does_not_create_stock(self):
        self.start()
        lot = OutputService.prepare_lot(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req, articolo=self.product)
        self.assertIsNotNone(lot.pk)
        self.assertFalse(OutputLavorazione.objects.exists())
        self.assertFalse(Movimento.objects.exists())
        self.assertFalse(Giacenza.objects.exists())
        self.work.refresh_from_db()
        self.assertEqual(self.work.stato, "IN_CORSO")

    def test_prepared_lot_is_consolidated_at_real_quantity(self):
        self.start()
        identity = OutputService.prepare_lot(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req, articolo=self.product)
        result = self.produce(amount="7", lotto=identity)
        self.assertEqual(identity.pk, result.lotto.pk)
        self.assertEqual(Giacenza.objects.get().quantita, 7)

    def test_prepared_lot_cannot_be_consolidated_twice(self):
        self.start()
        identity = OutputService.prepare_lot(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req, articolo=self.product)
        self.produce(lotto=identity)
        with self.assertRaises(ValidationError):
            self.produce(lotto=identity)
        self.assertEqual(Giacenza.objects.get().quantita, 4)

    def test_commercial_codes_have_date_and_alphabetic_suffix(self):
        kind = TipoLavorazione.objects.create(codice="COMM", nome="Commerciale")
        req = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Commerciale", articolo=self.product, multiplo=True)
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=kind)
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        codes = [LotGenerationService.create_production(actor=self.operator, lavorazione=work, requisito_output=req,
                                                        articolo=self.product, data_produzione=date(2026, 9, 5)).codice_lotto for _ in range(3)]
        self.assertEqual(codes, ["260905", "260905-A", "260905-B"])

    def test_intermediate_code_uses_requirement_prefix(self):
        self.start()
        lot = OutputService.prepare_lot(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req,
                                       articolo=self.product, data_produzione=date(2026, 9, 5))
        self.assertEqual(lot.codice_lotto, "INT260905")

    def test_wrong_output_article_is_rejected(self):
        self.start()
        with self.assertRaises(ValidationError):
            OutputService.prepare_lot(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req, articolo=self.article)

    def test_missing_mandatory_input_prevents_completion(self):
        self.start()
        self.produce()
        with self.assertRaises(ValidationError):
            WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)
        self.work.refresh_from_db()
        self.assertEqual(self.work.stato, "IN_CORSO")

    def test_missing_mandatory_output_prevents_completion(self):
        self.start()
        self.load()
        self.consume()
        with self.assertRaises(ValidationError):
            WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)

    def test_unreconciled_input_prevents_completion(self):
        self.start()
        InputLavorazione.objects.create(lavorazione=self.work, requisito_input=self.input_req, lotto=self.lot, quantita=1)
        self.produce()
        with self.assertRaises(ValidationError):
            WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)

    def test_unreconciled_output_prevents_completion(self):
        self.start()
        self.load()
        self.consume()
        identity = OutputService.prepare_lot(actor=self.operator, lavorazione=self.work, requisito_output=self.output_req, articolo=self.product)
        OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=identity, quantita=1)
        with self.assertRaises(ValidationError):
            WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)

    def test_complete_valid_work_and_cycle(self):
        self.record_materials()
        work = WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)
        self.assertEqual(work.stato, "COMPLETATA")
        self.assertIsNotNone(work.data_ora_fine)
        cycle = ProductionCycleService.complete(actor=self.production, ciclo=self.cycle)
        self.assertEqual(cycle.stato, "COMPLETATO")

    def test_completed_work_cannot_restart_or_take_new_input(self):
        self.record_materials()
        WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)
        with self.assertRaises(ValidationError):
            self.start()
        with self.assertRaises(ValidationError):
            self.consume(amount="1")

    def test_non_generating_process_completes_without_artificial_outputs(self):
        kind = TipoLavorazione.objects.create(codice="TRATTA", nome="Trattamento", genera_lotto=False)
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=kind)
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        result = WorkExecutionService.complete(actor=self.operator, lavorazione=work)
        self.assertEqual(result.stato, "COMPLETATA")
        self.assertFalse(result.outputs.exists())
        self.assertFalse(result.lotti_generati.exists())

    def test_operator_cannot_cancel_unstarted_work(self):
        with self.assertRaises(PermissionDenied):
            WorkExecutionService.cancel(actor=self.operator, lavorazione=self.work)

    def test_admin_actions_follow_custom_permissions(self):
        request = RequestFactory().get("/")
        request.user = self.operator
        model_admin = admin.site._registry[Lavorazione]
        actions = model_admin.get_actions(request)
        self.assertIn("start_work", actions)
        self.assertIn("complete_work", actions)
        self.assertNotIn("cancel_work", actions)
        request.user = self.administrator
        self.assertEqual(model_admin.get_actions(request), {})

    def test_responsible_can_cancel_unstarted_work(self):
        work = WorkExecutionService.cancel(actor=self.production, lavorazione=self.work)
        self.assertEqual(work.stato, "ANNULLATA")
        self.assertIsNone(work.data_ora_inizio)

    def test_started_work_cannot_be_cancelled(self):
        self.start()
        with self.assertRaises(ValidationError):
            WorkExecutionService.cancel(actor=self.production, lavorazione=self.work)

    def test_interruption_preserves_consumed_stock(self):
        self.start()
        self.load()
        self.consume()
        work = WorkExecutionService.interrupt(actor=self.operator, lavorazione=self.work, note="Guasto attrezzatura")
        self.assertEqual(work.stato, "INTERROTTA")
        self.assertEqual(Giacenza.objects.get().quantita, 5)
        self.assertIsNotNone(work.data_ora_fine)

    def test_interruption_requires_reason(self):
        self.start()
        with self.assertRaises(ValidationError):
            WorkExecutionService.interrupt(actor=self.operator, lavorazione=self.work, note=" ")

    def test_cancel_cycle_also_cancels_planned_work(self):
        ProductionCycleService.cancel(actor=self.production, ciclo=self.cycle)
        self.work.refresh_from_db()
        self.cycle.refresh_from_db()
        self.assertEqual(self.work.stato, "ANNULLATA")
        self.assertEqual(self.cycle.stato, "ANNULLATO")

    def test_started_cycle_cannot_be_cancelled(self):
        self.start()
        with self.assertRaises(ValidationError):
            ProductionCycleService.cancel(actor=self.production, ciclo=self.cycle)

    def test_cycle_with_open_work_cannot_complete(self):
        self.start()
        with self.assertRaises(ValidationError):
            ProductionCycleService.complete(actor=self.production, ciclo=self.cycle)

    def test_interrupted_work_blocks_normal_cycle_completion(self):
        self.start()
        WorkExecutionService.interrupt(actor=self.operator, lavorazione=self.work, note="Guasto")
        with self.assertRaises(ValidationError):
            ProductionCycleService.complete(actor=self.production, ciclo=self.cycle)

    def test_output_permission_is_not_inherited_from_warehouse_role(self):
        self.start()
        for actor in (self.warehouse, self.administrator):
            with self.subTest(actor=actor.username), self.assertRaises(PermissionDenied):
                OutputService.register(actor=actor, lavorazione=self.work, requisito_output=self.output_req,
                                       articolo=self.product, quantita="1", destinazioni=[Allocation(self.destination, "1")])

    def test_production_movement_cannot_exceed_consolidated_output(self):
        self.start()
        result = self.produce()
        with self.assertRaises(ValidationError):
            MovementService.register(actor=self.operator, lotto=result.lotto, tipo="PRODUZIONE", quantita="1",
                                     destinazione=self.destination, output_lavorazione=result.registrazione)
        self.assertEqual(Giacenza.objects.get(lotto=result.lotto).quantita, 4)

    def test_input_rejects_genealogy_cycle(self):
        kind = TipoLavorazione.objects.create(codice="REWORK", nome="Rilavorazione")
        req_in = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Prodotto", articolo=self.product, multiplo=True)
        req_out = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Prodotto", articolo=self.product)
        first = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=kind)
        second = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=kind)
        for work in (first, second):
            WorkExecutionService.start(actor=self.operator, lavorazione=work)
        a = OutputService.register(actor=self.operator, lavorazione=first, requisito_output=req_out, articolo=self.product, quantita="2", destinazioni=[Allocation(self.destination, "2")])
        InputService.register(actor=self.operator, lavorazione=second, requisito_input=req_in, lotto=a.lotto, quantita="1", origini=[Allocation(self.destination, "1")])
        b = OutputService.register(actor=self.operator, lavorazione=second, requisito_output=req_out, articolo=self.product, quantita="2", destinazioni=[Allocation(self.destination, "2")])
        with self.assertRaises(ValidationError):
            InputService.register(actor=self.operator, lavorazione=first, requisito_input=req_in, lotto=b.lotto, quantita="1", origini=[Allocation(self.destination, "1")])
