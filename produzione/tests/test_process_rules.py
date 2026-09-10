from types import SimpleNamespace

from django.contrib import admin
from django.core.exceptions import ValidationError
from django.db.migrations.loader import MigrationLoader
from django.test import SimpleTestCase

from produzione.management.commands.bootstrap_process_types import DEFAULT_TYPES
from produzione.models import (CicloProduzione, Lavorazione, InputLavorazione, OutputLavorazione,
                               RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione)


class ProcessRuleTests(SimpleTestCase):
    def test_input_needs_at_least_one_filter(self):
        with self.assertRaises(ValidationError):
            RequisitoInputTipoLavorazione(nome="Input").clean()

    def test_input_rejects_both_article_and_category(self):
        with self.assertRaises(ValidationError):
            RequisitoInputTipoLavorazione(nome="Input", articolo_id=1, categoria_articolo_id=1).clean()

    def test_input_can_filter_only_origin_type(self):
        RequisitoInputTipoLavorazione(nome="Input", tipo_lavorazione_origine_id=1).clean()

    def test_input_can_combine_article_with_origin(self):
        RequisitoInputTipoLavorazione(nome="Input", articolo_id=1, tipo_lavorazione_origine_id=1).clean()

    def test_output_needs_article_or_category(self):
        with self.assertRaises(ValidationError):
            RequisitoOutputTipoLavorazione(nome="Output").clean()

    def test_default_processes_are_configuration_data(self):
        self.assertEqual(len(DEFAULT_TYPES), 8)
        self.assertTrue(DEFAULT_TYPES["INVASETTAMENTO"][1])
        self.assertFalse(DEFAULT_TYPES["PASTORIZZAZIONE"][1])
        self.assertFalse(DEFAULT_TYPES["ABBATTIMENTO_VUOTO"][1])
        self.assertFalse(DEFAULT_TYPES["INSCATOLAMENTO"][1])

    def test_bulk_writes_and_deletes_are_blocked(self):
        for model in (CicloProduzione, Lavorazione, InputLavorazione, OutputLavorazione):
            with self.subTest(model=model.__name__):
                with self.assertRaises(ValidationError):
                    model.objects.all().update(note="retroattivo")
                with self.assertRaises(ValidationError):
                    model.objects.all().delete()

    def test_execution_admin_is_readonly(self):
        request = SimpleNamespace(user=SimpleNamespace(is_superuser=True))
        for model in (CicloProduzione, Lavorazione, InputLavorazione, OutputLavorazione):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(request))
            self.assertFalse(model_admin.has_change_permission(request))
            self.assertFalse(model_admin.has_delete_permission(request))

    def test_migration_graph_has_no_cycle(self):
        loader = MigrationLoader(None)
        loader.graph.ensure_not_cyclic()
        target = ("magazzino", "0002_lotto_lavorazione_origine_and_more")
        plan = loader.graph.forwards_plan(target)
        self.assertIn(("produzione", "0002_tipolavorazione_cicloproduzione_lavorazione_and_more"), plan)
