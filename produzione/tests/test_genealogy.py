import json
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import TestCase
from django.urls import reverse
from magazzino.models import Lotto, Movimento, Giacenza
from magazzino.services import Allocation, ReceivingService
from magazzino.tests.service_fixtures import ServiceFixtures
from produzione.models import TipoLavorazione, RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione
from produzione.services import (GenealogyService, ProductionCycleService, WorkExecutionService,
                                 InputService, OutputService)


class GenealogyTests(ServiceFixtures, TestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        received = ReceivingService.receive(actor=cls.warehouse, articolo=cls.article, fornitore=cls.supplier,
            codice_lotto="SOURCE", quantita_ricevuta="10", destinazioni=[Allocation(cls.position, "10")], numero_ddt="DDT-1")
        cls.source = received.lotto
        cls.kind = TipoLavorazione.objects.create(codice="TRACE", nome="Trasformazione")
        cls.req_in = RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, articolo=cls.article, nome="Materia", multiplo=True)
        cls.req_out = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=cls.kind, articolo=cls.article, nome="Prodotto")
        cls.cycle = ProductionCycleService.create(actor=cls.production, articolo=cls.article)
        cls.works, cls.lots = [], []
        for parents in ((cls.source,), (cls.source,), None):
            work = WorkExecutionService.plan(actor=cls.production, ciclo=cls.cycle, tipo_lavorazione=cls.kind)
            WorkExecutionService.start(actor=cls.operator, lavorazione=work)
            for parent in parents or cls.lots:
                amount = "2" if parents else "1"
                position = cls.position if parents else cls.destination
                InputService.register(actor=cls.operator, lavorazione=work, requisito_input=cls.req_in,
                    lotto=parent, quantita=amount, origini=[Allocation(position, amount)])
            result = OutputService.register(actor=cls.operator, lavorazione=work, requisito_output=cls.req_out,
                articolo=cls.article, quantita="2", destinazioni=[Allocation(cls.destination, "2")])
            WorkExecutionService.complete(actor=cls.operator, lavorazione=work)
            cls.works.append(work)
            cls.lots.append(result.lotto)

    def upstream(self, lot=None, **kwargs):
        return GenealogyService.upstream(actor=self.operator, lotto=lot or self.lots[-1], **kwargs)

    def test_upstream_shared_ancestor_appears_once(self):
        graph = self.upstream()
        self.assertCountEqual([l["id"] for l in graph["lotti"]], [self.source.pk, *[l.pk for l in self.lots]])
        self.assertEqual(len(graph["lavorazioni"]), 3)
        self.assertEqual(len(graph["legami_materiali"]), 7)
        self.assertFalse(graph["ciclo_materiale_rilevato"])
        self.assertFalse(graph["troncato"])

    def test_downstream_reaches_both_branches_and_merge(self):
        graph = GenealogyService.downstream(actor=self.warehouse, lotto=self.source)
        self.assertCountEqual([l["id"] for l in graph["lotti"]], [self.source.pk, *[l.pk for l in self.lots]])
        self.assertEqual(len(graph["legami_materiali"]), 7)

    def test_downstream_does_not_expand_to_coingredients(self):
        graph = GenealogyService.downstream(actor=self.operator, lotto=self.lots[0])
        self.assertCountEqual([l["id"] for l in graph["lotti"]], [self.lots[0].pk, self.lots[2].pk])

    def test_purchase_leaf_contains_supplier_and_receipt(self):
        graph = self.upstream(self.source)
        self.assertEqual(len(graph["lotti"]), 1)
        self.assertEqual(graph["lotti"][0]["fornitore_id"], self.supplier.pk)
        self.assertEqual(graph["ricevimenti"][0]["numero_ddt"], "DDT-1")
        self.assertEqual(graph["lavorazioni"], [])

    def test_input_and_output_movements_are_linked(self):
        graph = self.upstream()
        for edge in graph["legami_materiali"]:
            self.assertTrue(edge["movimenti_ids"])
            self.assertEqual(Movimento.objects.filter(pk__in=edge["movimenti_ids"]).count(), 1)

    def test_reading_does_not_change_domain_records(self):
        before = (Lotto.objects.count(), Movimento.objects.count(), list(Giacenza.objects.order_by("pk").values_list("pk", "quantita")))
        json.dumps(self.upstream(), ensure_ascii=False)
        after = (Lotto.objects.count(), Movimento.objects.count(), list(Giacenza.objects.order_by("pk").values_list("pk", "quantita")))
        self.assertEqual(before, after)

    def test_lot_limit_exposes_missing_frontier(self):
        graph = self.upstream(max_lotti=1)
        self.assertTrue(graph["troncato"])
        self.assertEqual(len(graph["lotti"]), 1)
        self.assertCountEqual(graph["frontiera_omessa_ids"], [self.lots[0].pk, self.lots[1].pk])

    def test_prepared_lot_has_identity_but_no_output_quantity(self):
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind)
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        InputService.register(actor=self.operator, lavorazione=work, requisito_input=self.req_in,
            lotto=self.source, quantita="1", origini=[Allocation(self.position, "1")])
        prepared = OutputService.prepare_lot(actor=self.operator, lavorazione=work, requisito_output=self.req_out, articolo=self.article)
        graph = self.upstream(prepared)
        output = next(e for e in graph["legami_materiali"] if e["tipo"] == "PRODUZIONE")
        self.assertIsNone(output["quantita"])
        self.assertIsNone(output["output_id"])
        self.assertFalse(output["output_registrato"])
        downstream = GenealogyService.downstream(actor=self.operator, lotto=self.source)
        self.assertIn(prepared.pk, [l["id"] for l in downstream["lotti"]])

    def test_isolated_legacy_lot_is_readable(self):
        legacy = Lotto.objects.create(articolo=self.article, tipo="PRODUZIONE", codice_lotto="LEGACY")
        graph = self.upstream(legacy)
        self.assertEqual(graph["legami_materiali"], [])
        self.assertIsNone(graph["lotti"][0]["lavorazione_origine_id"])

    def test_all_operational_roles_and_not_pure_admin(self):
        for actor in (self.operator, self.production, self.quality, self.manager, self.warehouse):
            GenealogyService.upstream(actor=actor, lotto=self.source)
        with self.assertRaises(PermissionDenied):
            GenealogyService.upstream(actor=self.administrator, lotto=self.source)

    def test_invalid_direction_or_identifier(self):
        with self.assertRaises(ValidationError):
            GenealogyService.trace(actor=self.operator, lotto=self.source, direzione="LATERALE")
        with self.assertRaises(ValidationError):
            self.upstream(99999999)

    def test_admin_endpoint_returns_json_for_authorized_staff(self):
        self.operator.is_staff = True
        self.operator.save(update_fields=["is_staff"])
        self.client.force_login(self.operator)
        response = self.client.get(reverse("admin:magazzino_lotto_genealogia", args=[self.lots[-1].pk]))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["lotto_radice_id"], self.lots[-1].pk)

    def test_admin_endpoint_denies_pure_administrator(self):
        self.administrator.is_staff = True
        self.administrator.save(update_fields=["is_staff"])
        self.client.force_login(self.administrator)
        response = self.client.get(reverse("admin:magazzino_lotto_genealogia", args=[self.source.pk]))
        self.assertEqual(response.status_code, 403)

    def test_admin_endpoint_requires_login_and_get(self):
        url = reverse("admin:magazzino_lotto_genealogia", args=[self.source.pk])
        self.assertEqual(self.client.get(url).status_code, 302)
        self.operator.is_staff = True
        self.operator.save(update_fields=["is_staff"])
        self.client.force_login(self.operator)
        self.assertEqual(self.client.post(url).status_code, 405)

    def test_admin_endpoint_rejects_invalid_direction(self):
        self.operator.is_staff = True
        self.operator.save(update_fields=["is_staff"])
        self.client.force_login(self.operator)
        url = reverse("admin:magazzino_lotto_genealogia", args=[self.source.pk])
        self.assertEqual(self.client.get(url, {"direzione": "INVALIDA"}).status_code, 400)

    def test_all_receipts_for_same_lot_are_preserved(self):
        ReceivingService.receive(actor=self.warehouse, articolo=self.article, fornitore=self.supplier,
            codice_lotto="SOURCE", quantita_ricevuta="1", destinazioni=[Allocation(self.position, "1")], numero_ddt="DDT-2")
        self.assertCountEqual([r["numero_ddt"] for r in self.upstream()["ricevimenti"]], ["DDT-1", "DDT-2"])

    def test_case_without_lot_is_found_through_physical_action(self):
        from qualita.services import NonConformityService as NC
        nc = NC.open(actor=self.operator, descrizione="Anomalia generale")
        NC.take_charge(actor=self.quality, non_conformita=nc)
        NC.action(actor=self.quality, non_conformita=nc, tipo_azione="SCARTO", descrizione="Campione non idoneo",
            lotto=self.lots[-1], quantita="1", origine=self.destination)
        case = next(n for n in self.upstream()["non_conformita"] if n["id"] == nc.pk)
        self.assertIsNone(case["lotto_id"])
        self.assertEqual(case["collegamento"], "DIRETTO")

    def test_interrupted_work_is_not_presented_as_completed(self):
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind)
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        InputService.register(actor=self.operator, lavorazione=work, requisito_input=self.req_in,
            lotto=self.source, quantita="1", origini=[Allocation(self.position, "1")])
        lot = OutputService.prepare_lot(actor=self.operator, lavorazione=work, requisito_output=self.req_out, articolo=self.article)
        WorkExecutionService.interrupt(actor=self.operator, lavorazione=work, note="Fermo tecnico")
        graph = self.upstream(lot)
        self.assertEqual(graph["lavorazioni"][0]["stato"], "INTERROTTA")
        self.assertFalse(next(e for e in graph["legami_materiali"] if e["tipo"] == "PRODUZIONE")["output_registrato"])

    def test_reused_resource_nc_is_marked_as_context_only(self):
        from produzione.models import RisorsaProduttiva
        from produzione.services import ResourceService
        from qualita.services import NonConformityService as NC
        resource = RisorsaProduttiva.objects.create(codice="SHARED", nome="Condivisa", tipo="MACCHINA")
        nc = NC.open(actor=self.operator, descrizione="Anomalia della risorsa", risorsa_produttiva=resource)
        work = WorkExecutionService.plan(actor=self.production, ciclo=self.cycle, tipo_lavorazione=self.kind)
        WorkExecutionService.start(actor=self.operator, lavorazione=work)
        ResourceService.assign(actor=self.operator, lavorazione=work, risorsa_produttiva=resource)
        lot = OutputService.prepare_lot(actor=self.operator, lavorazione=work, requisito_output=self.req_out, articolo=self.article)
        case = next(n for n in self.upstream(lot)["non_conformita"] if n["id"] == nc.pk)
        self.assertEqual(case["collegamento"], "RISORSA_CONDIVISA")
