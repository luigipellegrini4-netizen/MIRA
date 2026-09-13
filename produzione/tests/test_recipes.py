from decimal import Decimal
from unittest.mock import patch

from django.contrib import admin
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import RequestFactory, TestCase

from accounts.permissions import A, OP, RP, RM
from anagrafiche.models import Articolo, CategoriaArticolo
from produzione.models import Ricetta, RigaRicetta
from produzione.services import RecipeService


class RecipeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("bootstrap_roles", verbosity=0)
        for name, role in (("planner", RP), ("administrator", A), ("operator", OP), ("warehouse", RM)):
            user = get_user_model().objects.create_user(username=name, is_staff=True)
            user.groups.add(Group.objects.get(name=role))
            setattr(cls, name, user)
        cls.category = CategoriaArticolo.objects.create(codice="MP", nome="Materie prime")
        cls.child = CategoriaArticolo.objects.create(codice="FR", nome="Frutta", categoria_padre=cls.category)
        cls.other_category = CategoriaArticolo.objects.create(codice="IMB", nome="Imballaggi")
        cls.ingredient = Articolo.objects.create(codice="MELE", descrizione="Mele", categoria=cls.child, unita_misura="KG")
        cls.packaging = Articolo.objects.create(codice="VAS", descrizione="Vasetti", categoria=cls.other_category, unita_misura="PZ")
        cls.product = Articolo.objects.create(codice="CONF", descrizione="Confettura", categoria=cls.category, unita_misura="KG")
        cls.recipe = Ricetta.objects.create(articolo=cls.product, nome="Confettura", versione="1")

    def add_line(self, amount="2.5", **kwargs):
        if not kwargs:
            kwargs["articolo"] = self.ingredient
        return RecipeService.add_line(actor=self.planner, ricetta=self.recipe, quantita=amount, **kwargs)

    def test_recipe_create_by_planner(self):
        recipe = RecipeService.create(actor=self.planner, articolo=self.product, nome="Nuova", versione="2")
        self.assertEqual(recipe.articolo, self.product)

    def test_simple_production_freezes_recipe_and_lines(self):
        from produzione.services import ProduzioneSemplificataService
        line = self.add_line()
        ProduzioneSemplificataService.apri_roboqbo(
            actor=self.planner, ricetta=self.recipe, numero_batch_previsti=1,
        )
        self.assertTrue(self.recipe.utilizzata)
        with self.assertRaises(ValidationError):
            RecipeService.update_line(actor=self.planner, riga=line, quantita="99")
        with self.assertRaises(ValidationError):
            RecipeService.remove_line(actor=self.planner, riga=line)
        self.recipe.articolo = self.ingredient
        with self.assertRaises(ValidationError):
            self.recipe.save()
        self.recipe.refresh_from_db()
        self.recipe.attiva = False
        self.recipe.save()
        clone = RecipeService.new_version(actor=self.planner, ricetta=self.recipe.pk, versione="2")
        self.assertNotEqual(clone.pk, self.recipe.pk)
        line.refresh_from_db()
        self.assertEqual(line.quantita, Decimal("2.5"))

    def test_administrator_can_manage_recipes(self):
        recipe = RecipeService.create(actor=self.administrator, articolo=self.product, nome="Nuova", versione="2")
        self.assertIsNotNone(recipe.pk)

    def test_operator_cannot_manage_recipe(self):
        with self.assertRaises(PermissionDenied):
            RecipeService.create(actor=self.operator, articolo=self.product, nome="Nuova", versione="2")
        with self.assertRaises(PermissionDenied):
            RecipeService.add_line(actor=self.operator, ricetta=self.recipe, quantita="1", articolo=self.ingredient)

    def test_unique_article_version(self):
        with self.assertRaises(ValidationError):
            Ricetta.objects.create(articolo=self.product, nome="Duplicata", versione="1")

    def test_same_version_different_article(self):
        Ricetta.objects.create(articolo=self.ingredient, nome="Semilavorato", versione="1")
        self.assertEqual(Ricetta.objects.count(), 2)

    def test_no_reference_quantity_field(self):
        self.assertNotIn("quantita_riferimento", {field.name for field in Ricetta._meta.fields})

    def test_line_with_both_targets_rejected(self):
        with self.assertRaises(ValidationError):
            self.add_line(articolo=self.ingredient, categoria_articolo=self.category)

    def test_line_without_targets_rejected(self):
        with self.assertRaises(ValidationError):
            self.add_line(articolo=None, categoria_articolo=None)

    def test_line_quantity_must_be_positive(self):
        for amount in ("0", "-1"):
            with self.subTest(amount=amount), self.assertRaises(ValidationError):
                self.add_line(amount=amount)

    def test_parent_category_matches_descendant_article(self):
        line = self.add_line(categoria_articolo=self.category)
        self.assertTrue(line.accetta_articolo(self.ingredient))
        self.assertTrue(line.accetta_articolo(self.product))
        self.assertFalse(line.accetta_articolo(self.packaging))

    def test_specific_article_does_not_match_other_article(self):
        line = self.add_line()
        self.assertTrue(line.accetta_articolo(self.ingredient))
        self.assertFalse(line.accetta_articolo(self.product))

    def test_db_enforces_xor_and_positive_quantity(self):
        line = self.add_line()
        table = connection.ops.quote_name(RigaRicetta._meta.db_table)
        for clause, params in (("articolo_id = NULL", []), ("categoria_articolo_id = %s", [self.category.pk]), ("quantita = %s", [0]), ("quantita = %s", [-1])):
            with self.subTest(clause=clause, params=params), self.assertRaises(IntegrityError), transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute(f"UPDATE {table} SET {clause} WHERE id = %s", [*params, line.pk])

    def test_unused_formula_can_be_edited(self):
        line = self.add_line()
        line.quantita = Decimal("3")
        line.save()
        line.refresh_from_db()
        self.assertEqual(line.quantita, 3)

    def test_unused_line_can_be_removed(self):
        line = self.add_line()
        RecipeService.remove_line(actor=self.planner, riga=line)
        self.assertEqual(self.recipe.righe.count(), 0)

    def test_line_update_service(self):
        line = self.add_line()
        RecipeService.update_line(actor=self.planner, riga=line, quantita="3.25", note="Formula aggiornata")
        line.refresh_from_db()
        self.assertEqual(line.quantita, Decimal("3.25"))
        self.assertEqual(line.note, "Formula aggiornata")

    def test_operator_cannot_update_line(self):
        line = self.add_line()
        with self.assertRaises(PermissionDenied):
            RecipeService.update_line(actor=self.operator, riga=line, quantita="5")

    def test_line_cannot_be_moved_between_recipes(self):
        line = self.add_line()
        other = Ricetta.objects.create(articolo=self.product, nome="Altra", versione="2")
        line.ricetta = other
        with self.assertRaises(ValidationError):
            line.save()

    def test_new_version_copies_formula_without_changing_original(self):
        line = self.add_line()
        copy = RecipeService.new_version(actor=self.planner, ricetta=self.recipe, versione="2")
        self.assertNotEqual(copy.pk, self.recipe.pk)
        self.assertEqual(copy.righe.get().quantita, line.quantita)
        self.assertNotEqual(copy.righe.get().pk, line.pk)
        copied_line = copy.righe.get()
        copied_line.quantita = Decimal("8")
        copied_line.save()
        line.refresh_from_db()
        self.assertEqual(line.quantita, Decimal("2.5"))

    def test_clone_failure_rolls_back_new_recipe(self):
        self.add_line()
        with patch.object(RigaRicetta, "save", side_effect=ValidationError("Errore simulato")), self.assertRaises(ValidationError):
            RecipeService.new_version(actor=self.planner, ricetta=self.recipe, versione="2")
        self.assertFalse(Ricetta.objects.filter(versione="2").exists())

    def test_duplicate_clone_version_has_no_effect(self):
        self.add_line()
        with self.assertRaises(ValidationError):
            RecipeService.new_version(actor=self.planner, ricetta=self.recipe, versione="1")
        self.assertEqual(Ricetta.objects.count(), 1)
        self.assertEqual(RigaRicetta.objects.count(), 1)

    def test_used_recipe_guard_allows_only_activation_changes(self):
        with patch.object(Ricetta, "utilizzata", property(lambda obj: obj.pk == self.recipe.pk)):
            self.recipe.nome = "Alterata"
            with self.assertRaises(ValidationError):
                self.recipe.save()
            self.recipe.refresh_from_db()
            self.recipe.attiva = False
            self.recipe.save()
        self.recipe.refresh_from_db()
        self.assertFalse(self.recipe.attiva)

    def test_used_formula_guard_prevents_line_mutations(self):
        line = self.add_line()
        with patch.object(Ricetta, "utilizzata", property(lambda obj: obj.pk == self.recipe.pk)):
            with self.assertRaises(ValidationError):
                self.add_line()
            line.quantita = Decimal("3")
            with self.assertRaises(ValidationError):
                line.save()
            with self.assertRaises(ValidationError):
                line.delete()
            with self.assertRaises(ValidationError):
                self.recipe.delete()

    def test_used_recipe_can_be_copied_to_new_version(self):
        self.add_line()
        with patch.object(Ricetta, "utilizzata", property(lambda obj: obj.pk == self.recipe.pk)):
            copy = RecipeService.new_version(actor=self.planner, ricetta=self.recipe, versione="2")
        self.assertEqual(copy.righe.count(), 1)

    def test_requirements_are_multiplied_per_line(self):
        first = self.add_line(amount="2.5")
        second = self.add_line(amount="100", articolo=self.packaging)
        result = RecipeService.requirements(actor=self.operator, ricetta=self.recipe, numero_batch=3)
        self.assertEqual([r.riga_id for r in result], [first.pk, second.pk])
        self.assertEqual([r.quantita_totale for r in result], [Decimal("7.5"), Decimal("300")])
        self.assertEqual([r.quantita_per_batch for r in result], [Decimal("2.5"), Decimal("100")])

    def test_recipe_ingredient_is_protected(self):
        self.add_line()
        with self.assertRaises(ProtectedError):
            self.ingredient.delete()

    def test_recipe_category_is_protected(self):
        self.add_line(categoria_articolo=self.other_category)
        with self.assertRaises(ProtectedError):
            self.other_category.delete()

    def test_read_permissions_are_more_permissive_than_write(self):
        for user in (self.operator, self.warehouse):
            self.assertTrue(user.has_perm("produzione.view_ricetta"))
            self.assertFalse(user.has_perm("produzione.change_ricetta"))
            self.assertFalse(user.has_perm("produzione.delete_rigaricetta"))
        self.assertTrue(self.planner.has_perm("produzione.delete_rigaricetta"))
        self.assertFalse(self.planner.has_perm("produzione.delete_ricetta"))

    def test_admin_is_consultable_for_operator(self):
        self.client.force_login(self.operator)
        response = self.client.get("/admin/produzione/ricetta/")
        self.assertEqual(response.status_code, 200)
        response = self.client.get("/admin/produzione/ricetta/add/")
        self.assertEqual(response.status_code, 403)

    def test_used_recipe_admin_is_readonly_except_activation(self):
        request = RequestFactory().get("/")
        request.user = self.planner
        recipe_admin = admin.site._registry[Ricetta]
        with patch.object(Ricetta, "utilizzata", property(lambda obj: True)):
            readonly = recipe_admin.get_readonly_fields(request, self.recipe)
        self.assertIn("versione", readonly)
        self.assertNotIn("attiva", readonly)
