from types import SimpleNamespace
from unittest.mock import Mock

from django.core.exceptions import PermissionDenied
from django.test import SimpleTestCase

from accounts.permissions import A, RP, RM, RQ, OP, M, RV, CAPABILITIES, ROLES, require_permission


class PolicyTests(SimpleTestCase):
    def test_seven_distinct_roles(self):
        self.assertEqual(len(set(ROLES)), 7)

    def test_admin_has_no_operational_bypass(self):
        for code in ("can_receive_goods", "can_execute_production", "can_adjust_inventory", "can_manage_nc"):
            self.assertNotIn(A, CAPABILITIES[code][1])

    def test_warehouse_staff_can_receive_transfer_but_not_adjust(self):
        for code in ("can_receive_goods", "can_transfer_stock"):
            self.assertEqual(CAPABILITIES[code][1], {RM, M})
        self.assertEqual(CAPABILITIES["can_adjust_inventory"][1], {RM})

    def test_operator_executes_but_does_not_plan(self):
        self.assertIn(OP, CAPABILITIES["can_execute_production"][1])
        self.assertEqual(CAPABILITIES["can_plan_production"][1], {RP})

    def test_quality_alone_manages_and_closes_nc(self):
        for code in ("can_manage_nc", "can_close_nc", "can_quarantine_stock", "can_reintegrate_stock", "can_scrap_nc_stock"):
            self.assertEqual(CAPABILITIES[code][1], {RQ})

    def test_all_operational_roles_can_open_nc(self):
        self.assertEqual(CAPABILITIES["can_open_nc"][1], {RP, RM, RQ, OP, M, RV})

    def test_permission_guard_calls_django(self):
        actor = SimpleNamespace(is_authenticated=True, is_active=True, has_perm=Mock(return_value=True))
        require_permission(actor, "can_receive_goods")
        actor.has_perm.assert_called_once_with("auth.can_receive_goods")

    def test_permission_guard_rejects_missing_permission(self):
        actor = SimpleNamespace(is_authenticated=True, is_active=True, has_perm=lambda _: False)
        with self.assertRaises(PermissionDenied):
            require_permission(actor, "can_receive_goods")

    def test_permission_guard_rejects_inactive_user(self):
        actor = SimpleNamespace(is_authenticated=True, is_active=False, has_perm=lambda _: True)
        with self.assertRaises(PermissionDenied):
            require_permission(actor, "can_receive_goods")

    def test_unknown_permission_is_programming_error(self):
        with self.assertRaises(ValueError):
            require_permission(None, "typo")
