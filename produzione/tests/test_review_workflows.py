from datetime import date, time
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from interfaccia.simple_production_forms import OpenFillingForm
from magazzino.models import Giacenza, Movimento
from produzione.services import ProduzioneSemplificataService as Service
from produzione.services.demo_seed import seed_demo
from vendite.forms import VenditaForm
from vendite.models import Cliente, Vendita


class ReviewWorkflowTests(TestCase):
    def setUp(self):
        self.demo = seed_demo()
        self.actor = get_user_model().objects.create_superuser(username="review", password="test")
        self.session = Service.apri_roboqbo(actor=self.actor, ricetta=self.demo["recipe"], numero_batch_previsti=1)
        Service.avvia(actor=self.actor, sessione=self.session)

    def test_cancelled_filling_frees_source_but_active_filling_does_not(self):
        filling = Service.apri_invasettamento(actor=self.actor, lotto_origine=self.session, igienizzazione_confermata=True)
        self.assertFalse(OpenFillingForm().fields["lotto_origine"].queryset.filter(pk=self.session.pk).exists())
        with self.assertRaises(ValidationError):
            Service.apri_invasettamento(actor=self.actor, lotto_origine=self.session, igienizzazione_confermata=True)
        Service.annulla(actor=self.actor, sessione=filling)
        self.assertTrue(OpenFillingForm().fields["lotto_origine"].queryset.filter(pk=self.session.pk).exists())
        replacement = Service.apri_invasettamento(actor=self.actor, lotto_origine=self.session, igienizzazione_confermata=True)
        self.assertNotEqual(filling.pk, replacement.pk)
        self.assertFalse(OpenFillingForm().fields["lotto_origine"].queryset.filter(pk=self.session.pk).exists())
        filling.refresh_from_db()
        self.assertEqual(filling.stato, "ANNULLATA")

    def test_batch_dates_survive_next_day_save_and_correction(self):
        rows = [{"numero": 1, "inizio": time(8), "fine": time(9), "esito_tracciato_termico": "C"}]
        with patch("produzione.services.semplificata.timezone.localdate", return_value=date(2026, 9, 10)):
            original = Service.registra_tabella_batch(actor=self.actor, sessione=self.session, righe=rows)[0]
        with patch("produzione.services.semplificata.timezone.localdate", return_value=date(2026, 9, 11)):
            unchanged = Service.registra_tabella_batch(actor=self.actor, sessione=self.session, righe=rows)[0]
            self.assertEqual(unchanged.inizio, original.inizio)
            self.assertEqual(unchanged.fine, original.fine)
            rows[0]["fine"] = time(9, 15)
            corrected = Service.registra_tabella_batch(actor=self.actor, sessione=self.session, righe=rows)[0]
        self.assertEqual(timezone.localtime(corrected.fine).date(), date(2026, 9, 10))
        self.assertEqual(timezone.localtime(corrected.fine).time(), time(9, 15))

    def test_duplicate_sale_is_field_error_including_race(self):
        customer = Cliente.objects.create(codice="TEST", ragione_sociale="Cliente")
        Vendita.objects.create(numero_documento="D1", cliente=customer, registrata_da=self.actor)
        data = {"numero_documento": "D1", "data_documento": "2026-09-13", "cliente": customer.pk}
        form = VenditaForm(data)
        self.assertFalse(form.is_valid())
        self.assertIn("numero_documento", form.errors)
        self.client.force_login(self.actor)
        stock = Giacenza.objects.first()
        # Bypass only the preliminary checks to reproduce a concurrent duplicate
        # rejected by the database inside the real transaction.
        count = Movimento.objects.count()
        with patch.object(VenditaForm, "clean_numero_documento", return_value="D1"), patch("vendite.views.RigheVenditaFormSet") as factory:
            factory.return_value.is_valid.return_value = True
            factory.return_value.cleaned_data = [{"giacenza": stock, "quantita": 1}]
            response = self.client.post(reverse("ui:sale_new"), data)
        self.assertEqual(response.status_code, 200)
        self.assertIn("numero_documento", response.context["form"].errors)
        self.assertEqual(Vendita.objects.count(), 1)
        self.assertEqual(Movimento.objects.count(), count)
