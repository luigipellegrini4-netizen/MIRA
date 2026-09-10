from types import SimpleNamespace as NS
from django.core.exceptions import ValidationError
from django.template.loader import get_template, render_to_string
from django.contrib.auth.models import AnonymousUser
from django.test import SimpleTestCase
from interfaccia.azienda_views import signed_state, verify_state
from interfaccia.azienda_forms import AziendaActionForm
from interfaccia.filling_views import stock_signature, verify_stocks
from interfaccia.filling_forms import ClosureForm
from decimal import Decimal


class AziendaUIRulesTests(SimpleTestCase):
    def test_preview_is_bound_to_user_route_and_content(self):
        request = NS(user=NS(pk=1), path="/linee/batch/1/prelievo/")
        state = {"revision": 1, "rows": [[3, "10"]]}
        token = signed_state(request, state)
        verify_state(request, token, state)
        for changed_request, changed_state in ((NS(user=NS(pk=2), path=request.path), state),
            (NS(user=request.user, path="/linee/batch/2/prelievo/"), state),
            (request, {"revision": 1, "rows": [[4, "10"]]})):
            with self.assertRaises(ValidationError):
                verify_state(changed_request, token, changed_state)

    def test_hygiene_has_no_preselected_confirmation(self):
        form = AziendaActionForm(operation="igienizzazione")
        self.assertFalse(form.fields["confermato"].initial)
        self.assertFalse(AziendaActionForm(data={"invio": "x"}, operation="igienizzazione").is_valid())

    def test_control_requires_explicit_c_nc_or_na(self):
        for value in ("", "si", "c"):
            self.assertFalse(AziendaActionForm(data={"invio": "x", "esito": value}, operation="controllo_batch").is_valid())
        for value in ("C", "NC", "NA"):
            self.assertTrue(AziendaActionForm(data={"invio": "x", "esito": value}, operation="controllo_batch").is_valid())

    def test_all_new_templates_compile(self):
        for name in ("stations", "station", "setup", "action", "plan", "picking_plan", "batch", "batch_picking", "fields", "select_materials", "tank", "session", "closure"):
            with self.subTest(name=name):
                get_template("interfaccia/azienda/" + name + ".html")

    def test_empty_stations_explains_configuration(self):
        html = render_to_string("interfaccia/azienda/stations.html", {"stations": [], "user": AnonymousUser()})
        self.assertIn("Linee da configurare", html)

    def test_stock_signature_allows_subset_but_rejects_changed_quantity(self):
        request = NS(user=NS(pk=1), path="/linee/postazioni/1/forma-tank/")
        stocks = [NS(pk=1, quantita=Decimal("10.000000")), NS(pk=2, quantita=Decimal("20.000000"))]
        token = stock_signature(request, stocks)
        verify_stocks(request, token, stocks[:1])
        with self.assertRaises(ValidationError):
            verify_stocks(request, token, [NS(pk=1, quantita=Decimal("9.000000"))])
        with self.assertRaises(ValidationError):
            verify_stocks(request, token, [NS(pk=3, quantita=Decimal("10.000000"))])

    def test_all_rejected_closure_needs_no_good_stock_destination(self):
        data = dict(vasetti_buoni=0, vasetti_scarti=100, capsule_difettose=2, peso_netto_g="350,123456")
        self.assertTrue(ClosureForm(data=data).is_valid())
        self.assertFalse(ClosureForm(data=dict(data, vasetti_buoni=1)).is_valid())
