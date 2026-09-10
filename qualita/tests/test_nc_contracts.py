from decimal import Decimal
from django.contrib import admin
from django.contrib.auth.models import AnonymousUser
from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from qualita.models import NonConformita, AzioneNonConformita, VerificaNonConformita
from qualita.nc_selectors import blocked_quantity, NonConformitySelector
from qualita.nc_services import required_text


class NCContractTests(SimpleTestCase):
    def test_direct_writes_blocked(self):
        for model in (NonConformita, AzioneNonConformita, VerificaNonConformita):
            for operation in (model().save, model().delete, lambda: model.objects.all().update(note="x"), lambda: model.objects.bulk_create([model()])):
                with self.assertRaises(ValidationError):
                    operation()

    def test_blocked_amount_is_scoped_to_position_and_nc(self):
        balances = {(1, 10, 5, "A", "1"): Decimal("2"), (2, 10, 5, "A", "1"): Decimal("3"), (1, 10, 5, "B", "1"): Decimal("7")}
        position = dict(lotto_id=10, ubicazione_id=5, scaffale="A", piano="1")
        self.assertEqual(blocked_quantity(balances, **position), 5)
        self.assertEqual(blocked_quantity(balances, **position, nc_id=1), 2)
        self.assertEqual(blocked_quantity(balances, **position, nc_id=3), 0)

    def test_required_text_rejects_missing_or_nontext(self):
        for value in (None, 1, "", " "):
            with self.assertRaises(ValidationError):
                required_text(value, "Descrizione")

    def test_nc_has_no_stock_state_fields(self):
        names = {f.name for f in NonConformita._meta.fields}
        self.assertFalse(names & {"quantita_quarantena", "stato_quarantena", "decisione_finale"})

    def test_admin_is_consultative(self):
        for model in (NonConformita, AzioneNonConformita, VerificaNonConformita):
            model_admin = admin.site._registry[model]
            self.assertFalse(model_admin.has_add_permission(None))
            self.assertFalse(model_admin.has_change_permission(None))
            self.assertFalse(model_admin.has_delete_permission(None))

    def test_selector_rejects_anonymous_before_database(self):
        with self.assertRaises(PermissionDenied):
            NonConformitySelector.detail(actor=AnonymousUser(), non_conformita=1)
