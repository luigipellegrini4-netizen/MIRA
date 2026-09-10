from decimal import Decimal
from types import SimpleNamespace as NS
from unittest.mock import Mock
from django.core.exceptions import ValidationError
from django.test import SimpleTestCase
from magazzino.services import Allocation, Position
from produzione.services import InputSelection
from produzione.services.recipe_inputs import recipe_coverage, RecipeInputProposal


class RecipeConsumptionRulesTests(SimpleTestCase):
    def test_selection_requires_exactly_one_theoretical_source(self):
        for sources in ({}, {"riga_ricetta": 2, "requisito_input": 3}):
            with self.subTest(sources=sources), self.assertRaises(ValidationError):
                InputSelection(1, "2", [Allocation(Position(1), "2")], **sources)

    def test_selection_normalizes_ids_and_preserves_exact_decimal(self):
        item = InputSelection(1, ".050", [Allocation(Position(1), ".050")], riga_ricetta=2)
        self.assertEqual(item.quantita, Decimal(".050"))
        self.assertIsInstance(item.origini, tuple)
        self.assertEqual(item.riga_ricetta, 2)

    def test_selection_rejects_allocation_mismatch(self):
        with self.assertRaises(ValidationError):
            InputSelection(1, "2", [Allocation(Position(1), "1")], riga_ricetta=2)

    def coverage(self, ids, matches):
        rows = [NS(pk=i, accetta_articolo=lambda article, i=i: i in matches) for i in (1, 2)]
        work = NS(ricetta_id=1, ricetta=NS(righe=NS(all=lambda: rows)))
        records = [NS(riga_ricetta_id=i, lotto=NS(articolo=Mock())) for i in ids]
        return recipe_coverage(work, records)

    def test_partial_explicit_coverage_does_not_infer_other_rows(self):
        self.assertEqual(len(self.coverage([1, None], [2])), 1)

    def test_legacy_input_cannot_cover_two_ambiguous_rows(self):
        self.assertEqual(len(self.coverage([None], [1, 2])), 2)

    def test_legacy_unambiguous_match_preserved(self):
        self.assertEqual(len(self.coverage([None], [1])), 1)

    def test_proposal_with_any_shortage_is_incomplete(self):
        self.assertFalse(RecipeInputProposal((), ({"mancante": Decimal(".001")},)).completa)
        self.assertTrue(RecipeInputProposal((), ({"mancante": Decimal("0")},)).completa)
