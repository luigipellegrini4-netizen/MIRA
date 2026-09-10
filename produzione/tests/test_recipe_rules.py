from types import SimpleNamespace
from unittest.mock import patch

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase

from anagrafiche.models import Articolo, CategoriaArticolo
from produzione.models import Ricetta, RigaRicetta
from produzione.services import RecipeService


class RecipeRuleTests(SimpleTestCase):
    def test_line_requires_one_target(self):
        for article, category in ((None, None), (1, 1)):
            with self.subTest(article=article, category=category), self.assertRaises(ValidationError):
                RigaRicetta(articolo_id=article, categoria_articolo_id=category, quantita=1).clean()

    def test_direct_article_match(self):
        line = RigaRicetta(articolo_id=10, quantita=1)
        self.assertTrue(line.accetta_articolo(Articolo(pk=10)))
        self.assertFalse(line.accetta_articolo(Articolo(pk=11)))

    def test_category_accepts_descendant_without_leaf_requirement(self):
        parent = CategoriaArticolo(pk=1, nome="Ingredienti")
        child = CategoriaArticolo(pk=2, nome="Frutta", categoria_padre=parent)
        line = RigaRicetta(categoria_articolo=parent, quantita=1)
        self.assertTrue(line.accetta_articolo(Articolo(pk=10, categoria=child)))
        self.assertTrue(line.accetta_articolo(Articolo(pk=11, categoria=parent)))

    def test_unsaved_article_is_not_accepted(self):
        self.assertFalse(RigaRicetta(articolo_id=10, quantita=1).accetta_articolo(Articolo()))

    def test_empty_recipe_name_and_version_rejected(self):
        for name, version in (("", "1"), ("Nome", "   ")):
            with self.subTest(name=name), self.assertRaises(ValidationError):
                Ricetta(nome=name, versione=version).clean()

    def test_historical_formula_guard(self):
        # Isola la regola; l'integrazione con Lavorazione arriverà in fase 5.
        with patch.object(Ricetta, "utilizzata", property(lambda obj: True)), self.assertRaises(ValidationError):
            Ricetta().ensure_formula_editable()

    def test_direct_mass_changes_are_blocked(self):
        for queryset in (Ricetta.objects.all(), RigaRicetta.objects.all()):
            with self.assertRaises(ValidationError):
                queryset.update(note="modifica")
            with self.assertRaises(ValidationError):
                queryset.delete()
            with self.assertRaises(ValidationError):
                queryset.bulk_create([])

    def test_requirements_need_read_permission(self):
        actor = SimpleNamespace(is_authenticated=True, is_active=True, has_perm=lambda _: False)
        with self.assertRaises(PermissionDenied):
            RecipeService.requirements(actor=actor, ricetta=1)

    def test_batch_count_must_be_positive_integer(self):
        actor = SimpleNamespace(is_authenticated=True, is_active=True, has_perm=lambda _: True)
        for count in (0, -1, True, 1.5, "2"):
            with self.subTest(count=count), self.assertRaises(ValidationError):
                RecipeService.requirements(actor=actor, ricetta=1, numero_batch=count)
