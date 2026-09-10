from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, connections
from django.test import TransactionTestCase, skipUnlessDBFeature
from magazzino.models import Giacenza
from magazzino.services import MovementService
from magazzino.tests.service_fixtures import setup_inventory
from qualita.models import NonConformita
from qualita.services import NonConformityService as NC
from qualita.nc_selectors import quarantine_balances


@skipUnlessDBFeature("has_select_for_update")
class NCConcurrencyTests(TransactionTestCase):
    def setUp(self):
        setup_inventory(self)

    def parallel(self, operations):
        barrier = Barrier(len(operations))

        def run(actor_id, operation):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
                actor = get_user_model().objects.get(pk=actor_id)
                barrier.wait(timeout=10)
                try:
                    return operation(actor)
                except ValidationError:
                    return "rifiutato"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=len(operations)) as executor:
            futures = [executor.submit(run, actor.pk, operation) for actor, operation in operations]
            return [f.result(timeout=20) for f in futures]

    def test_concurrent_numbers_are_unique_and_progressive(self):
        def create(actor):
            return NC.open(actor=actor, descrizione="Anomalia").numero
        self.assertCountEqual(self.parallel([(self.operator, create), (self.warehouse, create)]), [1, 2])

    def test_quarantine_and_consumption_compete_for_same_stock(self):
        MovementService.register(actor=self.warehouse, lotto=self.lot, tipo="CARICO", quantita="10", destinazione=self.position)
        nc = NC.open(actor=self.operator, descrizione="Anomalia", lotto=self.lot)
        NC.take_charge(actor=self.quality, non_conformita=nc)

        def quarantine(actor):
            NC.action(actor=actor, non_conformita=nc.pk, tipo_azione="QUARANTENA", descrizione="Isolamento", quantita="7", origine=self.position, destinazione=self.destination)
            return "ok"

        def consume(actor):
            MovementService.register(actor=actor, lotto=self.lot.pk, tipo="CONSUMO", quantita="7", origine=self.position)
            return "ok"

        results = self.parallel([(self.quality, quarantine), (self.operator, consume)])
        self.assertCountEqual(results, ["ok", "rifiutato"])
        self.assertEqual(sum(quarantine_balances(lotto=self.lot).values()), 7 if results[0] == "ok" else 0)
        self.assertEqual(Giacenza.objects.get(lotto=self.lot, ubicazione=self.location).quantita, 3)

    def test_close_and_new_action_are_serialized(self):
        nc = NC.open(actor=self.operator, descrizione="Anomalia")
        NC.take_charge(actor=self.quality, non_conformita=nc)
        NC.action(actor=self.quality, non_conformita=nc, tipo_azione="ALTRO", descrizione="Correzione")
        NC.verify(actor=self.quality, non_conformita=nc, esito="EFFICACE", descrizione="Verifica")

        def action(actor):
            NC.action(actor=actor, non_conformita=nc.pk, tipo_azione="ALTRO", descrizione="Nuova azione")
            return "ok"

        def close(actor):
            NC.close(actor=actor, non_conformita=nc.pk, note="Risolto")
            return "ok"

        results = self.parallel([(self.quality, action), (self.quality, close)])
        self.assertCountEqual(results, ["ok", "rifiutato"])
        nc.refresh_from_db()
        self.assertEqual(nc.stato, "CHIUSA" if results[1] == "ok" else "IN_GESTIONE")
