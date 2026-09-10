from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import require_permission
from anagrafiche.models import Articolo
from produzione.models import CicloProduzione, Lavorazione
from produzione.models.protections import _execution_write
from .locking import get_record, lock_cycle_tree


class ProductionCycleService:
    @staticmethod
    @transaction.atomic
    def create(*, actor, articolo, data=None, note=""):
        require_permission(actor, "can_plan_production")
        article = get_record(Articolo, articolo, "Articolo")
        if not article.attivo:
            raise ValidationError("Non si può pianificare un articolo disattivato.")
        return CicloProduzione.objects.create(articolo=article, data=data or timezone.localdate(), creato_da=actor, note=note)

    @staticmethod
    @transaction.atomic
    def reschedule(*, actor, ciclo, data, note=None):
        require_permission(actor, "can_plan_production")
        cycle = get_record(CicloProduzione, ciclo, "Ciclo", lock=True)
        if cycle.stato != CicloProduzione.Stato.PIANIFICATO:
            raise ValidationError("Solo un ciclo pianificato può essere ripianificato.")
        cycle.data = data
        if note is not None:
            cycle.note = note
        cycle.save()
        return cycle

    @staticmethod
    @transaction.atomic
    def start(*, actor, ciclo):
        require_permission(actor, "can_plan_production")
        cycle = get_record(CicloProduzione, ciclo, "Ciclo", lock=True)
        if cycle.stato != CicloProduzione.Stato.PIANIFICATO:
            raise ValidationError("Il ciclo non è pianificato.")
        with _execution_write():
            cycle.stato = CicloProduzione.Stato.IN_CORSO
            cycle.save()
        return cycle

    @staticmethod
    @transaction.atomic
    def complete(*, actor, ciclo):
        require_permission(actor, "can_plan_production")
        cycle, works = lock_cycle_tree(ciclo)
        if cycle.stato != CicloProduzione.Stato.IN_CORSO:
            raise ValidationError("Il ciclo non è in corso.")
        if not works or not any(w.stato == Lavorazione.Stato.COMPLETATA for w in works):
            raise ValidationError("Serve almeno una lavorazione completata.")
        if any(w.stato not in {Lavorazione.Stato.COMPLETATA, Lavorazione.Stato.ANNULLATA} for w in works):
            raise ValidationError("Restano lavorazioni pianificate, in corso o interrotte da risolvere.")
        with _execution_write():
            cycle.stato = CicloProduzione.Stato.COMPLETATO
            cycle.data_chiusura = timezone.now()
            cycle.note += f"\nCompletato da {actor.get_username()}."
            cycle.save()
        return cycle

    @staticmethod
    @transaction.atomic
    def cancel(*, actor, ciclo, note=""):
        require_permission(actor, "can_plan_production")
        cycle, works = lock_cycle_tree(ciclo)
        if cycle.stato not in {CicloProduzione.Stato.PIANIFICATO, CicloProduzione.Stato.IN_CORSO}:
            raise ValidationError("Il ciclo è già terminato.")
        if any(w.stato not in {Lavorazione.Stato.PIANIFICATA, Lavorazione.Stato.ANNULLATA} or w.inputs.exists() or w.outputs.exists() or w.lotti_generati.exists() for w in works):
            raise ValidationError("Un ciclo con lavorazioni iniziate o materiale registrato non può essere annullato.")
        with _execution_write():
            for work in works:
                if work.stato == Lavorazione.Stato.PIANIFICATA:
                    work.stato = Lavorazione.Stato.ANNULLATA
                    work.note += f"\nAnnullata con il ciclo da {actor.get_username()}. {note}"
                    work.save()
            cycle.stato = CicloProduzione.Stato.ANNULLATO
            cycle.data_chiusura = timezone.now()
            cycle.note += f"\nAnnullato da {actor.get_username()}. {note}"
            cycle.save()
        return cycle
