from django.test import TestCase, Client
from django.urls import reverse
from magazzino.models import Movimento
from produzione.models import PianoProduzione, TurnoOperativo
from produzione.services import BatchService, PickingPlanService, ShiftService
from produzione.tests.test_azienda_flow import AziendaFixture


class AziendaViewsTests(AziendaFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.op)

    def action_url(self, op, pk):
        return reverse("ui:azienda_action", args=[op, pk])

    def form_data(self, response):
        form = response.context["form"]
        return {name: field.value() for name, field in ((f.name, f) for f in form) if field.value() is not None}

    def test_station_pages_and_batch_page_render(self):
        plan, _ = self.plan()
        batch = plan.batch.get()
        for name, args in (("azienda_stations", []), ("azienda_station", [self.shift.postazione_id]),
            ("azienda_plan", [plan.pk]), ("azienda_batch", [batch.pk]), ("azienda_picking_plan", [plan.pk])):
            with self.subTest(name=name):
                self.assertEqual(self.client.get(reverse("ui:" + name, args=args)).status_code, 200)
        self.assertRedirects(self.client.get(reverse("ui:work", args=[batch.lavorazione_id])), reverse("ui:azienda_batch", args=[batch.pk]))

    def test_get_does_not_start_shift(self):
        ShiftService.end(actor=self.op, turno=self.shift)
        path = self.action_url("inizio_turno", self.shift.postazione_id)
        before = TurnoOperativo.objects.count()
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(TurnoOperativo.objects.count(), before)

    def test_shift_double_post_is_idempotent(self):
        ShiftService.end(actor=self.op, turno=self.shift)
        path = self.action_url("inizio_turno", self.shift.postazione_id)
        data = self.form_data(self.client.get(path))
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(TurnoOperativo.objects.filter(operatore=self.op, fine__isnull=True).count(), 1)

    def test_hygiene_requires_explicit_checkbox(self):
        self.client.force_login(self.filler)
        path = self.action_url("igienizzazione", self.fill_shift.pk)
        data = self.form_data(self.client.get(path))
        data.pop("confermato", None)
        self.assertEqual(self.client.post(path, data).status_code, 200)
        self.fill_shift.refresh_from_db()
        self.assertIsNone(self.fill_shift.igienizzazione_confermata_il)
        data["confermato"] = "on"
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.fill_shift.refresh_from_db()
        self.assertIsNotNone(self.fill_shift.igienizzazione_confermata_il)

    def test_other_operator_cannot_confirm_hygiene(self):
        path = self.action_url("igienizzazione", self.fill_shift.pk)
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post(path, {"confermato": "on"}).status_code, 403)

    def test_admin_cannot_operate_even_with_direct_post(self):
        self.client.force_login(self.d["users"]["admin"])
        path = self.action_url("piano", self.shift.postazione_id)
        self.assertEqual(self.client.post(path, {}).status_code, 403)

    def test_setup_requires_both_process_and_quality_configuration_permissions(self):
        path = reverse("ui:azienda_setup")
        for role in ("operatore", "produzione", "qualita"):
            self.client.force_login(self.d["users"][role])
            self.assertEqual(self.client.get(path).status_code, 403)
        self.client.force_login(self.d["users"]["admin"])
        data = self.form_data(self.client.get(path))
        data.update(categoria_semilavorati=self.d["categories"]["SL"].pk, categoria_output=self.d["categories"]["SL"].pk,
            articolo_vasetti=self.jars.pk, articolo_capsule=self.caps.pk)
        before = Movimento.objects.count()
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(Movimento.objects.count(), before)

    def test_csrf_protects_shift_operations(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.op)
        self.assertEqual(client.post(self.action_url("fine_turno", self.shift.pk), {}).status_code, 403)

    def test_operator_creates_plan_once(self):
        path = self.action_url("piano", self.shift.postazione_id)
        data = self.form_data(self.client.get(path))
        data.update(ricetta=self.recipe.pk, numero_batch=2)
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(PianoProduzione.objects.count(), 1)
        self.assertEqual(PianoProduzione.objects.get().batch.count(), 2)

    def plan_form_data(self, response):
        data = self.form_data(response)
        fs = response.context["formset"]
        for field in fs.management_form:
            data[field.html_name] = field.value()
        for form in fs:
            for field in form:
                data[field.html_name] = field.value() if field.value() is not None else ""
        return data

    def test_ui_plan_confirmation_makes_no_movements(self):
        plan, revision = self.plan()
        path = reverse("ui:azienda_picking_plan", args=[plan.pk])
        data = self.plan_form_data(self.client.get(path))
        before = Movimento.objects.count()
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(Movimento.objects.count(), before)
        self.assertEqual(plan.revisioni.count(), 2)

    def test_changed_plan_requires_new_preview(self):
        plan, revision = self.plan()
        path = reverse("ui:azienda_picking_plan", args=[plan.pk])
        data = self.plan_form_data(self.client.get(path))
        proposal = PickingPlanService.forecast(actor=self.op, piano=plan)
        PickingPlanService.confirm(actor=self.op, piano=plan, selections=proposal.selections, motivo="Revisione da un'altra pagina")
        self.assertContains(self.client.post(path, data), "Il piano o i prelievi sono cambiati")
        self.assertEqual(plan.revisioni.count(), 2)

    def test_batch_previews_cannot_be_reused_on_another_batch(self):
        plan, revision = self.plan(2)
        first, second = plan.batch.order_by("numero")
        BatchService.start(actor=self.op, batch=first)
        path = reverse("ui:azienda_batch_picking", args=[first.pk])
        data = self.form_data(self.client.get(path))
        data["confermato"] = "on"
        other = reverse("ui:azienda_batch_picking", args=[second.pk])
        self.assertContains(self.client.post(other, data), "Modulo scaduto o non valido")
        self.assertFalse(first.lavorazione.inputs.exists())
        self.assertFalse(second.lavorazione.inputs.exists())

    def test_batch_previews_detect_revision_changes_and_tampering(self):
        plan, revision = self.plan()
        batch = plan.batch.get()
        BatchService.start(actor=self.op, batch=batch)
        path = reverse("ui:azienda_batch_picking", args=[batch.pk])
        data = self.form_data(self.client.get(path))
        data["confermato"] = "on"
        modified = dict(data, proposta=data["proposta"] + "x")
        self.assertContains(self.client.post(path, modified), "Proposta scaduta o non valida")
        proposal = PickingPlanService.forecast(actor=self.op, piano=plan)
        PickingPlanService.confirm(actor=self.op, piano=plan, selections=proposal.selections, motivo="Cambio piano")
        self.assertContains(self.client.post(path, data), "Il piano o i prelievi sono cambiati")
        self.assertFalse(batch.lavorazione.inputs.exists())

    def test_ui_batch_workflow_and_double_consumption(self):
        plan, revision = self.plan()
        batch = plan.batch.get()
        start = self.action_url("inizio_batch", batch.pk)
        self.assertEqual(self.client.post(start, self.form_data(self.client.get(start))).status_code, 302)
        path = reverse("ui:azienda_batch_picking", args=[batch.pk])
        data = self.form_data(self.client.get(path))
        data["confermato"] = "on"
        self.assertEqual(self.client.post(path, data).status_code, 302)
        before = Movimento.objects.count()
        self.assertEqual(self.client.post(path, data).status_code, 302)
        self.assertEqual(Movimento.objects.count(), before)
        control = self.action_url("controllo_batch", batch.pk)
        data = self.form_data(self.client.get(control))
        data["esito"] = "C"
        self.assertEqual(self.client.post(control, data).status_code, 302)
        finish = self.action_url("fine_batch", batch.pk)
        data = self.form_data(self.client.get(finish))
        self.assertNotIn("quantita", data)
        data["destinazione"] = self.buffer.ubicazione_id
        self.assertEqual(self.client.post(finish, data).status_code, 302)
        batch.lavorazione.refresh_from_db()
        self.assertEqual(batch.lavorazione.stato, "COMPLETATA")
        self.assertEqual(batch.lavorazione.outputs.get().quantita, self.recipe.righe.get(articolo=self.d["articles"]["FRAGOLE"]).quantita + self.recipe.righe.get(articolo=self.d["articles"]["ACIDO"]).quantita)
