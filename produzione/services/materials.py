from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.permissions import require_permission
from magazzino.models import Lotto
from magazzino.services import Allocation, LotGenerationService, MovementService
from magazzino.services.movements import lock_locations
from magazzino.services.types import persisted_id, quantity
from produzione.models import InputLavorazione, OutputLavorazione, RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione, RigaRicetta
from .locking import get_record, lock_work, lock_work_for_inputs, require_running


def validate_allocations(allocations, total):
    allocations = tuple(allocations)
    if not allocations or any(not isinstance(a, Allocation) for a in allocations):
        raise ValidationError("Specificare almeno un'allocazione valida.")
    if sum(a.quantita for a in allocations) != total:
        raise ValidationError("Somma delle allocazioni diversa dalla quantità dichiarata.")
    return allocations


@dataclass(frozen=True)
class MaterialResult:
    registrazione: object
    lotto: Lotto
    movimenti: tuple


@dataclass(frozen=True)
class InputSelection:
    lotto: object
    quantita: object
    origini: object
    requisito_input: object = None
    riga_ricetta: object = None
    note: str = ""

    def __post_init__(self):
        if (self.requisito_input is None) == (self.riga_ricetta is None):
            raise ValidationError("Specificare una sola origine teorica dell'input.")
        object.__setattr__(self, "lotto", persisted_id(self.lotto, "Lotto"))
        object.__setattr__(self, "quantita", quantity(self.quantita))
        object.__setattr__(self, "origini", validate_allocations(self.origini, self.quantita))
        for field in ("requisito_input", "riga_ricetta"):
            value = getattr(self, field)
            if value is not None:
                object.__setattr__(self, field, persisted_id(value, field))


class InputService:
    @staticmethod
    @transaction.atomic
    def register(*, actor, lavorazione, lotto, quantita, origini, requisito_input=None, riga_ricetta=None, note=""):
        require_permission(actor, "can_record_production_consumption")
        selection = InputSelection(lotto, quantita, origini, requisito_input, riga_ricetta, note)
        return InputService.register_many(actor=actor, lavorazione=lavorazione, selections=[selection])[0]

    @staticmethod
    @transaction.atomic
    def register_many(*, actor, lavorazione, selections):
        require_permission(actor, "can_record_production_consumption")
        selections = tuple(selections)
        if not selections or any(not isinstance(s, InputSelection) for s in selections):
            raise ValidationError("Specificare almeno una InputSelection valida.")
        lot_ids = {s.lotto for s in selections}
        work = lock_work_for_inputs(lavorazione, lot_ids)
        require_running(work)
        from .azienda_common import managed_guard
        managed_guard(work)
        lots = {lot.pk: lot for lot in Lotto.objects.select_for_update().filter(pk__in=lot_ids).order_by("pk")}
        if set(lots) != lot_ids:
            raise ValidationError("Lotto inesistente.")
        lock_locations([a.posizione for s in selections for a in s.origini])
        results = []
        for s in selections:
            req = get_record(RequisitoInputTipoLavorazione, s.requisito_input, "Requisito input") if s.requisito_input else None
            row = get_record(RigaRicetta, s.riga_ricetta, "Riga ricetta") if s.riga_ricetta else None
            lot = lots[s.lotto]
            record = InputLavorazione.objects.create(lavorazione=work, requisito_input=req, riga_ricetta=row, lotto=lot, quantita=s.quantita, note=s.note)
            movements = tuple(MovementService.register(actor=actor, lotto=lot, tipo="CONSUMO", quantita=a.quantita,
                origine=a.posizione, input_lavorazione=record, note=s.note) for a in s.origini)
            results.append(MaterialResult(record, lot, movements))
        return tuple(results)


class OutputService:
    @staticmethod
    def prepare_lot(**kwargs):
        """Crea soltanto l'identità: nessun output fittizio o giacenza."""
        return LotGenerationService.create_production(**kwargs)

    @staticmethod
    @transaction.atomic
    def register(*, actor, lavorazione, requisito_output, quantita, destinazioni,
                 articolo=None, lotto=None, data_produzione=None, data_scadenza=None, note=""):
        require_permission(actor, "can_execute_production")
        total = quantity(quantita)
        allocations = validate_allocations(destinazioni, total)
        work = lock_work(lavorazione)
        require_running(work)
        from .azienda_common import managed_guard
        managed_guard(work)
        req = get_record(RequisitoOutputTipoLavorazione, requisito_output, "Requisito output")
        if lotto is None:
            lot = LotGenerationService.create_production(actor=actor, lavorazione=work, requisito_output=req,
                                                         articolo=articolo, data_produzione=data_produzione,
                                                         data_scadenza=data_scadenza)
        else:
            if data_produzione is not None or data_scadenza is not None:
                raise ValidationError("Le date del lotto già creato non si modificano durante il consolidamento.")
            lot = get_record(Lotto, lotto, "Lotto", lock=True)
            if articolo is not None and lot.articolo_id != persisted_id(articolo, "Articolo"):
                raise ValidationError("Articolo incompatibile con il lotto preparato.")
            if OutputLavorazione.objects.filter(lotto=lot).exists():
                raise ValidationError("Questo lotto ha già un output consolidato.")
        lock_locations([a.posizione for a in allocations])
        record = OutputLavorazione.objects.create(lavorazione=work, requisito_output=req, lotto=lot, quantita=total, note=note)
        movements = tuple(MovementService.register(actor=actor, lotto=lot, tipo="PRODUZIONE", quantita=a.quantita,
                                                   destinazione=a.posizione, output_lavorazione=record, note=note)
                          for a in allocations)
        return MaterialResult(record, lot, movements)
