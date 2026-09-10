from uuid import uuid4

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import require_permission


class LotGenerationService:
    """Generazione centralizzata di identità tecniche e lotti produttivi."""

    @staticmethod
    def technical_code():
        # Identità nuova quando il fornitore non espone un lotto. Il vincolo
        # univoco DB rimane l'ultima protezione; nessun codice nei model.save().
        return f"TECH-{uuid4().hex.upper()}"

    @staticmethod
    def suffix(number):
        if isinstance(number, bool) or not isinstance(number, int) or number < 1:
            raise ValidationError("Progressivo suffisso non valido.")
        chars = []
        while number:
            number, remainder = divmod(number - 1, 26)
            chars.append(chr(ord("A") + remainder))
        return "".join(reversed(chars))

    @classmethod
    @transaction.atomic
    def create_production(cls, *, actor, lavorazione, requisito_output, articolo=None,
                          data_produzione=None, data_scadenza=None, note=""):
        from anagrafiche.models import Articolo
        from magazzino.models import Lotto
        from produzione.models import RequisitoOutputTipoLavorazione
        from produzione.services.locking import get_record, lock_work, require_running
        require_permission(actor, "can_execute_production")
        work = lock_work(lavorazione)
        require_running(work)
        from produzione.services.azienda_common import managed_guard
        managed_guard(work)
        req = get_record(RequisitoOutputTipoLavorazione, requisito_output, "Requisito output")
        if req.tipo_output == "PRINCIPALE" and work.ricetta_id:
            from magazzino.services.types import persisted_id
            expected = work.ricetta.articolo_id
            if articolo is not None and persisted_id(articolo, "Articolo") != expected:
                raise ValidationError("L'articolo principale deve corrispondere alla ricetta.")
            articolo = expected
        article = get_record(Articolo, articolo, "Articolo", lock=True)
        if not work.tipo_lavorazione.genera_lotto or req.tipo_lavorazione_id != work.tipo_lavorazione_id or not req.accetta_articolo(article):
            raise ValidationError("Articolo o requisito non compatibili con il lotto da generare.")
        if not article.attivo:
            raise ValidationError("L'articolo output è disattivato.")
        production_date = Lotto._meta.get_field("data_produzione").clean(data_produzione or timezone.localdate(), None)
        expiry = Lotto._meta.get_field("data_scadenza").clean(data_scadenza, None)
        prefix = req.prefisso_lotto.strip().upper()
        if req.schema_lotto != "LEGACY":
            from produzione.services.azienda_common import NumberingService
            code = NumberingService.next(articolo=article, famiglia=req.schema_lotto, giorno=production_date)
            return Lotto.objects.create(articolo=article, tipo=Lotto.Tipo.PRODUZIONE,
                codice_lotto=code, lavorazione_origine=work, data_produzione=production_date,
                data_scadenza=expiry, note=note)
        base = f"{prefix}{production_date:%y%m%d}"
        code, index = base, 0
        # Il lock articolo serializza tutte le generazioni dello stesso articolo.
        # L'indice univoco MySQL protegge anche scritture fuori dal servizio.
        while Lotto.objects.filter(articolo=article, tipo=Lotto.Tipo.PRODUZIONE, codice_lotto=code).exists():
            index += 1
            code = f"{base}-{cls.suffix(index)}"
        return Lotto.objects.create(articolo=article, tipo=Lotto.Tipo.PRODUZIONE,
                                    codice_lotto=code, lavorazione_origine=work,
                                    data_produzione=production_date, data_scadenza=expiry, note=note)
