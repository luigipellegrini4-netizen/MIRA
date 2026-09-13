from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from accounts.permissions import A, RM, ROLES


class BackupAccessTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        call_command("bootstrap_roles", verbosity=0)
        cls.users = {}
        for role in ROLES:
            user = get_user_model().objects.create_user(username=role)
            user.groups.add(Group.objects.get(name=role))
            cls.users[role] = user

    def test_non_admin_roles_cannot_access_backup_endpoints(self):
        for role, user in self.users.items():
            if role == A:
                continue
            self.client.force_login(user)
            for name in ("download_backup", "restore_backup", "reset_database"):
                with self.subTest(role=role, endpoint=name):
                    response = (self.client.get if name == "download_backup" else self.client.post)(reverse("ui:" + name))
                    self.assertEqual(response.status_code, 403)

    def test_admin_backup_and_configuration_without_inventory_rights(self):
        self.client.force_login(self.users[A])
        response = self.client.get(reverse("ui:manage_csv"))
        self.assertContains(response, "Scarica backup JSON")
        self.assertNotContains(response, "Controlla anteprima")
        with patch("interfaccia.csv_views.create_backup", return_value={"records": []}):
            self.assertEqual(self.client.get(reverse("ui:download_backup")).status_code, 200)
        self.assertEqual(self.client.post(reverse("ui:restore_backup")).status_code, 302)
        self.assertEqual(self.client.post(reverse("ui:reset_database")).status_code, 302)
        self.assertEqual(self.client.post(reverse("ui:manage_csv"), {}).status_code, 403)

    def test_warehouse_retains_csv_without_backup_controls(self):
        self.client.force_login(self.users[RM])
        response = self.client.get(reverse("ui:manage_csv"))
        self.assertContains(response, "Controlla anteprima")
        self.assertNotContains(response, "Scarica backup JSON")
        self.assertNotContains(response, "Azzera dati di prova")
