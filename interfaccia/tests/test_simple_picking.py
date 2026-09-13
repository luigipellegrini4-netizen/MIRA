from decimal import Decimal

from django.test import TestCase
from django.urls import reverse

from magazzino.models import Giacenza, Movimento
from produzione.services.demo_seed import seed_demo
from produzione.services import ProduzioneSemplificataService


class SimplePickingTests(TestCase):
    def setUp(self):
        self.demo = seed_demo()
        self.actor = self.demo["users"]["operatore"]
        self.client.force_login(self.actor)
        self.session = ProduzioneSemplificataService.apri_semilavorato(
            actor=self.actor, ricetta=self.demo["recipe"], numero_batch_previsti=1)
        ProduzioneSemplificataService.avvia(actor=self.actor, sessione=self.session)
        self.url = reverse("ui:simple_picking", args=[self.session.pk])
        self.acid_old = Giacenza.objects.get(lotto=self.demo["lots"]["A_A"])
        self.acid_new = Giacenza.objects.get(lotto=self.demo["lots"]["A_B"])
        self.fruit = Giacenza.objects.get(lotto=self.demo["lots"]["F_A"])
        self.data = {"form-TOTAL_FORMS": "2", "form-INITIAL_FORMS": "2",
            "form-0-articolo": self.demo["articles"]["FRAGOLE"].pk,
            "form-0-giacenza": [self.fruit.pk], "form-0-quantita_kg": "12",
            "form-1-articolo": self.demo["articles"]["ACIDO"].pk,
            "form-1-giacenza": [self.acid_new.pk, self.acid_old.pk], "form-1-quantita_kg": "0.1"}

    def test_fifo_consumption_and_custom_quantity(self):
        self.assertEqual(self.client.post(self.url, self.data).status_code, 302)
        self.acid_old.refresh_from_db()
        self.acid_new.refresh_from_db()
        self.fruit.refresh_from_db()
        self.assertEqual(self.acid_old.quantita, Decimal("0.9"))
        self.assertEqual(self.acid_new.quantita, Decimal("1"))
        self.assertEqual(self.fruit.quantita, Decimal("28"))

    def test_second_confirmation_does_not_duplicate_consumption(self):
        self.client.post(self.url, self.data)
        count = Movimento.objects.count()
        self.client.post(self.url, self.data)
        self.assertEqual(Movimento.objects.count(), count)
        self.assertEqual(self.session.prelievi.count(), 2)

    def test_closed_session_rejects_additional_pick(self):
        from django.utils import timezone
        type(self.session).objects.filter(pk=self.session.pk).update(
            stato="CHIUSA", chiusa_da=self.actor, chiusa_il=timezone.now())
        count = Movimento.objects.count()
        response = self.client.post(reverse("ui:simple_additional_picking", args=[self.session.pk]),
            {"giacenza": self.fruit.pk, "quantita": "1"})
        self.assertEqual(response.status_code, 404)
        self.assertEqual(Movimento.objects.count(), count)
