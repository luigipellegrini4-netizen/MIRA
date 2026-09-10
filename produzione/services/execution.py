from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import require_permission
from produzione.models import CicloProduzione, Lavorazione, Ricetta, TipoLavorazione
from produzione.models.protections import _execution_write
from .completion import CompletionValidator
from .locking import get_record, lock_work, require_running


class WorkExecutionService:
    @staticmethod
    @transaction.atomic
    def plan(*, actor, ciclo, tipo_lavorazione, ricetta=None, note=""):
        require_permission(actor, "can_plan_production")
        kind = get_record(TipoLavorazione, tipo_lavorazione, "Tipo", lock=True)
        recipe = get_record(Ricetta, ricetta, "Ricetta", lock=True) if ricetta is not None else None
        cycle = get_record(CicloProduzione, ciclo, "Ciclo", lock=True)
        if not kind.attivo or (recipe and not recipe.attiva):
            raise ValidationError("Tipo e ricetta devono essere attivi.")
        if cycle.stato not in {CicloProduzione.Stato.PIANIFICATO, CicloProduzione.Stato.IN_CORSO}:
            raise ValidationError("Non si possono aggiungere lavorazioni a un ciclo chiuso.")
        return Lavorazione.objects.create(ciclo_produzione=cycle, tipo_lavorazione=kind, ricetta=recipe, note=note)

    @classmethod
    @transaction.atomic
    def plan_batches(cls, *, actor, ciclo, tipo_lavorazione, ricetta, numero_batch, note=""):
        require_permission(actor, "can_plan_production")
        if isinstance(numero_batch, bool) or not isinstance(numero_batch, int) or numero_batch < 1:
            raise ValidationError("Il numero batch deve essere un intero positivo.")
        return tuple(cls.plan(actor=actor, ciclo=ciclo, tipo_lavorazione=tipo_lavorazione, ricetta=ricetta, note=note)
                     for _ in range(numero_batch))

    @staticmethod
    @transaction.atomic
    def reschedule(*, actor, lavorazione, **changes):
        require_permission(actor, "can_plan_production")
        if set(changes) - {"tipo_lavorazione", "ricetta", "note"}:
            raise ValidationError("Campi di pianificazione non riconosciuti.")
        kind = get_record(TipoLavorazione, changes["tipo_lavorazione"], "Tipo") if "tipo_lavorazione" in changes else None
        recipe = get_record(Ricetta, changes["ricetta"], "Ricetta") if changes.get("ricetta") is not None else None
        work = lock_work(lavorazione, extra_types=[kind.pk] if kind else (), extra_recipes=[recipe.pk] if recipe else ())
        if work.tipo_lavorazione.fase_operativa or (kind and kind.fase_operativa):
            raise ValidationError("Il piano aziendale conserva processo e ricetta: creare un nuovo piano.")
        if work.stato != Lavorazione.Stato.PIANIFICATA:
            raise ValidationError("Solo una lavorazione mai iniziata può essere ripianificata.")
        if work.ciclo_produzione.stato in {CicloProduzione.Stato.COMPLETATO, CicloProduzione.Stato.ANNULLATO}:
            raise ValidationError("Il ciclo è chiuso.")
        if kind is not None:
            work.tipo_lavorazione = get_record(TipoLavorazione, kind.pk, "Tipo")
        if "ricetta" in changes:
            work.ricetta = get_record(Ricetta, recipe.pk, "Ricetta") if recipe else None
        if not work.tipo_lavorazione.attivo or (work.ricetta_id and not work.ricetta.attiva):
            raise ValidationError("Tipo e ricetta devono essere attivi.")
        if "note" in changes:
            work.note = changes["note"]
        work.save()
        return work

    @staticmethod
    @transaction.atomic
    def start(*, actor, lavorazione):
        require_permission(actor, "can_execute_production")
        work = lock_work(lavorazione)
        from .azienda_common import managed_guard
        managed_guard(work)
        if work.stato != Lavorazione.Stato.PIANIFICATA:
            raise ValidationError("Si può avviare soltanto una lavorazione pianificata.")
        if not work.tipo_lavorazione.attivo or (work.ricetta_id and not work.ricetta.attiva):
            raise ValidationError("Tipo o ricetta disattivati.")
        cycle = work.ciclo_produzione
        if cycle.stato not in {CicloProduzione.Stato.PIANIFICATO, CicloProduzione.Stato.IN_CORSO}:
            raise ValidationError("Il ciclo è chiuso.")
        with _execution_write():
            if cycle.stato == CicloProduzione.Stato.PIANIFICATO:
                cycle.stato = CicloProduzione.Stato.IN_CORSO
                cycle.save()
            work.stato = Lavorazione.Stato.IN_CORSO
            work.data_ora_inizio = timezone.now()
            work.eseguita_da = actor
            work.save()
        return work

    @staticmethod
    @transaction.atomic
    def complete(*, actor, lavorazione):
        require_permission(actor, "can_execute_production")
        work = lock_work(lavorazione)
        from .azienda_common import managed_guard
        managed_guard(work)
        require_running(work)
        CompletionValidator.validate(work)
        with _execution_write():
            work.stato = Lavorazione.Stato.COMPLETATA
            work.data_ora_fine = timezone.now()
            work.note += f"\nCompletata da {actor.get_username()}."
            work.save()
        return work

    @staticmethod
    @transaction.atomic
    def interrupt(*, actor, lavorazione, note):
        require_permission(actor, "can_execute_production")
        if not isinstance(note, str) or not note.strip():
            raise ValidationError("Specificare il motivo dell'interruzione.")
        work = lock_work(lavorazione)
        require_running(work)
        if work.tipo_lavorazione.fase_operativa in {"INVASETTAMENTO", "PASTORIZZAZIONE", "VUOTO"}:
            raise ValidationError("La sessione e i suoi trattamenti richiedono la gestione aziendale; interruzione generica non consentita.")
        with _execution_write():
            work.stato = Lavorazione.Stato.INTERROTTA
            work.data_ora_fine = timezone.now()
            work.note += f"\nInterrotta da {actor.get_username()}: {note}"
            work.save()
        return work

    @staticmethod
    @transaction.atomic
    def cancel(*, actor, lavorazione, note=""):
        require_permission(actor, "can_cancel_unstarted_work")
        work = lock_work(lavorazione)
        if work.stato != Lavorazione.Stato.PIANIFICATA or work.inputs.exists() or work.outputs.exists() or work.lotti_generati.exists():
            raise ValidationError("Si può annullare soltanto una lavorazione mai iniziata e senza materiale registrato.")
        with _execution_write():
            work.stato = Lavorazione.Stato.ANNULLATA
            work.note += f"\nAnnullata da {actor.get_username()}. {note}"
            work.save()
        return work
