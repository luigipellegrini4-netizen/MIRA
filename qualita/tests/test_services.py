from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from magazzino.tests.service_fixtures import ServiceFixtures
from produzione.models import TipoLavorazione
from produzione.services import ProductionCycleService, WorkExecutionService
from qualita.models import ParametroControllo, ControlloRichiestoTipoLavorazione, ControlloQualita
from qualita.services import QualityService


class QualityServiceTests(ServiceFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.kind = TipoLavorazione.objects.create(codice="QUALITY", nome="Controllo", genera_lotto=False)
        cls.parameter = ParametroControllo.objects.create(codice="TEMP", nome="Temperatura", tipo_dato="DECIMALE")
        cls.req = ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, parametro_controllo=cls.parameter, valore_minimo=10, valore_massimo=20)
        cls.cycle = ProductionCycleService.create(actor=cls.production, articolo=cls.article)
        cls.work = WorkExecutionService.plan(actor=cls.production, ciclo=cls.cycle, tipo_lavorazione=cls.kind)

    def start(self):
        self.work = WorkExecutionService.start(actor=self.operator, lavorazione=self.work)

    def record(self, value="15", **kwargs):
        return QualityService.record(actor=kwargs.pop("actor", self.operator), lavorazione=self.work, controllo_richiesto=self.req, valore=value, **kwargs)

    def test_required_missing_blocks_completion(self):
        self.start()
        with self.assertRaises(ValidationError):
            WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)

    def test_conforming_allows_completion(self):
        self.start()
        self.assertTrue(self.record().conforme)
        self.assertEqual(WorkExecutionService.complete(actor=self.operator, lavorazione=self.work).stato, "COMPLETATA")

    def test_failed_repeat_is_preserved_and_blocks(self):
        self.start()
        self.assertFalse(self.record("9").conforme)
        self.assertTrue(self.record("15").conforme)
        self.assertEqual(ControlloQualita.objects.count(), 2)
        with self.assertRaises(ValidationError):
            WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)

    def test_record_before_start_rejected(self):
        with self.assertRaises(ValidationError):
            self.record()

    def test_closed_work_rejected(self):
        self.start()
        self.record()
        WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)
        with self.assertRaises(ValidationError):
            self.record()

    def test_roles(self):
        self.start()
        for actor in (self.warehouse, self.manager, self.administrator):
            with self.assertRaises(PermissionDenied):
                self.record(actor=actor)
        for actor in (self.production, self.quality, self.operator):
            self.record(actor=actor)

    def test_history_cannot_be_changed(self):
        self.start()
        record = self.record()
        for operation in (record.save, record.delete, lambda: ControlloQualita.objects.all().update(conforme=False), lambda: ControlloQualita.objects.all().delete()):
            with self.assertRaises(ValidationError):
                operation()

    def test_used_requirement_frozen(self):
        self.req.valore_minimo = 0
        with self.assertRaises(ValidationError):
            self.req.save()

    def test_parameter_semantics_frozen(self):
        self.parameter.tipo_dato = "TESTO"
        with self.assertRaises(ValidationError):
            self.parameter.save()

    def test_cannot_add_required_control_retroactively(self):
        with self.assertRaises(ValidationError):
            ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=self.kind, parametro_controllo=self.parameter, determina_conformita=False)

    def test_wrong_type_requirement(self):
        other = TipoLavorazione.objects.create(codice="OTHER", nome="Altro", genera_lotto=False)
        req = ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=other, parametro_controllo=self.parameter, determina_conformita=False)
        self.start()
        with self.assertRaises(ValidationError):
            QualityService.record(actor=self.operator, lavorazione=self.work, controllo_richiesto=req, valore="15")

    def test_no_manual_override(self):
        self.start()
        with self.assertRaises(ValidationError):
            self.record("1", conforme=True)
        self.assertFalse(ControlloQualita.objects.exists())

    def make_control(self, kind, **criteria):
        process = TipoLavorazione.objects.create(codice="EXTRA", nome="Extra", genera_lotto=False)
        parameter = ParametroControllo.objects.create(codice="EXTRA", nome="Extra", tipo_dato=kind)
        req = ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=process, parametro_controllo=parameter, **criteria)
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=process)
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        return work, req

    def test_false_boolean_persisted(self):
        work, req = self.make_control("BOOLEANO", valore_booleano_atteso=False)
        result = QualityService.record(actor=self.quality, lavorazione=work, controllo_richiesto=req, valore=False)
        result.refresh_from_db()
        self.assertIs(result.valore_booleano, False)
        self.assertTrue(result.conforme)

    def test_text_assessment_persisted(self):
        work, req = self.make_control("TESTO")
        result = QualityService.record(actor=self.quality, lavorazione=work, controllo_richiesto=req, valore="Difetto visibile", conforme=False)
        self.assertFalse(result.conforme)
        self.assertTrue(QualityService.completion_errors(work))

    def test_informational_failure_does_not_block(self):
        work, req = self.make_control("INTERO", valore_minimo=1, determina_conformita=False)
        result = QualityService.record(actor=self.operator, lavorazione=work, controllo_richiesto=req, valore=0)
        self.assertFalse(result.conforme)
        self.assertEqual(WorkExecutionService.complete(actor=self.operator, lavorazione=work).stato, "COMPLETATA")

    def test_quality_permissions(self):
        self.assertTrue(self.administrator.has_perm("qualita.add_parametrocontrollo"))
        self.assertFalse(self.administrator.has_perm("qualita.view_controlloqualita"))
        self.assertTrue(self.manager.has_perm("qualita.view_controlloqualita"))
        self.assertFalse(self.production.has_perm("qualita.change_parametrocontrollo"))
        self.assertTrue(self.production.has_perm("qualita.add_controllorichiestotipolavorazione"))
        self.assertFalse(self.quality.has_perm("qualita.add_controlloqualita"))

    def test_invalid_configuration(self):
        process = TipoLavorazione.objects.create(codice="BAD", nome="Bad")
        for criteria in ({"valore_minimo": 20, "valore_massimo": 10}, {"valore_booleano_atteso": True}, {}):
            with self.assertRaises(ValidationError):
                ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=process, parametro_controllo=self.parameter, **criteria)
