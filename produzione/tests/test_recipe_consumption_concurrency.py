from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from decimal import Decimal
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connections, connection
from django.test import TransactionTestCase, skipUnlessDBFeature
from magazzino.models import Giacenza
from produzione.services import RecipeInputService, ProductionCycleService, WorkExecutionService
from produzione.services.demo_seed import seed_demo


@skipUnlessDBFeature("has_select_for_update")
class RecipeConsumptionConcurrencyTests(TransactionTestCase):
    def test_two_batches_compete_for_all_ingredients_without_partial_loser(self):
        d = seed_demo()
        actor = d["users"]["operatore"]
        works, selections = [], []
        for index in range(2):
            cycle = ProductionCycleService.create(actor=d["users"]["produzione"], articolo=d["articles"]["SEMILAVORATO"])
            work = WorkExecutionService.plan(actor=d["users"]["produzione"], ciclo=cycle, tipo_lavorazione=d["kind"], ricetta=d["recipe"])
            works.append(WorkExecutionService.start(actor=actor, lavorazione=work))
            proposal = RecipeInputService.propose(actor=actor, lavorazione=work, ubicazioni=[d["locations"]["C"]])
            selections.append(proposal.selections if index == 0 else tuple(reversed(proposal.selections)))
        barrier = Barrier(2)

        def consume(index):
            close_old_connections()
            try:
                with connection.cursor() as cursor:
                    cursor.execute("SET SESSION innodb_lock_wait_timeout = 5")
                user = get_user_model().objects.get(pk=actor.pk)
                barrier.wait(timeout=10)
                try:
                    RecipeInputService.confirm(actor=user, lavorazione=works[index].pk, selections=selections[index])
                    return "ok"
                except ValidationError:
                    return "rifiutato"
            finally:
                connections.close_all()

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(consume, i) for i in range(2)]
            results = [f.result(timeout=20) for f in futures]
        self.assertCountEqual(results, ["ok", "rifiutato"])
        loser = works[results.index("rifiutato")]
        self.assertFalse(loser.inputs.exists())
        self.assertFalse(loser.outputs.exists())
        fruit = Giacenza.objects.filter(ubicazione=d["locations"]["C"], lotto__articolo=d["articles"]["FRAGOLE"])
        self.assertEqual(sum(s.quantita for s in fruit), Decimal(4))
        self.assertEqual(Giacenza.objects.get(lotto=d["lots"]["AC"]).quantita, Decimal(".95"))
