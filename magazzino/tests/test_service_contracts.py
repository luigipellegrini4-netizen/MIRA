from decimal import Decimal
from types import SimpleNamespace

from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase

from magazzino.selectors import StockProposalService
from magazzino.services import Allocation, LotGenerationService, Position
from magazzino.services.types import quantity


class ServiceContractTests(SimpleTestCase):
    def test_positive_exact_quantity(self):
        self.assertEqual(quantity("0.000001"), Decimal("0.000001"))
        self.assertEqual(quantity(2), Decimal("2"))

    def test_invalid_quantities_are_rejected(self):
        for value in ("0", "-1", "NaN", "Infinity", "-Infinity", "abc", None, True, 0.1, "0.0000001", "1000000000000"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                quantity(value)

    def test_positions_normalize(self):
        self.assertEqual(Position(1, " a ", " b "), Position(1, "A", "B"))

    def test_position_rejects_bad_ids(self):
        for value in (None, 0, -1, True, "1"):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Position(value)

    def test_position_rejects_invalid_codes(self):
        for value in (1, "a" * 31):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                Position(1, value)

    def test_allocation_validates_amount_and_position(self):
        with self.assertRaises(ValidationError):
            Allocation(None, "1")
        with self.assertRaises(ValidationError):
            Allocation(Position(1), "0")

    def test_technical_codes_are_distinct(self):
        codes = {LotGenerationService.technical_code() for _ in range(100)}
        self.assertEqual(len(codes), 100)
        self.assertTrue(all(code.startswith("TECH-") and len(code) <= 100 for code in codes))

    def test_proposals_require_read_permission(self):
        actor = SimpleNamespace(is_authenticated=True, is_active=True, has_perm=lambda _: False)
        with self.assertRaises(PermissionDenied):
            StockProposalService.propose(actor=actor, articolo=1, quantita="1")
