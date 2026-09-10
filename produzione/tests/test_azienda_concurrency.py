from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from magazzino.services import Allocation
from produzione.models import PrelievoDaPiano, RiepilogoInvasettamento
from produzione.services.azienda_planning import ShiftService, PickingPlanService
from produzione.services.azienda_execution import BatchService, FillingService
from .test_azienda_flow import AziendaFixture


@skipUnlessDBFeature("has_select_for_update")
class AziendaConcurrencyTests(AziendaFixture, TransactionTestCase):
    def setUp(self):
        self.setUpTestData()
        super().setUp()

    def parallel(self, actor_id, operation):
        barrier = Barrier(2)

        def run():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
                actor = get_user_model().objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                try:
                    operation(actor)
                    return "ok"
                except ValidationError:
                    return "rifiutato"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(run) for _ in range(2)]
            return [future.result(timeout=30) for future in futures]

    def test_same_batch_cannot_be_consumed_twice(self):
        plan, revision = self.plan()
        batch = plan.batch.get()
        BatchService.start(actor=self.op, batch=batch)
        def consume(actor):
            PickingPlanService.consume_batch(actor=actor, batch=batch.pk, revisione=revision.pk)
        self.assertCountEqual(self.parallel(self.op.pk, consume), ["ok", "rifiutato"])
        self.assertEqual(batch.lavorazione.inputs.count(), 2)
        self.assertEqual(PrelievoDaPiano.objects.count(), 2)

    def test_shift_start_has_one_winner(self):
        ShiftService.end(actor=self.op, turno=self.shift)
        def start(actor):
            ShiftService.start(actor=actor, postazione=self.shift.postazione_id)
        self.assertCountEqual(self.parallel(self.op.pk, start), ["ok", "rifiutato"])

    def test_double_closure_writes_one_summary_and_one_packaging_consumption(self):
        session = self.open_filling(self.make_tank())
        self.treated_cart(session)
        args = dict(sessione=session.pk, vasetti_buoni=90, vasetti_scarti=5, capsule_difettose=2, peso_netto_g="100")
        _, selections, _ = FillingService.packaging_forecast(actor=self.filler, **args, ubicazioni=[self.mag.ubicazione_id])
        def close(actor):
            FillingService.close(actor=actor, **args, selections=selections, destinazioni=[Allocation(self.mag, "9")])
        self.assertCountEqual(self.parallel(self.filler.pk, close), ["ok", "rifiutato"])
        self.assertEqual(RiepilogoInvasettamento.objects.filter(sessione=session).count(), 1)
        self.assertEqual(session.lavorazione.inputs.filter(requisito_input=self.c["input"]["vasetti"]).count(), 1)
