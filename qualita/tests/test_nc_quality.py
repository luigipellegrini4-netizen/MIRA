from django.core.exceptions import ValidationError
from django.test import TestCase
from magazzino.tests.service_fixtures import ServiceFixtures
from produzione.models import TipoLavorazione
from produzione.services import ProductionCycleService, WorkExecutionService
from qualita.models import ParametroControllo, ControlloRichiestoTipoLavorazione
from qualita.services import NonConformityService as NC, QualityService


class NCQualityTests(ServiceFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.kind = TipoLavorazione.objects.create(codice="NC_TEST", nome="Test qualità", genera_lotto=False)
        parameter = ParametroControllo.objects.create(codice="NC_BOOL", nome="Conforme", tipo_dato="BOOLEANO")
        cls.req = ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, parametro_controllo=parameter, valore_booleano_atteso=True)
        cls.cycle = ProductionCycleService.create(actor=cls.production, articolo=cls.article)
        cls.work = WorkExecutionService.plan(actor=cls.production, ciclo=cls.cycle, tipo_lavorazione=cls.kind)
        cls.work = WorkExecutionService.start(actor=cls.operator, lavorazione=cls.work)
        cls.bad = QualityService.record(actor=cls.operator, lavorazione=cls.work, controllo_richiesto=cls.req, valore=False)

    def case(self):
        nc = NC.open(actor=self.operator, descrizione="Misura non conforme", controllo_qualita=self.bad)
        return NC.take_charge(actor=self.quality, non_conformita=nc)

    def correction(self, nc):
        return NC.action(actor=self.quality, non_conformita=nc, tipo_azione="CORREZIONE_PROCESSO", descrizione="Regolazione verificata")

    def verify(self, nc, measurement=None):
        return NC.verify(actor=self.quality, non_conformita=nc, esito="EFFICACE", descrizione="Controllo finale documentato", controllo_qualita=measurement)

    def complete(self):
        return WorkExecutionService.complete(actor=self.operator, lavorazione=self.work)

    def resolve(self, nc):
        self.correction(nc)
        good = QualityService.record(actor=self.quality, lavorazione=self.work, controllo_richiesto=self.req, valore=True)
        self.verify(nc, good)
        NC.close(actor=self.quality, non_conformita=nc, note="Correzione efficace confermata")

    def test_measurement_populates_work_reference(self):
        self.assertEqual(self.case().lavorazione_id, self.work.pk)

    def test_only_explicit_closure_resolves_quality_block(self):
        nc = self.case()
        self.correction(nc)
        good = QualityService.record(actor=self.quality, lavorazione=self.work, controllo_richiesto=self.req, valore=True)
        self.verify(nc, good)
        with self.assertRaises(ValidationError):
            self.complete()
        NC.close(actor=self.quality, non_conformita=nc, note="Risoluzione documentata")
        self.assertEqual(self.complete().stato, "COMPLETATA")
        self.bad.refresh_from_db()
        self.assertFalse(self.bad.conforme)

    def test_all_cases_for_same_measurement_must_be_closed(self):
        first, second = self.case(), self.case()
        self.resolve(first)
        with self.assertRaises(ValidationError):
            self.complete()
        self.resolve(second)
        self.complete()

    def test_generic_work_nc_does_not_resolve_specific_bad_measurement(self):
        nc = NC.open(actor=self.operator, descrizione="NC generica", lavorazione=self.work)
        nc = NC.take_charge(actor=self.quality, non_conformita=nc)
        self.resolve(nc)
        with self.assertRaises(ValidationError):
            self.complete()

    def test_unrelated_measurement_cannot_verify_nc(self):
        nc = self.case()
        self.correction(nc)
        other = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind)
        WorkExecutionService.start(actor=self.operator, lavorazione=other)
        unrelated = QualityService.record(actor=self.quality, lavorazione=other, controllo_richiesto=self.req, valore=True)
        with self.assertRaises(ValidationError):
            self.verify(nc, unrelated)

    def test_failed_measurement_cannot_verify_effectiveness(self):
        nc = self.case()
        self.correction(nc)
        bad = QualityService.record(actor=self.quality, lavorazione=self.work, controllo_richiesto=self.req, valore=False)
        with self.assertRaises(ValidationError):
            self.verify(nc, bad)

    def test_rework_must_be_completed_before_nc_closure(self):
        nc = self.case()
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind)
        NC.action(actor=self.quality, non_conformita=nc, tipo_azione="RILAVORAZIONE", descrizione="Nuovo tentativo", lavorazione=work)
        self.verify(nc)
        with self.assertRaises(ValidationError):
            NC.close(actor=self.quality, non_conformita=nc, note="Tentativo")
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        measurement = QualityService.record(actor=self.quality, lavorazione=work, controllo_richiesto=self.req, valore=True)
        WorkExecutionService.complete(actor=self.operator, lavorazione=work)
        self.verify(nc, measurement)
        NC.close(actor=self.quality, non_conformita=nc, note="Rilavorazione completata e verificata")

    def test_mismatched_initial_work_reference_rejected(self):
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind)
        with self.assertRaises(ValidationError):
            NC.open(actor=self.operator, descrizione="Errata", controllo_qualita=self.bad, lavorazione=work)

    def test_measurement_before_corrective_action_is_not_effectiveness_evidence(self):
        nc = self.case()
        measurement = QualityService.record(actor=self.quality, lavorazione=self.work, controllo_richiesto=self.req, valore=True)
        self.correction(nc)
        with self.assertRaises(ValidationError):
            self.verify(nc, measurement)

    def test_rework_cannot_reference_original_work(self):
        with self.assertRaises(ValidationError):
            NC.action(actor=self.quality, non_conformita=self.case(), tipo_azione="RILAVORAZIONE", descrizione="Tentativo", lavorazione=self.work)
