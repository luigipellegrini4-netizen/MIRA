import copy
import json

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.exceptions import ValidationError
from django.test import TransactionTestCase

from interfaccia.backup import create_backup, read_backup, restore_backup
from interfaccia.backup_validation import stock_differences


class BackupIntegrityTests(TransactionTestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(username="backup-check")
        self.group = Group.objects.create(name="backup-group")
        self.user.groups.add(self.group)
        self.payload = create_backup()

    def read(self, payload):
        return read_backup(json.dumps(payload).encode())

    def test_roundtrip_preserves_user_and_membership(self):
        self.read(self.payload)
        self.user.first_name = "changed"
        self.user.save()
        restore_backup(self.payload)
        self.user.refresh_from_db()
        self.assertEqual(self.user.first_name, "")
        self.assertEqual(list(self.user.groups.values_list("pk", flat=True)), [self.group.pk])

    def test_operational_backup_roundtrip(self):
        from produzione.services.demo_seed import seed_demo
        from magazzino.models import Giacenza, Movimento
        seed_demo()
        payload = create_backup()
        counts = (Giacenza.objects.count(), Movimento.objects.count())
        restore_backup(payload)
        self.assertEqual((Giacenza.objects.count(), Movimento.objects.count()), counts)
        self.assertEqual(stock_differences(create_backup()["records"]), [])

    def test_name_change_is_allowed(self):
        row = next(r for r in self.payload["records"] if r["model"] == "auth.group")
        row["fields"]["name"] = "Gruppo rinominato"
        restore_backup(self.payload)
        self.group.refresh_from_db()
        self.assertEqual(self.group.name, "Gruppo rinominato")

    def test_stock_mismatch_rejected_before_replacement(self):
        from produzione.services.demo_seed import seed_demo
        from magazzino.models import Giacenza
        seed_demo()
        payload = create_backup()
        row = next(r for r in payload["records"] if r["model"] == "magazzino.giacenza")
        stock = Giacenza.objects.get(pk=row["pk"])
        original = stock.quantita
        row["fields"]["quantita"] = str(original + 1)
        with self.assertRaises(ValidationError):
            restore_backup(payload)
        stock.refresh_from_db()
        self.assertEqual(stock.quantita, original)

    def test_missing_relation_rejected_before_replacement(self):
        payload = copy.deepcopy(self.payload)
        row = next(r for r in payload["records"] if r["model"] == "auth.user")
        row["fields"]["groups"] = [999999]
        with self.assertRaises(ValidationError):
            restore_backup(payload)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk).exists())

    def test_duplicate_identity_rejected(self):
        row = next(r for r in self.payload["records"] if r["model"] == "auth.user")
        self.payload["records"].append(copy.deepcopy(row))
        self.payload["counts"]["auth.User"] += 1
        with self.assertRaises(ValidationError):
            self.read(self.payload)

    def test_invalid_structure_and_missing_field_rejected(self):
        with self.assertRaises(ValidationError):
            self.read([])
        row = next(r for r in self.payload["records"] if r["model"] == "auth.user")
        del row["fields"]["username"]
        with self.assertRaises(ValidationError):
            self.read(self.payload)

    def test_unique_constraint_failure_rolls_back_replacement(self):
        row = copy.deepcopy(next(r for r in self.payload["records"] if r["model"] == "auth.user"))
        row["pk"] = 999999
        self.payload["records"].append(row)
        self.payload["counts"]["auth.User"] += 1
        with self.assertRaises(ValidationError):
            restore_backup(self.payload)
        self.assertTrue(get_user_model().objects.filter(pk=self.user.pk, username="backup-check").exists())

    def test_position_difference_detected_even_when_total_matches(self):
        records = [
            {"model": "magazzino.movimento", "fields": {"lotto": 1, "quantita": "600", "ubicazione_destinazione": 1}},
            {"model": "magazzino.giacenza", "fields": {"lotto": 1, "ubicazione": 2, "quantita": "600"}},
        ]
        self.assertEqual(len(stock_differences(records)), 2)
