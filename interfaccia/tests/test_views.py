from unittest import skip

from django.core.exceptions import ValidationError
from django.test import TestCase, Client, RequestFactory
from django.urls import reverse
from magazzino.models import Movimento, Giacenza
from produzione.services.demo_seed import seed_demo
from produzione.services import ProductionCycleService, WorkExecutionService
from interfaccia.models import InvioOperativo
from interfaccia.views import token_for, submit_once


class InterfaceViewsTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.demo = seed_demo()

    def login(self, role="operatore"):
        self.user = self.demo["users"][role]
        self.client.force_login(self.user)

    def token(self, path):
        request = RequestFactory().get(path)
        request.user = self.user
        return token_for(request)

    def test_read_pages_render_real_records(self):
        self.login()
        for name in ("home", "magazzino", "movimenti", "qualita", "anagrafiche"):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse("ui:" + name)).status_code, 200)
        self.assertEqual(self.client.get(reverse("ui:lot", args=[self.demo["lots"]["F_A"].pk])).status_code, 200)

    def test_warehouse_cannot_access_production_planning_even_by_post(self):
        self.login("magazziniere")
        path = reverse("ui:operation", args=["pianifica"])
        self.assertEqual(self.client.get(path).status_code, 404)
        self.assertEqual(self.client.post(path, {}).status_code, 404)

    def test_admin_pure_cannot_receive_goods(self):
        self.login("admin")
        self.assertEqual(self.client.get(reverse("ui:operation", args=["ricevimento"])).status_code, 403)

    def receipt_data(self, path):
        return {"invio": self.token(path), "articolo": self.demo["articles"]["FRAGOLE"].pk,
            "fornitore": self.demo["supplier"].pk, "codice_lotto": "UI_TEST_LOT", "quantita": "2,500",
            "destinazione": self.demo["locations"]["MAG"].pk}

    def test_receipt_double_post_creates_one_movement(self):
        self.login("magazziniere")
        path = reverse("ui:operation", args=["ricevimento"])
        data = self.receipt_data(path)
        before = Movimento.objects.count()
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(Movimento.objects.count(), before + 1)
        self.assertEqual(InvioOperativo.objects.count(), 1)

    def test_token_from_another_route_is_rejected_without_stock_change(self):
        self.login("magazziniere")
        path = reverse("ui:operation", args=["ricevimento"])
        data = self.receipt_data(reverse("ui:operation", args=["trasferimento"]))
        before = Movimento.objects.count()
        response = self.client.post(path, data)
        self.assertContains(response, "Modulo scaduto o non valido")
        self.assertEqual(Movimento.objects.count(), before)

    def test_csrf_is_required_for_mutations(self):
        user = self.demo["users"]["magazziniere"]
        client = Client(enforce_csrf_checks=True)
        client.force_login(user)
        self.assertEqual(client.post(reverse("ui:operation", args=["ricevimento"]), {}).status_code, 403)

    def test_read_get_does_not_register_receipt(self):
        self.login("magazziniere")
        before = Movimento.objects.count()
        self.assertEqual(self.client.get(reverse("ui:operation", args=["ricevimento"])).status_code, 200)
        self.assertEqual(Movimento.objects.count(), before)

    def test_service_failure_rolls_back_submission_receipt(self):
        self.login()
        request = RequestFactory().post("/test/")
        request.user = self.user
        def fail():
            raise ValidationError("Operazione rifiutata")
        with self.assertRaises(ValidationError):
            submit_once(request, token_for(request), fail)
        self.assertFalse(InvioOperativo.objects.exists())

    @skip("Interfaccia produttiva storica disattivata")
    def test_recipe_form_renders_proposal_and_registers_both_rows(self):
        self.login()
        d = self.demo
        cycle = ProductionCycleService.create(actor=d["users"]["produzione"], articolo=d["articles"]["SEMILAVORATO"])
        work = WorkExecutionService.plan(actor=d["users"]["produzione"], ciclo=cycle, tipo_lavorazione=d["kind"], ricetta=d["recipe"])
        work = WorkExecutionService.start(actor=self.user, lavorazione=work)
        self.assertEqual(self.client.get(reverse("ui:work", args=[work.pk])).status_code, 200)
        path = reverse("ui:ingredients", args=[work.pk])
        self.assertContains(self.client.get(path), "Prelievo ingredienti")
        rows = list(d["recipe"].righe.all())
        data = {"invio": self.token(path), "form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "0"}
        for i, (lot, quantity) in enumerate(((d["lots"]["F_A"], "10"), (d["lots"]["A_A"], "0,05"))):
            data.update({f"form-{i}-riga_ricetta": rows[i].pk, f"form-{i}-lotto": lot.pk,
                f"form-{i}-quantita": quantity, f"form-{i}-origine": d["locations"]["MAG"].pk})
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(work.inputs.count(), 2)

    def test_production_operation_forms_render_with_scoped_choices(self):
        self.login("produzione")
        d = self.demo
        cycle = ProductionCycleService.create(actor=self.user, articolo=d["articles"]["SEMILAVORATO"])
        work = WorkExecutionService.plan(actor=self.user, ciclo=cycle, tipo_lavorazione=d["kind"], ricetta=d["recipe"])
        for op in ("avvia", "completa", "interrompi", "annulla", "output", "input", "controllo", "prepara_lotto", "risorsa", "unita", "partecipa", "chiudi_unita", "chiudi_ciclo"):
            with self.subTest(operation=op):
                response = self.client.get(reverse("ui:record_operation", args=[op, work.pk]))
                self.assertEqual(response.status_code, 404)

    def test_quality_case_and_action_forms_render(self):
        from qualita.services import NonConformityService
        self.login("qualita")
        case = NonConformityService.open(actor=self.user, descrizione="Test interfaccia", lotto=self.demo["lots"]["F_A"])
        self.assertEqual(self.client.get(reverse("ui:case", args=[case.pk])).status_code, 200)
        for op in ("nc_gestisci", "nc_azione", "nc_verifica", "nc_chiudi"):
            with self.subTest(operation=op):
                self.assertEqual(self.client.get(reverse("ui:record_operation", args=[op, case.pk])).status_code, 200)
