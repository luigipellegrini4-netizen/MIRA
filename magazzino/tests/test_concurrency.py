from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from django.contrib.auth import get_user_model
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature

from magazzino.models import Giacenza, Lotto, Movimento, RicevimentoLotto
from magazzino.services import Allocation, MovementService, ReceivingService
from magazzino.services.movements import InsufficientStock
from .service_fixtures import setup_inventory


@skipUnlessDBFeature("has_select_for_update")
class StockConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup_inventory(self)

    def run_parallel(self, operation):
        barrier = Barrier(2)

        def worker():
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
                barrier.wait(timeout=10)
                return operation()
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as executor:
            futures = [executor.submit(worker) for _ in range(2)]
            return [future.result(timeout=20) for future in futures]

    def test_two_consumers_cannot_overspend_same_stock(self):
        MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="CARICO", quantita="10", destinazione=self.position)
        operator_id, lot_id, position = self.operator.pk, self.lot.pk, self.position

        def consume():
            actor = get_user_model().objects.get(pk=operator_id)
            try:
                MovementService.register(actor=actor, lotto=lot_id, tipo="CONSUMO", quantita="7", origine=position)
                return "ok"
            except InsufficientStock:
                return "insufficiente"

        self.assertCountEqual(self.run_parallel(consume), ["ok", "insufficiente"])
        self.assertEqual(Giacenza.objects.get().quantita, 3)
        self.assertEqual(Movimento.objects.filter(tipo="CONSUMO").count(), 1)

    def test_two_receipts_reuse_single_new_lot_and_stock_row(self):
        user_id, article_id, supplier_id, position = self.warehouse.pk, self.article.pk, self.supplier.pk, self.position

        def receive():
            actor = get_user_model().objects.get(pk=user_id)
            return ReceivingService.receive(actor=actor, articolo=article_id, fornitore=supplier_id,
                                            codice_lotto="CONCURRENT", quantita_ricevuta="2",
                                            destinazioni=[Allocation(position, "2")]).lotto.pk

        results = self.run_parallel(receive)
        self.assertEqual(results[0], results[1])
        self.assertEqual(Lotto.objects.filter(codice_lotto="CONCURRENT").count(), 1)
        self.assertEqual(RicevimentoLotto.objects.count(), 2)
        self.assertEqual(Giacenza.objects.get().quantita, 4)

    def test_two_loads_create_only_one_previously_absent_stock_row(self):
        user_id, lot_id, position = self.warehouse.pk, self.lot.pk, self.position

        def load():
            actor = get_user_model().objects.get(pk=user_id)
            MovementService.register(actor=actor, lotto=lot_id, tipo="CARICO", quantita="2", destinazione=position)
            return "ok"

        self.assertEqual(self.run_parallel(load), ["ok", "ok"])
        self.assertEqual(Giacenza.objects.get().quantita, 4)
        self.assertEqual(Movimento.objects.count(), 2)
