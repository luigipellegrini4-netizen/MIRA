from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from decimal import Decimal

from interfaccia.simple_production_forms import CarrelloPhaseForm
from magazzino.services import Position
from produzione.services import ProduzioneSemplificataService as Service
from produzione.services.demo_seed import seed_demo


class CarrelloPhaseTests(TestCase):
    def setUp(self):
        self.demo = seed_demo()
        self.actor = get_user_model().objects.create_superuser(username="carrello-test", password="test")
        roboqbo = Service.apri_roboqbo(actor=self.actor, ricetta=self.demo["recipe"], numero_batch_previsti=1)
        Service.avvia(actor=self.actor, sessione=roboqbo)
        self.filling = Service.apri_invasettamento(
            actor=self.actor, lotto_origine=roboqbo, igienizzazione_confermata=True,
        )
        Service.avvia(actor=self.actor, sessione=self.filling)

    def test_phases_are_recorded_separately_on_one_carrello(self):
        with self.assertRaises(ValidationError):
            Service.registra_fase_carrello(
                actor=self.actor, sessione=self.filling, fase="shock-vuoto", numero=1, esito="C",
            )
        past = Service.registra_fase_carrello(
            actor=self.actor, sessione=self.filling, fase="pastorizzazione", numero=1, esito="C",
        )
        self.assertEqual(past.esito_pastorizzazione, "C")
        self.assertEqual(past.esito_shock_vuoto, "")
        self.assertFalse(past.completo)
        form = CarrelloPhaseForm(session=self.filling, fase="shock-vuoto")
        self.assertIn(("1", "Carrello 1"), form.fields["numero"].choices)
        with self.assertRaises(ValidationError):
            Service.registra_fase_carrello(
                actor=self.actor, sessione=self.filling, fase="pastorizzazione", numero=1, esito="NC",
            )
        shock = Service.registra_fase_carrello(
            actor=self.actor, sessione=self.filling, fase="shock-vuoto", numero=1, esito="NC",
        )
        self.assertEqual(shock.pk, past.pk)
        self.assertTrue(shock.completo)
        self.assertEqual(shock.esito, "NC")

    def test_page_shows_distinct_registration_forms_and_carrello_summary(self):
        self.client.force_login(self.actor)
        response = self.client.get(reverse("ui:simple_session", args=[self.filling.pk]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Registra la 2ª pastorizzazione")
        self.assertContains(response, "Completa shock termico e vuoto")
        self.assertContains(response, "Stato di ogni carrello")
        self.assertEqual(response.context["carrelli"], [])
        self.assertEqual(response.context["control_tables"], [])

    def test_partial_carrello_cannot_be_closed(self):
        Service.registra_fase_carrello(
            actor=self.actor, sessione=self.filling, fase="pastorizzazione", numero=1, esito="C",
        )
        with self.assertRaisesMessage(ValidationError, "Completare 2ª pastorizzazione"):
            Service.chiudi_invasettamento(
                actor=self.actor, sessione=self.filling,
                vasetti_buoni=0, vasetti_scartati=0,
                capsule_difettose=0, peso_netto_g=Decimal("230"),
                vasetti_giacenza=(), capsule_giacenza=(),
                destinazione=Position(self.demo["locations"]["MAG"].pk),
            )

    def test_operator_posts_each_phase_independently(self):
        self.client.force_login(self.actor)
        past_url = reverse("ui:simple_carrello_phase", args=[self.filling.pk, "pastorizzazione"])
        shock_url = reverse("ui:simple_carrello_phase", args=[self.filling.pk, "shock-vuoto"])
        self.assertEqual(self.client.post(past_url, {"numero": "1", "esito": "C"}).status_code, 302)
        self.assertEqual(self.client.post(shock_url, {"numero": "1", "esito": "C"}).status_code, 302)
        controls = list(self.filling.controlli.filter(tipo="CARRELLO"))
        self.assertEqual(len(controls), 1)
        self.assertEqual((controls[0].esito_pastorizzazione, controls[0].esito_shock_vuoto), ("C", "C"))
