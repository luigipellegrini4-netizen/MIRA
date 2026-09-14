from unittest import skip

from django.test import TestCase
from django.urls import reverse
from magazzino.models import Giacenza, Movimento
from magazzino.services import MovementService
from produzione.models import TankAziendale, SessioneInvasettamento, CarrelloSessione
from produzione.services import ShiftService
from produzione.tests.test_azienda_flow import AziendaFixture


@skip("Interfaccia produttiva storica disattivata; servizi conservati per uso futuro")
class FillingViewsTests(AziendaFixture, TestCase):
    def setUp(self):
        super().setUp()
        self.client.force_login(self.op)

    def data(self, response):
        return {f.name: f.value() for f in response.context["form"] if f.value() is not None}

    def material_data(self, response):
        d = self.data(response)
        d["materiali"] = list(response.context["form"].fields["materiali"].queryset.values_list("pk", flat=True))
        return d

    def test_form_tank_then_quality_release_through_ui(self):
        plan, revision = self.plan()
        self.finish_batch(plan.batch.get(), revision)
        path = reverse("ui:azienda_form_tank", args=[self.shift.postazione_id])
        response = self.client.get(path, {"ricetta": self.recipe.pk})
        self.assertEqual(response.status_code, 200)
        d = self.material_data(response)
        d["destinazione"] = self.buffer.ubicazione_id
        self.assertEqual(self.client.post(path, d).status_code, 302)
        tank = TankAziendale.objects.get()
        quality = reverse("ui:azienda_tank", args=[tank.pk])
        self.client.force_login(self.d["users"]["qualita"])
        d = self.data(self.client.get(quality))
        d.update(brix="42,5", ph="4,1")
        self.assertEqual(self.client.post(quality, d).status_code, 302)
        self.assertEqual(self.client.post(quality, d).status_code, 302)
        tank.refresh_from_db()
        self.assertIsNotNone(tank.pronto_il)
        self.assertEqual(tank.lavorazione.controlli_qualita.count(), 2)
        self.assertContains(self.client.get(quality), "Pronto per invasettamento")

    def test_tank_quality_preserves_out_of_range_values(self):
        tank = self.make_tank(False)
        path = reverse("ui:azienda_tank", args=[tank.pk])
        d = self.data(self.client.get(path))
        d.update(brix="45", ph="4,1")
        self.assertEqual(self.client.post(path, d).status_code, 302)
        tank.refresh_from_db()
        self.assertIsNone(tank.pronto_il)
        self.assertContains(self.client.get(path), "NC")

    def test_existing_ph_does_not_prevent_registering_brix_and_release(self):
        tank = self.make_tank(False)
        self.measure(tank, "PH", "4.1")
        path = reverse("ui:azienda_tank", args=[tank.pk])
        d = self.data(self.client.get(path))
        d.update(brix="42", ph="4,1")
        self.assertEqual(self.client.post(path, d).status_code, 302)
        tank.refresh_from_db()
        self.assertIsNotNone(tank.pronto_il)

    def test_tank_stock_change_rejects_stale_selection(self):
        plan, revision = self.plan()
        output = self.finish_batch(plan.batch.get(), revision)
        path = reverse("ui:azienda_form_tank", args=[self.shift.postazione_id])
        d = self.material_data(self.client.get(path, {"ricetta": self.recipe.pk}))
        d["destinazione"] = self.buffer.ubicazione_id
        MovementService.register(actor=self.d["users"]["magazzino"], lotto=output.lotto, tipo="RETTIFICA",
            quantita="1", origine=self.buffer, note="Disponibilità cambiata")
        self.assertContains(self.client.post(path, d), "Le quantità selezionate sono cambiate")
        self.assertFalse(TankAziendale.objects.exists())

    def test_invasettamento_ui_requires_hygiene(self):
        self.make_tank()
        self.client.force_login(self.filler)
        path = reverse("ui:azienda_open_session", args=[self.fill_shift.postazione_id])
        d = self.material_data(self.client.get(path, {"ricetta": self.recipe.pk}))
        self.assertEqual(self.client.post(path, d).status_code, 200)
        self.assertFalse(SessioneInvasettamento.objects.exists())

    def prepare_session_ui(self):
        self.make_tank()
        self.client.force_login(self.filler)
        ShiftService.confirm_hygiene(actor=self.filler, turno=self.fill_shift, confermato=True)
        path = reverse("ui:azienda_open_session", args=[self.fill_shift.postazione_id])
        d = self.material_data(self.client.get(path, {"ricetta": self.recipe.pk}))
        self.assertEqual(self.client.post(path, d).status_code, 302)
        session = SessioneInvasettamento.objects.get()
        cart_url = reverse("ui:azienda_add_cart", args=[session.pk])
        cart_data = self.data(self.client.get(cart_url))
        self.assertEqual(self.client.post(cart_url, cart_data).status_code, 302)
        self.assertEqual(self.client.post(cart_url, cart_data).status_code, 302)
        cart = CarrelloSessione.objects.get()
        for route in ("azienda_pasteurize", "azienda_vacuum"):
            path = reverse("ui:" + route, args=[cart.pk])
            d = self.data(self.client.get(path))
            d["esito"] = "C"
            self.assertEqual(self.client.post(path, d).status_code, 302)
        return session

    def closure_preview(self, session):
        path = reverse("ui:azienda_close_session", args=[session.pk])
        counts = dict(fase="proponi", vasetti_buoni="90", vasetti_scarti="5", capsule_difettose="2",
            peso_netto_g="100", destinazione=self.mag.ubicazione_id)
        response = self.client.post(path, counts)
        self.assertEqual(response.status_code, 200)
        d = self.data(response)
        d.update(fase="conferma", invio=response.context["token"], riepilogo=response.context["preview"])
        fs = response.context["formset"]
        for f in fs.management_form:
            d[f.html_name] = f.value()
        for form in fs:
            for f in form:
                d[f.html_name] = f.value() if f.value() is not None else ""
        return path, d, response

    def test_complete_filling_ui_closes_once_and_shows_final_yield(self):
        session = self.prepare_session_ui()
        before = Movimento.objects.count()
        path, d, response = self.closure_preview(session)
        self.assertEqual(Movimento.objects.count(), before)
        self.assertEqual(response.context["values"]["vasetti"], 95)
        self.assertEqual(response.context["values"]["capsule"], 97)
        self.assertEqual(self.client.post(path, d).status_code, 302)
        count = Movimento.objects.count()
        self.assertEqual(self.client.post(path, d).status_code, 302)
        self.assertEqual(Movimento.objects.count(), count)
        session.refresh_from_db()
        self.assertIsNotNone(session.chiusa_il)
        self.assertContains(self.client.get(reverse("ui:azienda_session", args=[session.pk])), "Riepilogo finale")

    def test_closure_counts_cannot_change_after_signed_preview(self):
        session = self.prepare_session_ui()
        path, d, _ = self.closure_preview(session)
        d["vasetti_buoni"] = "91"
        before = Movimento.objects.count()
        self.assertContains(self.client.post(path, d), "Il piano o i prelievi sono cambiati")
        self.assertEqual(Movimento.objects.count(), before)
        session.refresh_from_db()
        self.assertIsNone(session.chiusa_il)

    def test_another_operator_cannot_close_session(self):
        session = self.prepare_session_ui()
        self.client.force_login(self.op)
        path = reverse("ui:azienda_close_session", args=[session.pk])
        self.assertEqual(self.client.get(path).status_code, 403)
        self.assertEqual(self.client.post(path, {}).status_code, 403)
