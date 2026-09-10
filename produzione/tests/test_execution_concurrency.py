from concurrent.futures import ThreadPoolExecutor
from datetime import date
from threading import Barrier

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from magazzino.models import Giacenza
from magazzino.services import Allocation, LotGenerationService, MovementService
from magazzino.tests.service_fixtures import setup_inventory
from produzione.models import TipoLavorazione, RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione
from produzione.services import ProductionCycleService, WorkExecutionService, InputService, OutputService


@skipUnlessDBFeature("has_select_for_update")
class ExecutionConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup_inventory(self)
        self.works, self.inputs, self.outputs = [], [], []
        for index in range(2):
            kind = TipoLavorazione.objects.create(codice=f"TYPE{index}", nome=f"Tipo {index}")
            req_in = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Ingresso", articolo=self.article)
            req_out = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Uscita", articolo=self.article)
            cycle = ProductionCycleService.create(actor=self.production, articolo=self.article)
            work = WorkExecutionService.plan(actor=self.production, ciclo=cycle, tipo_lavorazione=kind)
            work = WorkExecutionService.start(actor=self.operator, lavorazione=work)
            self.works.append(work)
            self.inputs.append(req_in)
            self.outputs.append(req_out)

    def parallel(self, operations):
        barrier = Barrier(len(operations))
        actor_id = self.operator.pk

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
                actor = get_user_model().objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                return operation(actor)
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_lot_codes_are_unique_across_cycles_and_types(self):
        def operation(index):
            def generate(actor):
                return LotGenerationService.create_production(actor=actor, lavorazione=self.works[index].pk,
                                                               requisito_output=self.outputs[index].pk,
                                                               articolo=self.article.pk, data_produzione=date(2026, 9, 5)).codice_lotto
            return generate

        self.assertCountEqual(self.parallel([operation(0), operation(1)]), ["260905", "260905-A"])

    def test_concurrent_opposite_inputs_cannot_create_genealogy_cycle(self):
        lots = [OutputService.register(actor=self.operator, lavorazione=w, requisito_output=self.outputs[i],
                                       articolo=self.article, quantita="2", destinazioni=[Allocation(self.destination, "2")]).lotto
                for i, w in enumerate(self.works)]

        def operation(index):
            def consume(actor):
                try:
                    InputService.register(actor=actor, lavorazione=self.works[index].pk, requisito_input=self.inputs[index].pk,
                                          lotto=lots[1 - index].pk, quantita="1", origini=[Allocation(self.destination, "1")])
                    return "ok"
                except ValidationError:
                    return "rifiutato"
            return consume

        self.assertCountEqual(self.parallel([operation(0), operation(1)]), ["ok", "rifiutato"])

    def test_completion_and_new_input_are_serialized(self):
        kind = TipoLavorazione.objects.create(codice="TREAT", nome="Trattamento", genera_lotto=False)
        req = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Accessorio", articolo=self.article, obbligatorio=False)
        cycle = ProductionCycleService.create(actor=self.production, articolo=self.article)
        work = WorkExecutionService.plan(actor=self.production, ciclo=cycle, tipo_lavorazione=kind)
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="CARICO", quantita="2", destinazione=self.position)

        def consume(actor):
            try:
                InputService.register(actor=actor, lavorazione=work.pk, requisito_input=req.pk, lotto=self.lot.pk,
                                      quantita="1", origini=[Allocation(self.position, "1")])
                return "consumato"
            except ValidationError:
                return "gia_chiusa"

        def complete(actor):
            WorkExecutionService.complete(actor=actor, lavorazione=work.pk)
            return "completata"

        results = self.parallel([consume, complete])
        self.assertEqual(results[1], "completata")
        work.refresh_from_db()
        self.assertEqual(work.stato, "COMPLETATA")
        expected = 1 if results[0] == "consumato" else 2
        self.assertEqual(Giacenza.objects.get(lotto=self.lot).quantita, expected)
        self.assertEqual(work.inputs.count(), 2 - expected)
