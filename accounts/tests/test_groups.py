from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase

from accounts.permissions import A, M, OP, RM, RQ


class GroupIntegrationTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("bootstrap_roles", verbosity=0)

    def user_in(self, *roles):
        user = get_user_model().objects.create_user(username="tester", password="Test-only-Password-892!")
        user.groups.set(Group.objects.filter(name__in=roles))
        return user

    def test_bootstrap_is_idempotent(self):
        before = {g.name: set(g.permissions.values_list("pk", flat=True)) for g in Group.objects.all()}
        call_command("bootstrap_roles", verbosity=0)
        after = {g.name: set(g.permissions.values_list("pk", flat=True)) for g in Group.objects.all()}
        self.assertEqual(before, after)
        self.assertEqual(len(after), 6)

    def test_admin_is_not_operator(self):
        user = self.user_in(A)
        self.assertTrue(user.has_perm("auth.change_user"))
        self.assertFalse(user.has_perm("auth.can_receive_goods"))
        self.assertFalse(user.has_perm("auth.can_execute_production"))

    def test_multiple_groups_are_cumulative(self):
        user = self.user_in(OP, RM)
        self.assertTrue(user.has_perm("auth.can_execute_production"))
        self.assertTrue(user.has_perm("auth.can_adjust_inventory"))

    def test_warehouse_operator(self):
        user = self.user_in(M)
        self.assertTrue(user.has_perm("auth.can_receive_goods"))
        self.assertTrue(user.has_perm("auth.can_transfer_stock"))
        self.assertFalse(user.has_perm("auth.can_adjust_inventory"))

    def test_production_operator(self):
        user = self.user_in(OP)
        self.assertTrue(user.has_perm("auth.can_execute_production"))
        self.assertFalse(user.has_perm("auth.can_plan_production"))

    def test_quality_permissions(self):
        user = self.user_in(RQ)
        self.assertTrue(user.has_perm("auth.can_manage_nc"))
        self.assertFalse(user.has_perm("auth.can_adjust_inventory"))

    def test_inactive_superuser_is_denied(self):
        user = get_user_model().objects.create_superuser("tech", password="Test-only-Password-892!")
        user.is_active = False
        user.save()
        self.assertFalse(user.has_perm("auth.can_receive_goods"))

    def test_magazziniere_legge_ma_non_modifica_anagrafiche(self):
        user = self.user_in(M)
        self.assertTrue(user.has_perm("anagrafiche.view_articolo"))
        self.assertTrue(user.has_perm("magazzino.view_giacenza"))
        self.assertFalse(user.has_perm("anagrafiche.change_articolo"))
        self.assertFalse(user.has_perm("magazzino.add_movimento"))

    def test_responsabile_magazzino_gestisce_articoli_non_categorie(self):
        user = self.user_in(RM)
        self.assertTrue(user.has_perm("anagrafiche.change_articolo"))
        self.assertTrue(user.has_perm("anagrafiche.change_ubicazione"))
        self.assertFalse(user.has_perm("anagrafiche.change_categoriaarticolo"))

    def test_admin_gestisce_anagrafiche_senza_scritture_stock(self):
        user = self.user_in(A)
        self.assertTrue(user.has_perm("anagrafiche.add_articolo"))
        self.assertFalse(user.has_perm("magazzino.change_giacenza"))
        self.assertFalse(user.has_perm("magazzino.add_movimento"))
