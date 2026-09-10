import json
from unittest.mock import patch
from decimal import Decimal
from django.test import SimpleTestCase, TestCase
from django.core.exceptions import ValidationError
from django.contrib.auth import get_user_model
from tempfile import TemporaryDirectory
from magazzino.management.commands.inizializza_confetture import catalog, formulas, initialize, dependencies, reset_models, INVENTORY
from magazzino.models import Lotto, Movimento
from produzione.models import Ricetta
from produzione.services.demo_seed import seed_demo
from produzione.services import ProductionCycleService, WorkExecutionService, OutputService
from magazzino.services import Allocation, Position


class InitialCatalogRulesTests(SimpleTestCase):
    def test_reset_order_and_preserved_configuration(self):
        models = reset_models(True)
        self.assertEqual(len(models), 27)
        positions = {model: index for index, model in enumerate(models)}
        for model in models:
            for field in model._meta.fields:
                if field.is_relation and field.related_model in positions:
                    self.assertLess(positions[model], positions[field.related_model])
        labels = {model._meta.label for model in models}
        self.assertNotIn("produzione.Ricetta", labels)
        self.assertNotIn("produzione.LineaProduttiva", labels)
        self.assertNotIn("qualita.ParametroControllo", labels)
        self.assertEqual(set(reset_models()), set(INVENTORY))

    def test_catalog_has_21_distinct_articles(self):
        rows = catalog()
        self.assertEqual(len(rows), 21)
        self.assertEqual(len({r[0] for r in rows}), 21)
        self.assertEqual(sum(r[3] == "PZ" for r in rows), 2)

    def test_ten_recipes_reference_only_catalog_articles(self):
        codes = {r[0] for r in catalog()}
        self.assertEqual(len(formulas()), 10)
        for product, rows in formulas().items():
            self.assertIn(product, codes)
            for ingredient, amount in rows:
                self.assertIn(ingredient, codes)
                self.assertGreater(Decimal(amount), 0)

    def test_jams_have_five_requested_ingredients(self):
        for code, rows in formulas().items():
            if code.startswith("CF_"):
                self.assertEqual({c for c, q in rows}, {code.replace("CF_", "SL_"), "MP_PECTINA", "MP_ASCORBICO", "MP_PUREA_MELA", "MP_ZUCCHERO"})
                self.assertEqual(sum(Decimal(q) for c, q in rows), Decimal("18.170"))


class InitialCatalogDatabaseTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.d = seed_demo()

    def test_reset_preserves_users_and_existing_recipes_and_loads_63_lots(self):
        users = list(get_user_model().objects.order_by("pk").values_list("pk", "username", "password"))
        with TemporaryDirectory() as directory:
            backup = initialize(recipe_actor=self.d["users"]["produzione"], stock_actor=self.d["users"]["magazzino"], backup_dir=directory)
            self.assertTrue(backup.exists())
            self.assertEqual(Lotto.objects.count(), 63)
            self.assertEqual(Movimento.objects.count(), 63)
            self.assertEqual(Ricetta.objects.filter(versione="PROVA-1").count(), 10)
            self.assertTrue(Ricetta.objects.filter(pk=self.d["recipe"].pk).exists())
            self.assertEqual(list(get_user_model().objects.order_by("pk").values_list("pk", "username", "password")), users)
            initialize(recipe_actor=self.d["users"]["produzione"], stock_actor=self.d["users"]["magazzino"], backup_dir=directory)
            self.assertEqual(Lotto.objects.count(), 63)
            self.assertEqual(Ricetta.objects.filter(versione="PROVA-1").count(), 10)

    def test_linked_production_blocks_reset_without_removing_stock(self):
        cycle = ProductionCycleService.create(actor=self.d["users"]["produzione"], articolo=self.d["recipe"].articolo)
        work = WorkExecutionService.plan(actor=self.d["users"]["produzione"], ciclo=cycle,
            tipo_lavorazione=self.d["kind"], ricetta=self.d["recipe"])
        WorkExecutionService.start(actor=self.d["users"]["operatore"], lavorazione=work)
        OutputService.register(actor=self.d["users"]["operatore"], lavorazione=work, requisito_output=self.d["output"],
            quantita="10", destinazioni=[Allocation(Position(self.d["locations"]["MAG"].pk), "10")])
        self.assertTrue(dependencies())
        count = Lotto.objects.count()
        with TemporaryDirectory() as directory, self.assertRaises(ValidationError):
            initialize(recipe_actor=self.d["users"]["produzione"], stock_actor=self.d["users"]["magazzino"], backup_dir=directory)
        self.assertEqual(Lotto.objects.count(), count)

    def test_extended_reset_backs_up_production_and_preserves_configuration(self):
        cycle = ProductionCycleService.create(actor=self.d["users"]["produzione"], articolo=self.d["recipe"].articolo)
        work = WorkExecutionService.plan(actor=self.d["users"]["produzione"], ciclo=cycle,
            tipo_lavorazione=self.d["kind"], ricetta=self.d["recipe"])
        WorkExecutionService.start(actor=self.d["users"]["operatore"], lavorazione=work)
        OutputService.register(actor=self.d["users"]["operatore"], lavorazione=work, requisito_output=self.d["output"],
            quantita="10", destinazioni=[Allocation(Position(self.d["locations"]["MAG"].pk), "10")])
        users = list(get_user_model().objects.order_by("pk").values())
        with TemporaryDirectory() as directory:
            backup = initialize(recipe_actor=self.d["users"]["produzione"], stock_actor=self.d["users"]["magazzino"],
                backup_dir=directory, include_operations=True)
            records = json.loads(backup.read_text(encoding="utf-8"))
            self.assertTrue(any(r["model"] == "produzione.lavorazione" and r["pk"] == work.pk for r in records))
            for model in set(reset_models(True)) - set(INVENTORY):
                self.assertFalse(model.objects.exists(), model._meta.label)
            self.assertEqual(Lotto.objects.count(), 63)
            self.assertTrue(Ricetta.objects.filter(pk=self.d["recipe"].pk).exists())
            self.assertTrue(type(self.d["kind"]).objects.filter(pk=self.d["kind"].pk).exists())
            self.assertEqual(list(get_user_model().objects.order_by("pk").values()), users)

    def test_extended_reset_rolls_back_if_loading_fails(self):
        cycle = ProductionCycleService.create(actor=self.d["users"]["produzione"], articolo=self.d["recipe"].articolo)
        old_lots = list(Lotto.objects.order_by("pk").values_list("pk", flat=True))
        with TemporaryDirectory() as directory:
            with patch("magazzino.management.commands.inizializza_confetture.ReceivingService.receive", side_effect=ValidationError("Errore simulato")):
                with self.assertRaises(ValidationError):
                    initialize(recipe_actor=self.d["users"]["produzione"], stock_actor=self.d["users"]["magazzino"],
                        backup_dir=directory, include_operations=True)
            self.assertTrue(type(cycle).objects.filter(pk=cycle.pk).exists())
            self.assertEqual(list(Lotto.objects.order_by("pk").values_list("pk", flat=True)), old_lots)
