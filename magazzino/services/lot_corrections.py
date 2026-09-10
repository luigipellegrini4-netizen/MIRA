from django.core.exceptions import ValidationError
from django.db import models, transaction

from accounts.permissions import require_permission
from magazzino.models import CorrezioneLotto, Lotto


FIELDS = ("codice_lotto", "data_produzione", "data_scadenza", "note")


class LotCorrectionService:
    @staticmethod
    @transaction.atomic
    def correct(*, actor, lotto, motivazione, **values):
        require_permission(actor, "can_adjust_inventory")
        reason = (motivazione or "").strip()
        if not reason:
            raise ValidationError("La motivazione è obbligatoria.")
        current = Lotto.objects.select_for_update().get(pk=lotto.pk)
        before = {name: str(getattr(current, name) or "") for name in FIELDS}
        for name in FIELDS:
            if name in values:
                setattr(current, name, values[name])
        current.full_clean()
        after = {name: str(getattr(current, name) or "") for name in FIELDS}
        if before == after:
            raise ValidationError("Non è stata indicata alcuna modifica.")
        audit = CorrezioneLotto(lotto=current, valori_precedenti=before, valori_nuovi=after,
                                motivazione=reason, eseguita_da=actor)
        audit.full_clean(); audit.save()
        models.Model.save(current, force_update=True, update_fields=FIELDS)
        return current
