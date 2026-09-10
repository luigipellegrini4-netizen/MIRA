from dataclasses import dataclass

from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from accounts.permissions import require_permission
from anagrafiche.models import Articolo, Fornitore
from magazzino.models import Lotto, Movimento, RicevimentoLotto

from .lots import LotGenerationService
from .movements import MovementService, lock_locations
from .types import Allocation, persisted_id, quantity


@dataclass(frozen=True)
class ReceivingResult:
    lotto: Lotto
    ricevimento: RicevimentoLotto
    movimenti: tuple


class ReceivingService:
    DOCUMENT_FIELDS = frozenset({
        "numero_ddt", "data_ddt", "numero_fattura", "data_fattura",
        "numero_colli", "numero_unita_per_collo", "quantita_per_unita",
    })

    @classmethod
    @transaction.atomic
    def receive(cls, *, actor, articolo, fornitore, quantita_ricevuta, destinazioni,
                codice_lotto=None, data_produzione=None, data_scadenza=None,
                data_ricevimento=None, note="", **documenti):
        require_permission(actor, "can_receive_goods")
        total = quantity(quantita_ricevuta)
        allocations = tuple(destinazioni)
        if not allocations or any(not isinstance(a, Allocation) for a in allocations):
            raise ValidationError("Specificare almeno una Allocation di destinazione.")
        if sum(a.quantita for a in allocations) != total:
            raise ValidationError("La somma delle destinazioni deve coincidere con la quantità ricevuta.")
        if set(documenti) - cls.DOCUMENT_FIELDS:
            raise ValidationError("Campi documento non riconosciuti.")
        if not isinstance(note, str):
            raise ValidationError("Le note devono essere testuali.")
        data_produzione = Lotto._meta.get_field("data_produzione").clean(data_produzione, None)
        data_scadenza = Lotto._meta.get_field("data_scadenza").clean(data_scadenza, None)
        try:
            # Il lock articolo protegge la ricerca/creazione di un lotto ancora
            # inesistente. Il fornitore si legge dal DB, non da oggetti obsoleti.
            article = Articolo.objects.select_for_update().get(pk=persisted_id(articolo, "Articolo"))
            supplier = Fornitore.objects.get(pk=persisted_id(fornitore, "Fornitore"))
        except (Articolo.DoesNotExist, Fornitore.DoesNotExist):
            raise ValidationError("Articolo o fornitore inesistente.") from None
        if not article.attivo or not supplier.attivo:
            raise ValidationError("Articolo e fornitore devono essere attivi per ricevere merce.")
        if codice_lotto is not None and not isinstance(codice_lotto, str):
            raise ValidationError("Il codice lotto deve essere testuale.")
        code = (codice_lotto or "").strip()
        if not code:
            if article.tracciabilita_lotto:
                raise ValidationError("Il codice del lotto fornitore è obbligatorio per questo articolo.")
            code = LotGenerationService.technical_code()
            while Lotto.objects.filter(articolo=article, fornitore=supplier, codice_lotto=code).exists():
                code = LotGenerationService.technical_code()

        lot = Lotto.objects.select_for_update().filter(
            articolo=article, fornitore=supplier, codice_lotto=code, tipo=Lotto.Tipo.ACQUISTO,
        ).first()
        if lot is None:
            lot = Lotto.objects.create(articolo=article, fornitore=supplier, codice_lotto=code,
                                       tipo=Lotto.Tipo.ACQUISTO, data_produzione=data_produzione,
                                       data_scadenza=data_scadenza)
        else:
            for field, value in (("data_produzione", data_produzione), ("data_scadenza", data_scadenza)):
                if value is not None and getattr(lot, field) != value:
                    raise ValidationError(f"{field} diversa da quella del lotto già registrato; lo storico non viene sovrascritto.")

        # Preacquisizione di TUTTE le destinazioni prima di qualsiasi carico,
        # così ricevimenti con più posizioni non acquisiscono lock al contrario.
        lock_locations([a.posizione for a in allocations])
        receipt = RicevimentoLotto(lotto=lot, quantita_ricevuta=total,
                                  data_ricevimento=data_ricevimento or timezone.now(),
                                  note=note, **documenti)
        receipt.full_clean()
        receipt.save()
        movements = tuple(
            MovementService.register(actor=actor, lotto=lot, tipo=Movimento.Tipo.CARICO,
                                     quantita=a.quantita, destinazione=a.posizione,
                                     note=f"Ricevimento #{receipt.pk}" + (f" — {note}" if note else ""))
            for a in allocations
        )
        return ReceivingResult(lot, receipt, movements)
