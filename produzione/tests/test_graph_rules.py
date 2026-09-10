from django.core.exceptions import PermissionDenied, ValidationError
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase
from produzione.services import GenealogyService
from produzione.services.graph import walk_lots, has_cycle


class GraphRuleTests(SimpleTestCase):
    def walk(self, graph, limit=100):
        return walk_lots(1, lambda frontier: {target for source in frontier for target in graph.get(source, [])}, limit)

    def test_leaf(self):
        self.assertEqual(self.walk({}), ({1}, set()))

    def test_diamond_is_not_cycle(self):
        graph = {1: [2, 3], 2: [4], 3: [4]}
        self.assertEqual(self.walk(graph), ({1, 2, 3, 4}, set()))
        self.assertFalse(has_cycle([(1, 2), (1, 3), (2, 4), (3, 4)]))

    def test_cycles_terminate_and_are_identified(self):
        graph = {1: [2], 2: [3], 3: [1]}
        self.assertEqual(self.walk(graph), ({1, 2, 3}, set()))
        self.assertTrue(has_cycle([(1, 2), (2, 3), (3, 1)]))

    def test_self_loop(self):
        self.assertEqual(self.walk({1: [1]}), ({1}, set()))
        self.assertTrue(has_cycle([(1, 1)]))

    def test_parallel_edges_not_cycle(self):
        self.assertFalse(has_cycle([(1, 2), (1, 2)]))

    def test_limit_is_explicit_and_deterministic(self):
        self.assertEqual(self.walk({1: [4, 3, 2]}, 2), ({1, 2}, {3, 4}))

    def test_chain_does_not_use_python_recursion(self):
        graph = {i: [i + 1] for i in range(1, 2000)}
        visited, omitted = self.walk(graph, 2500)
        self.assertEqual(len(visited), 2000)
        self.assertFalse(omitted)

    def test_invalid_limits(self):
        for limit in (0, -1, True, 1.5, "10", 10001):
            with self.assertRaises(ValidationError):
                self.walk({}, limit)

    def test_permission_checked_before_database(self):
        with self.assertRaises(PermissionDenied):
            GenealogyService.upstream(actor=AnonymousUser(), lotto=1)
