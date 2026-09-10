from datetime import timedelta
from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, connection, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase
from django.utils import timezone

from anagrafiche.models import Articolo, CategoriaArticolo
from magazzino.models import Lotto, Movimento, Giacenza
from magazzino.services import MovementService
from magazzino.tests.service_fixtures import ServiceFixtures
from produzione.models import (Ricetta, RigaRicetta, TipoLavorazione, CicloProduzione, Lavorazione,
                               RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione,
                               InputLavorazione, OutputLavorazione)
from produzione.models.protections import _execution_write


class ProcessModelTests(ServiceFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.kind = TipoLavorazione.objects.create(codice="TRASFORMAZIONE", nome="Trasformazione")
        cls.input_req = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, nome="Materia prima", categoria_articolo=cls.category)
        cls.multi_req = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, nome="Più lotti", articolo=cls.article, multiplo=True)
        cls.output_req = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, nome="Prodotto", articolo=cls.article, prefisso_lotto="INT")
        cls.recipe = Ricetta.objects.create(articolo=cls.article, nome="Formula", versione="1")
        cls.recipe_line = RigaRicetta.objects.create(ricetta=cls.recipe, articolo=cls.article, quantita=1)
        cls.cycle = CicloProduzione.objects.create(articolo=cls.article, creato_da=cls.production)
        cls.work = Lavorazione.objects.create(ciclo_produzione=cls.cycle, tipo_lavorazione=cls.kind, ricetta=cls.recipe)

    def start(self, work=None):
        work = work or self.work
        with _execution_write():
            work.stato = "IN_CORSO"
            work.data_ora_inizio = timezone.now()
            work.eseguita_da = self.operator
            work.save()
        return work

    def input(self, **kwargs):
        return InputLavorazione.objects.create(lavorazione=self.work, requisito_input=kwargs.pop("requisito_input", self.input_req), lotto=kwargs.pop("lotto", self.lot), quantita=kwargs.pop("quantita", "5"), **kwargs)

    def output_lot(self, work=None, code="PROD"):
        return Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto=code, lavorazione_origine=work or self.work)

    def test_planned_work_has_no_execution_times(self):
        self.assertEqual(self.work.stato, "PIANIFICATA")
        self.assertIsNone(self.work.data_ora_inizio)

    def test_state_cannot_be_changed_directly(self):
        self.work.stato = "IN_CORSO"
        self.work.data_ora_inizio = timezone.now()
        self.work.eseguita_da = self.operator
        with self.assertRaises(ValidationError):
            self.work.save()

    def test_started_work_cannot_change_configuration(self):
        self.start()
        self.work.ricetta = None
        with self.assertRaises(ValidationError):
            self.work.save()

    def test_completed_work_cannot_be_modified(self):
        self.start()
        with _execution_write():
            self.work.stato = "COMPLETATA"
            self.work.data_ora_fine = timezone.now()
            self.work.save()
        self.work.note = "modifica retroattiva"
        with self.assertRaises(ValidationError):
            self.work.save()

    def test_cancelled_work_cannot_have_start_time(self):
        with _execution_write(), self.assertRaises(ValidationError):
            self.work.stato = "ANNULLATA"
            self.work.data_ora_inizio = timezone.now()
            self.work.save()

    def test_interrupted_work_requires_start(self):
        with _execution_write(), self.assertRaises(ValidationError):
            self.work.stato = "INTERROTTA"
            self.work.data_ora_fine = timezone.now()
            self.work.save()

    def test_end_before_start_rejected(self):
        self.start()
        with _execution_write(), self.assertRaises(ValidationError):
            self.work.stato = "INTERROTTA"
            self.work.data_ora_fine = self.work.data_ora_inizio - timedelta(seconds=1)
            self.work.save()

    def test_recipe_frozen_by_actual_work_reference(self):
        self.assertTrue(self.recipe.utilizzata)
        self.recipe_line.quantita = Decimal("2")
        with self.assertRaises(ValidationError):
            self.recipe_line.save()
        with self.assertRaises(ValidationError):
            self.recipe_line.delete()
        self.recipe.versione = "retroattiva"
        with self.assertRaises(ValidationError):
            self.recipe.save()

    def test_used_type_cannot_change_formula(self):
        self.kind.genera_lotto = False
        with self.assertRaises(ValidationError):
            self.kind.save()
        self.kind.refresh_from_db()
        self.kind.attivo = False
        self.kind.save()
        self.assertFalse(self.kind.attivo)

    def test_used_requirement_cannot_change_or_delete(self):
        self.input_req.multiplo = True
        with self.assertRaises(ValidationError):
            self.input_req.save()
        with self.assertRaises(ValidationError):
            self.input_req.delete()

    def test_input_requires_running_work(self):
        with self.assertRaises(ValidationError):
            self.input()

    def test_input_matches_category(self):
        self.start()
        record = self.input()
        self.assertEqual(record.lotto, self.lot)

    def test_input_accepts_descendant_category(self):
        child = CategoriaArticolo.objects.create(codice="CHILD", nome="Discendente", categoria_padre=self.category)
        article = Articolo.objects.create(codice="CHILD", descrizione="Ingrediente", categoria=child, unita_misura="KG")
        lot = Lotto.objects.create(articolo=article, fornitore=self.supplier, tipo="ACQUISTO", codice_lotto="CHILD")
        self.start()
        self.input(lotto=lot)

    def test_input_rejects_unrelated_article(self):
        category = CategoriaArticolo.objects.create(codice="OTHER", nome="Altro")
        article = Articolo.objects.create(codice="OTHER", descrizione="Altro", categoria=category, unita_misura="PZ")
        lot = Lotto.objects.create(articolo=article, fornitore=self.supplier, tipo="ACQUISTO", codice_lotto="OTHER")
        self.start()
        with self.assertRaises(ValidationError):
            self.input(lotto=lot)

    def test_input_requirement_from_wrong_type_rejected(self):
        other = TipoLavorazione.objects.create(codice="OTHER", nome="Altro")
        requirement = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=other, nome="Altro", articolo=self.article)
        self.start()
        with self.assertRaises(ValidationError):
            self.input(requisito_input=requirement)

    def test_single_input_requirement_rejects_second_record(self):
        self.start()
        self.input()
        with self.assertRaises(ValidationError):
            self.input()

    def test_multiple_input_requirement_allows_multiple_records(self):
        self.start()
        self.input(requisito_input=self.multi_req)
        self.input(requisito_input=self.multi_req)
        self.assertEqual(self.work.inputs.count(), 2)

    def test_origin_filter_uses_lot_work_without_needing_output(self):
        downstream = TipoLavorazione.objects.create(codice="DOWN", nome="Downstream")
        req = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=downstream, nome="Da monte", tipo_lavorazione_origine=self.kind)
        identity = self.output_lot()
        self.assertTrue(req.accetta_lotto(identity))
        self.assertFalse(req.accetta_lotto(self.lot))
        self.assertEqual(OutputLavorazione.objects.count(), 0)

    def test_work_cannot_consume_own_output_lot(self):
        self.start()
        identity = self.output_lot()
        with self.assertRaises(ValidationError):
            self.input(lotto=identity)

    def test_output_identity_can_precede_consolidation(self):
        self.start()
        identity = self.output_lot()
        self.assertEqual(identity.lavorazione_origine_id, self.work.pk)
        self.assertFalse(self.work.outputs.exists())
        self.assertFalse(Giacenza.objects.exists())

    def test_output_requires_correct_origin_and_requirement(self):
        self.start()
        identity = self.output_lot()
        result = OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=identity, quantita=5)
        self.assertEqual(result.lotto, identity)
        self.assertFalse(Movimento.objects.exists())  # modello non movimenta stock

    def test_output_rejects_purchase_lot(self):
        self.start()
        with self.assertRaises(ValidationError):
            OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=self.lot, quantita=5)

    def test_output_rejects_requirement_from_other_type(self):
        kind = TipoLavorazione.objects.create(codice="OTHER", nome="Altro processo")
        req = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Altro", articolo=self.article)
        self.start()
        with self.assertRaises(ValidationError):
            OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=req, lotto=self.output_lot(), quantita=5)

    def test_single_output_requirement_rejects_second_record(self):
        self.start()
        identity = self.output_lot()
        OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=identity, quantita=5)
        with self.assertRaises(ValidationError):
            OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=identity, quantita=1)

    def test_input_and_output_quantities_must_be_positive(self):
        self.start()
        with self.assertRaises(ValidationError):
            self.input(quantita=0)
        with self.assertRaises(ValidationError):
            OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=self.output_lot(), quantita=-1)

    def test_origin_filter_rejects_different_production_type(self):
        other = TipoLavorazione.objects.create(codice="OTHER", nome="Altro processo")
        req = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=other, nome="Origine", articolo=self.article, tipo_lavorazione_origine=other)
        self.assertFalse(req.accetta_lotto(self.output_lot()))

    def test_output_rejects_wrong_work_origin(self):
        other = Lavorazione.objects.create(ciclo_produzione=self.cycle, tipo_lavorazione=self.kind)
        identity = self.output_lot(work=other)
        self.start()
        with self.assertRaises(ValidationError):
            OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=identity, quantita=5)

    def test_non_generating_type_cannot_configure_output(self):
        kind = TipoLavorazione.objects.create(codice="TRATTAMENTO", nome="Trattamento", genera_lotto=False)
        with self.assertRaises(ValidationError):
            RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=kind, nome="Fittizio", articolo=self.article)

    def test_non_generating_type_cannot_create_lot(self):
        kind = TipoLavorazione.objects.create(codice="TRATTAMENTO", nome="Trattamento", genera_lotto=False)
        work = Lavorazione.objects.create(ciclo_produzione=self.cycle, tipo_lavorazione=kind)
        with self.assertRaises(ValidationError):
            self.output_lot(work=work)

    def test_input_can_link_multiple_consumption_movements(self):
        self.start()
        record = self.input()
        self.load()
        for amount in ("2", "3"):
            MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita=amount, origine=self.position, input_lavorazione=record)
        self.assertEqual(record.movimenti.count(), 2)
        self.assertEqual(Giacenza.objects.get().quantita, 5)

    def test_linked_consumption_cannot_exceed_declared_input(self):
        self.start()
        record = self.input()
        self.load()
        with self.assertRaises(ValidationError):
            MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="6", origine=self.position, input_lavorazione=record)
        self.assertEqual(Giacenza.objects.get().quantita, 10)

    def test_linked_consumption_rejects_other_lot(self):
        self.start()
        record = self.input()
        other = Lotto.objects.create(articolo=self.article, fornitore=self.supplier, tipo="ACQUISTO", codice_lotto="OTHER")
        self.load(lot=other)
        with self.assertRaises(ValidationError):
            MovementService.register(actor=self.operator, lotto=other, tipo="CONSUMO", quantita="2", origine=self.position, input_lavorazione=record)
        self.assertEqual(Giacenza.objects.get().quantita, 10)

    def test_completed_work_rejects_new_linked_movements(self):
        self.start()
        record = self.input()
        self.load()
        with _execution_write():
            self.work.stato = "COMPLETATA"
            self.work.data_ora_fine = timezone.now()
            self.work.save()
        with self.assertRaises(ValidationError):
            MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="2", origine=self.position, input_lavorazione=record)

    def test_movement_cannot_link_both_input_and_output(self):
        self.start()
        input_record = self.input()
        output_record = OutputLavorazione.objects.create(lavorazione=self.work, requisito_output=self.output_req, lotto=self.output_lot(), quantita=5)
        move = Movimento(tipo="CONSUMO", lotto=self.lot, quantita=1, eseguito_da=self.operator, ubicazione_origine=self.location,
                         input_lavorazione=input_record, output_lavorazione=output_record)
        with self.assertRaises(ValidationError):
            move.full_clean()
        stored = self.load()
        with self.assertRaises(IntegrityError), transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("UPDATE magazzino_movimento SET input_lavorazione_id=%s, output_lavorazione_id=%s WHERE id=%s", [input_record.pk, output_record.pk, stored.pk])

    def test_registered_material_cannot_be_changed(self):
        self.start()
        record = self.input()
        record.quantita = 3
        with self.assertRaises(ValidationError):
            record.save()
        with self.assertRaises(ValidationError):
            record.delete()

    def test_lot_origin_and_recipe_references_protect_history(self):
        self.output_lot()
        with self.assertRaises(ValidationError):
            self.work.delete()
        with self.assertRaises(ValidationError):
            self.recipe.delete()

    def test_seed_is_idempotent_and_preserves_custom_names(self):
        call_command("bootstrap_process_types", verbosity=0)
        existing = TipoLavorazione.objects.get(codice="ROBOQBO")
        existing.nome = "Nome personalizzato"
        existing.save()
        count = TipoLavorazione.objects.count()
        call_command("bootstrap_process_types", verbosity=0)
        self.assertEqual(TipoLavorazione.objects.count(), count)
        existing.refresh_from_db()
        self.assertEqual(existing.nome, "Nome personalizzato")

    def test_operator_reads_configuration_without_editing(self):
        self.assertTrue(self.operator.has_perm("produzione.view_lavorazione"))
        self.assertTrue(self.operator.has_perm("produzione.view_tipolavorazione"))
        self.assertFalse(self.operator.has_perm("produzione.add_tipolavorazione"))
        self.assertFalse(self.operator.has_perm("produzione.add_cicloproduzione"))
        self.assertTrue(self.production.has_perm("produzione.change_tipolavorazione"))
