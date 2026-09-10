from django.core.exceptions import PermissionDenied, ValidationError
from django.test import SimpleTestCase
from django.contrib.auth.models import AnonymousUser
from produzione.models import UnitaLavorazione, PartecipazioneUnitaLavorazione, RisorsaLavorazione
from produzione.selectors import UnitSelector


class UnitContractsTests(SimpleTestCase):
    def test_anonymous_cannot_consult_units(self):
        with self.assertRaises(PermissionDenied):
            UnitSelector.detail(actor=AnonymousUser(), unita_lavorazione=1)

    def test_direct_writes_blocked_before_database(self):
        for model in (UnitaLavorazione, PartecipazioneUnitaLavorazione, RisorsaLavorazione):
            with self.assertRaises(ValidationError):
                model().save()

    def test_direct_bulk_writes_blocked(self):
        for model in (UnitaLavorazione, PartecipazioneUnitaLavorazione, RisorsaLavorazione):
            for operation in (lambda: model.objects.all().update(note="x"), lambda: model.objects.all().delete(), lambda: model.objects.bulk_create([model()])):
                with self.assertRaises(ValidationError):
                    operation()

    def test_fields_do_not_reference_stock_or_locations(self):
        for model in (UnitaLavorazione, PartecipazioneUnitaLavorazione, RisorsaLavorazione):
            self.assertFalse({"ubicazione", "giacenza", "movimento"} & {f.name for f in model._meta.fields})
