from pathlib import Path
from django.conf import settings
from django.contrib.auth.models import AnonymousUser
from django.template.loader import get_template, render_to_string
from django.test import SimpleTestCase, RequestFactory
from django.urls import reverse
from interfaccia.forms import OperationForm, amount
from interfaccia.views import token_for, submit_once
from django.core import signing


class InterfaceRulesTests(SimpleTestCase):
    def test_all_templates_compile(self):
        for path in (settings.BASE_DIR / "interfaccia/templates/interfaccia").glob("*.html"):
            with self.subTest(template=path.name):
                get_template("interfaccia/" + path.name)

    def test_login_is_available_without_database_or_authentication(self):
        response = self.client.get(reverse("login"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Accedi al gestionale")

    def test_anonymous_dashboard_redirects_to_login(self):
        response = self.client.get(reverse("ui:home"))
        self.assertEqual(response.status_code, 302)
        self.assertIn("/accesso/", response.url)

    def test_italian_decimal_keeps_six_places(self):
        self.assertEqual(str(amount().clean("0,000001")), "0.000001")

    def test_negative_quantities_rejected(self):
        from django.core.exceptions import ValidationError
        with self.assertRaises(ValidationError):
            amount().clean("-1")

    def test_signature_is_bound_to_user_and_route(self):
        from types import SimpleNamespace
        request = SimpleNamespace(user=SimpleNamespace(pk=7), path="/operazioni/ricevimento/")
        data = signing.loads(token_for(request), salt="mira-ui")
        self.assertEqual((data["user"], data["path"]), (7, request.path))
        self.assertNotEqual(token_for(request), token_for(request))

    def test_empty_adjustment_requires_reason(self):
        form = OperationForm(data={}, operation="rettifica")
        self.assertFalse(form.is_valid())
        self.assertIn("note", form.errors)

    def test_ingredient_page_renders_article_without_category(self):
        from types import SimpleNamespace as NS
        row = NS(articolo=NS(descrizione="Fragole gelo", unita_misura="KG"),
            categoria_articolo=None, quantita="10")
        html = render_to_string("interfaccia/ingredients.html", {
            "user": AnonymousUser(), "work": NS(pk=1, ricetta=NS(nome="Fragola", versione="1")),
            "recipe_rows": [row],
        })
        self.assertIn("Fragole gelo", html)
        self.assertIn("KG", html)

    def test_ingredient_page_renders_category_without_article(self):
        from types import SimpleNamespace as NS
        row = NS(articolo=None, categoria_articolo=NS(nome="Frutta surgelata"), quantita="10")
        html = render_to_string("interfaccia/ingredients.html", {
            "user": AnonymousUser(), "work": NS(pk=1, ricetta=NS(nome="Fragola", versione="1")),
            "recipe_rows": [row],
        })
        self.assertIn("Frutta surgelata", html)
