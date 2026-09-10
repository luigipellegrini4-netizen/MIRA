from django.core.exceptions import ValidationError
from django.test import SimpleTestCase

from magazzino.services import Allocation, LotGenerationService, Position
from produzione.services.materials import validate_allocations


class ExecutionContractTests(SimpleTestCase):
    def test_alphabetic_suffixes_continue_after_z(self):
        for value, expected in ((1, "A"), (26, "Z"), (27, "AA"), (52, "AZ"), (53, "BA"), (702, "ZZ"), (703, "AAA")):
            with self.subTest(value=value):
                self.assertEqual(LotGenerationService.suffix(value), expected)

    def test_suffix_rejects_invalid_progressives(self):
        for value in (0, -1, True, "1", 1.5):
            with self.subTest(value=value), self.assertRaises(ValidationError):
                LotGenerationService.suffix(value)

    def test_allocations_must_cover_total(self):
        with self.assertRaises(ValidationError):
            validate_allocations([Allocation(Position(1), "2")], 3)

    def test_empty_or_invalid_allocations_rejected(self):
        for allocations in ([], [None], [Position(1)]):
            with self.subTest(allocations=allocations), self.assertRaises(ValidationError):
                validate_allocations(allocations, 1)

    def test_multiple_allocations_accepted(self):
        result = validate_allocations([Allocation(Position(1), "2"), Allocation(Position(2), "3")], 5)
        self.assertEqual(len(result), 2)
