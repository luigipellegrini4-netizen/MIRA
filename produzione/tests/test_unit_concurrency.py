from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from produzione.models import UnitaLavorazione
from produzione.services import WorkUnitService, WorkExecutionService
from .unit_fixtures import setup_units


@skipUnlessDBFeature("has_select_for_update")
class UnitConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup_units(self)

    def parallel(self, operations):
        barrier = Barrier(len(operations))

        def run(operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
                actor = get_user_model().objects.get(pk=self.operator.pk)
                barrier.wait(timeout=10)
                try:
                    operation(actor)
                    return "ok"
                except ValidationError:
                    return "rifiutato"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, operation) for operation in operations]
            return [future.result(timeout=20) for future in futures]

    def test_concurrent_cart_assignment_has_one_winner(self):
        def create(actor):
            WorkUnitService.create(actor=actor, lavorazione_origine=self.origin.pk, lotto=self.inv_lot.pk, risorsa_produttiva=self.cart.pk)

        self.assertCountEqual(self.parallel([create, create]), ["ok", "rifiutato"])
        self.assertEqual(UnitaLavorazione.objects.filter(risorsa_produttiva=self.cart, stato="ATTIVA").count(), 1)

    def test_completion_serializes_with_new_participation(self):
        units = [WorkUnitService.create(actor=self.operator, lavorazione_origine=self.origin, lotto=self.inv_lot) for _ in range(2)]
        WorkExecutionService.start(actor=self.operator, lavorazione=self.heat)
        WorkUnitService.participate(actor=self.operator, unita_lavorazione=units[0], lavorazione=self.heat)

        def join(actor):
            WorkUnitService.participate(actor=actor, unita_lavorazione=units[1].pk, lavorazione=self.heat.pk)

        def complete(actor):
            WorkExecutionService.complete(actor=actor, lavorazione=self.heat.pk)

        result = self.parallel([join, complete])
        self.assertEqual(result[1], "ok")
        self.heat.refresh_from_db()
        self.assertEqual(self.heat.stato, "COMPLETATA")
        self.assertEqual(self.heat.partecipazioni_unita.count(), 2 if result[0] == "ok" else 1)
