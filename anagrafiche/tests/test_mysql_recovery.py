from types import SimpleNamespace

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.core.management.base import CommandError
from django.db.migrations.state import ProjectState
from django.test import SimpleTestCase
from importlib import import_module
from unittest.mock import patch

from anagrafiche.management.commands.recover_anagrafiche_initial import foreign_key_present, validate_columns
from anagrafiche.models import CategoriaArticolo


class MysqlRecoveryTests(SimpleTestCase):
    def test_dummy_backend_is_refused(self):
        with patch("anagrafiche.management.commands.recover_anagrafiche_initial.connection") as conn, self.assertRaises(CommandError):
            conn.vendor = "dummy"
            call_command("recover_anagrafiche_initial")

    def test_initial_migration_has_no_check_on_autoincrement(self):
        migration = import_module("anagrafiche.migrations.0001_initial").Migration("0001_initial", "anagrafiche")
        state = migration.mutate_state(ProjectState())
        category = state.apps.get_model("anagrafiche", "CategoriaArticolo")
        self.assertEqual(category._meta.constraints, [])
        article = state.apps.get_model("anagrafiche", "Articolo")
        self.assertEqual(len(article._meta.constraints), 3)

    def test_direct_cycle_is_still_rejected(self):
        category = CategoriaArticolo(pk=1, codice="A", nome="A")
        category.categoria_padre = category
        with self.assertRaises(ValidationError):
            category.clean()

    def test_indirect_cycle_is_still_rejected(self):
        parent = CategoriaArticolo(pk=1, codice="A", nome="A")
        child = CategoriaArticolo(pk=2, codice="B", nome="B", categoria_padre=parent)
        parent.categoria_padre = child
        with self.assertRaises(ValidationError):
            parent.clean()

    def test_unexpected_column_is_rejected(self):
        model = SimpleNamespace(_meta=SimpleNamespace(local_fields=[], db_table="test"))
        with self.assertRaises(CommandError):
            validate_columns(model, {"unexpected": ("int", False)}, None)

    def test_unexpected_type_is_rejected(self):
        field = SimpleNamespace(column="value", null=False, db_type=lambda _: "bigint")
        model = SimpleNamespace(_meta=SimpleNamespace(local_fields=[field], db_table="test"))
        with self.assertRaises(CommandError):
            validate_columns(model, {"value": ("varchar(10)", False)}, None)

    def test_unexpected_nullability_is_rejected(self):
        field = SimpleNamespace(column="value", null=False, db_type=lambda _: "bigint")
        model = SimpleNamespace(_meta=SimpleNamespace(local_fields=[field], db_table="test"))
        with self.assertRaises(CommandError):
            validate_columns(model, {"value": ("bigint", True)}, None)

    def test_mysql_boolean_alias_is_accepted(self):
        field = SimpleNamespace(column="active", null=False, db_type=lambda _: "bool")
        model = SimpleNamespace(_meta=SimpleNamespace(local_fields=[field], db_table="test"))
        validate_columns(model, {"active": ("tinyint(1)", False)}, None)

    def test_mysql_decimal_alias_is_accepted(self):
        field = SimpleNamespace(column="scorta_minima", null=False, db_type=lambda _: "numeric(18, 6)")
        model = SimpleNamespace(_meta=SimpleNamespace(local_fields=[field], db_table="anagrafiche_articolo"))
        validate_columns(model, {"scorta_minima": ("decimal(18,6)", False)}, None)

    def test_decimal_precision_scale_and_signedness_are_not_ignored(self):
        field = SimpleNamespace(column="value", null=False, db_type=lambda _: "numeric(18, 6)")
        model = SimpleNamespace(_meta=SimpleNamespace(local_fields=[field], db_table="test"))
        for kind in ("decimal(10,6)", "decimal(18,2)", "decimal(18,6) unsigned"):
            with self.subTest(kind=kind), self.assertRaises(CommandError):
                validate_columns(model, {"value": (kind, False)}, None)

    def test_decimal_nullability_is_still_checked(self):
        field = SimpleNamespace(column="value", null=False, db_type=lambda _: "numeric(18, 6)")
        model = SimpleNamespace(_meta=SimpleNamespace(local_fields=[field], db_table="test"))
        with self.assertRaises(CommandError):
            validate_columns(model, {"value": ("decimal(18,6)", True)}, None)

    def test_missing_foreign_key_is_detected(self):
        field = CategoriaArticolo._meta.get_field("categoria_padre")
        self.assertFalse(foreign_key_present({}, field))

    def test_existing_foreign_key_is_recognized(self):
        field = CategoriaArticolo._meta.get_field("categoria_padre")
        constraints = {"fk": {"foreign_key": ("anagrafiche_categoriaarticolo", "id"), "columns": ["categoria_padre_id"]}}
        self.assertTrue(foreign_key_present(constraints, field))

    def test_wrong_foreign_key_is_rejected(self):
        field = CategoriaArticolo._meta.get_field("categoria_padre")
        constraints = {"fk": {"foreign_key": ("wrong_table", "id"), "columns": ["categoria_padre_id"]}}
        with self.assertRaises(CommandError):
            foreign_key_present(constraints, field)
