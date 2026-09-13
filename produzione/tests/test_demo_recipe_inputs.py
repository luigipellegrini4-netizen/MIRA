from decimal import Decimal
from unittest.mock import patch
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from anagrafiche.models import Articolo
from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.services import Allocation, Position, MovementService
from produzione.models import InputLavorazione, CicloProduzione, Ricetta, RigaRicetta
from produzione.services import (RecipeService, RecipeInputService, InputSelection,
    InputService, OutputService, ProductionCycleService, WorkExecutionService)
from produzione.services.demo_seed import seed_demo
from produzione.services.demo_collation import run_demo, stocks


class DemoRecipeInputsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_demo()

    def setUp(self):
        self.d = self.demo
        self.actor = self.d["users"]["operatore"]
        self.rows = list(self.d["recipe"].righe.all())
        self.position = Position(self.d["locations"]["MAG"].pk)

    def work(self, recipe=None):
        cycle = ProductionCycleService.create(actor=self.d["users"]["produzione"], articolo=self.d["articles"]["SEMILAVORATO"])
        work = WorkExecutionService.plan(actor=self.d["users"]["produzione"], ciclo=cycle,
            tipo_lavorazione=self.d["kind"], ricetta=recipe or self.d["recipe"])
        return WorkExecutionService.start(actor=self.actor, lavorazione=work)

    def proposal(self, work, location="MAG"):
        return RecipeInputService.propose(actor=self.actor, lavorazione=work, ubicazioni=[self.d["locations"][location]])

    def confirm(self, work, proposal=None):
        return RecipeInputService.confirm_proposal(actor=self.actor, lavorazione=work, proposal=proposal or self.proposal(work))

    def test_seed_twice_does_not_duplicate_or_replenish_stock(self):
        before = stocks(), Movimento.objects.count(), Lotto.objects.count()
        repeat = seed_demo()
        self.assertEqual((stocks(), Movimento.objects.count(), Lotto.objects.count()), before)
        self.assertEqual(repeat["recipe"].pk, self.d["recipe"].pk)
        self.assertFalse(repeat["kind"].requisiti_input.exists())
        self.assertEqual(get_user_model().objects.filter(username__startswith="demo11_").count(), 7)

    def test_seed_preserves_password_set_locally(self):
        self.actor.set_password("Only-a-test-password-11")
        self.actor.save()
        repeat = seed_demo()
        self.assertTrue(repeat["users"]["operatore"].check_password("Only-a-test-password-11"))
        self.assertFalse(repeat["users"]["admin"].has_usable_password())

    def test_seed_collision_does_not_overwrite_article(self):
        article = self.d["articles"]["FRAGOLE"]
        article.descrizione = "Modifica intenzionale"
        article.save()
        with self.assertRaises(ValidationError):
            seed_demo()
        article.refresh_from_db()
        self.assertEqual(article.descrizione, "Modifica intenzionale")

    def test_direct_recipe_inputs_and_automatic_article_with_real_yield(self):
        work = self.work()
        results = self.confirm(work)
        self.assertEqual({r.registrazione.riga_ricetta_id for r in results}, {r.pk for r in self.rows})
        self.assertTrue(all(r.registrazione.requisito_input_id is None for r in results))
        output = OutputService.register(actor=self.actor, lavorazione=work, requisito_output=self.d["output"],
            quantita="9.800", destinazioni=[Allocation(self.position, "9.800")])
        self.assertEqual(output.lotto.articolo_id, self.d["recipe"].articolo_id)
        self.assertEqual(output.registrazione.quantita, Decimal("9.8"))
        self.assertEqual(WorkExecutionService.complete(actor=self.actor, lavorazione=work).stato, "COMPLETATA")

    def test_split_row_over_two_lots_retains_the_same_recipe_row(self):
        work = self.work()
        results = self.confirm(work, self.proposal(work, "C"))
        fruit = [r for r in results if r.registrazione.riga_ricetta_id == self.rows[0].pk]
        self.assertEqual([r.registrazione.quantita for r in fruit], [Decimal(6), Decimal(4)])
        self.assertEqual(len({r.lotto.pk for r in fruit}), 2)

    def test_second_confirmation_rolls_back_all_new_inputs(self):
        work = self.work()
        self.confirm(work)
        before = stocks(), Movimento.objects.count(), InputLavorazione.objects.count()
        with self.assertRaises(ValidationError):
            self.confirm(work)
        self.assertEqual((stocks(), Movimento.objects.count(), InputLavorazione.objects.count()), before)

    def test_partial_recipe_confirmation_is_atomic(self):
        work = self.work()
        proposal = self.proposal(work)
        before = stocks(), Movimento.objects.count()
        with self.assertRaises(ValidationError):
            RecipeInputService.confirm(actor=self.actor, lavorazione=work, selections=proposal.selections[:1])
        self.assertEqual((stocks(), Movimento.objects.count()), before)
        self.assertFalse(work.inputs.exists())

    def test_stale_proposal_rolls_back_first_ingredient_when_second_is_short(self):
        work = self.work()
        proposal = self.proposal(work)
        MovementService.register(actor=self.d["users"]["magazzino"], lotto=self.d["lots"]["A_A"],
            tipo="RETTIFICA", quantita="1", origine=self.position, note="Test variazione successiva alla proposta")
        before = stocks(), Movimento.objects.count()
        with self.assertRaises(ValidationError):
            self.confirm(work, proposal)
        self.assertEqual((stocks(), Movimento.objects.count()), before)
        self.assertFalse(work.inputs.exists())

    def test_incomplete_proposal_has_no_side_effects(self):
        work = self.work()
        before = stocks(), Movimento.objects.count()
        with self.assertRaises(ValidationError):
            self.confirm(work, self.proposal(work, "D"))
        self.assertEqual((stocks(), Movimento.objects.count()), before)

    def test_wrong_article_cannot_satisfy_recipe_row(self):
        work = self.work()
        with self.assertRaises(ValidationError):
            InputService.register(actor=self.actor, lavorazione=work, lotto=self.d["lots"]["A_A"],
                riga_ricetta=self.rows[0], quantita=".05", origini=[Allocation(self.position, ".05")])
        self.assertFalse(work.inputs.exists())

    def test_row_from_different_recipe_is_rejected(self):
        other = RecipeService.create(actor=self.d["users"]["produzione"], articolo=self.d["articles"]["SEMILAVORATO"], nome="Altra", versione="2")
        row = RecipeService.add_line(actor=self.d["users"]["produzione"], ricetta=other, articolo=self.d["articles"]["FRAGOLE"], quantita="1")
        with self.assertRaises(ValidationError):
            InputService.register(actor=self.actor, lavorazione=self.work(), lotto=self.d["lots"]["F_A"],
                riga_ricetta=row, quantita="1", origini=[Allocation(self.position, "1")])

    def test_output_without_all_recipe_ingredients_cannot_complete(self):
        work = self.work()
        OutputService.register(actor=self.actor, lavorazione=work, requisito_output=self.d["output"],
            quantita="9.8", destinazioni=[Allocation(self.position, "9.8")])
        with self.assertRaisesMessage(ValidationError, "Ingrediente"):
            WorkExecutionService.complete(actor=self.actor, lavorazione=work)

    def test_principal_output_rejects_different_article_in_same_category(self):
        other = Articolo.objects.create(codice="ALTRO_SL", descrizione="Altro", categoria=self.d["categories"]["SL"], unita_misura="KG")
        with self.assertRaises(ValidationError):
            OutputService.register(actor=self.actor, lavorazione=self.work(), requisito_output=self.d["output"],
                articolo=other, quantita="9.8", destinazioni=[Allocation(self.position, "9.8")])
        self.assertFalse(Lotto.objects.filter(tipo="PRODUZIONE").exists())

    def test_legacy_overlapping_category_and_article_rows_share_one_stock_pool(self):
        recipe = RecipeService.create(actor=self.d["users"]["produzione"], articolo=self.d["articles"]["SEMILAVORATO"], nome="Sovrapposizione", versione="2")
        RecipeService.add_line(actor=self.d["users"]["produzione"], ricetta=recipe, articolo=self.d["articles"]["FRAGOLE"], quantita="8")
        category_row = RigaRicetta.objects.create(ricetta=recipe, categoria_articolo=self.d["categories"]["MP"], quantita="8")
        work = self.work(recipe)
        with self.assertRaises(ValidationError):
            self.proposal(work, "C")
        proposal = RecipeInputService.propose(actor=self.actor, lavorazione=work, ubicazioni=[self.d["locations"]["C"]],
            articoli_per_riga={category_row.pk: self.d["articles"]["FRAGOLE"].pk})
        self.assertFalse(proposal.completa)
        self.assertEqual(sum(s.quantita for s in proposal.selections), Decimal(14))
        self.assertEqual(proposal.righe[-1]["mancante"], Decimal(2))

    def test_collation_all_scenarios_and_repeat_without_new_movements(self):
        report = run_demo()
        self.assertEqual(set(report["scenari"]), {"A", "B", "C", "D", "E", "F", "G", "STORICO"})
        self.assertTrue(all(s["esito"] == "PASS" for s in report["scenari"].values()))
        before = stocks(), Movimento.objects.count(), InputLavorazione.objects.count()
        self.assertEqual(run_demo(), report)
        self.assertEqual((stocks(), Movimento.objects.count(), InputLavorazione.objects.count()), before)

    def test_late_collation_failure_rolls_back_every_scenario(self):
        before = stocks(), Movimento.objects.count(), CicloProduzione.objects.count()
        with patch("produzione.services.demo_collation.NC.open", side_effect=ValidationError("Guasto simulato")):
            with self.assertRaisesMessage(ValidationError, "Guasto simulato"):
                run_demo()
        self.assertEqual((stocks(), Movimento.objects.count(), CicloProduzione.objects.count()), before)
        self.assertFalse(InputLavorazione.objects.exists())
