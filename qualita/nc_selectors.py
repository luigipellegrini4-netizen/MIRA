from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import PermissionDenied


def quarantine_balances(*, lotto=None, non_conformita=None):
    """Saldo vincolato per NC/lotto/posizione, derivato solo dalle azioni fisiche.

    Il chiamante che scrive stock deve possedere il lock Lotto. La lettura per
    consultazione non riserva materiale. Lo scarto usa prima la quota della NC.
    """
    from .models import AzioneNonConformita
    actions = AzioneNonConformita.objects.filter(movimento__isnull=False)
    if lotto is not None:
        actions = actions.filter(movimento__lotto_id=getattr(lotto, "pk", lotto))
    if non_conformita is not None:
        actions = actions.filter(non_conformita_id=getattr(non_conformita, "pk", non_conformita))
    held = defaultdict(Decimal)
    for action in actions.select_related("movimento").order_by("pk"):
        movement = action.movimento
        prefix = (action.non_conformita_id, movement.lotto_id)
        if action.tipo_azione == "QUARANTENA":
            key = (*prefix, movement.ubicazione_destinazione_id, movement.scaffale_destinazione, movement.piano_destinazione)
            held[key] += movement.quantita
        elif action.tipo_azione in {"REINTEGRO", "SCARTO"}:
            key = (*prefix, movement.ubicazione_origine_id, movement.scaffale_origine, movement.piano_origine)
            held[key] -= min(held[key], movement.quantita)
    return {key: amount for key, amount in held.items() if amount > 0}


def blocked_quantity(balances, *, lotto_id, ubicazione_id, scaffale, piano, nc_id=None):
    return sum((amount for key, amount in balances.items()
                if key[1:] == (lotto_id, ubicazione_id, scaffale, piano) and (nc_id is None or key[0] == nc_id)), Decimal(0))


def measurement_resolved(measurement):
    """Solo NC esplicitamente riferite alla misura; tutte devono essere chiuse."""
    cases = measurement.non_conformita.all()
    return cases.exists() and not cases.exclude(stato="CHIUSA").exists()


class NonConformitySelector:
    @staticmethod
    def detail(*, actor, non_conformita):
        from produzione.services.locking import get_record
        from .models import NonConformita
        if not actor or not actor.is_authenticated or not actor.is_active or not actor.has_perm("qualita.view_nonconformita"):
            raise PermissionDenied("Non puoi consultare le non conformità.")
        nc = get_record(NonConformita, non_conformita, "NC")
        return {
            "id": nc.pk, "numero": nc.numero, "stato": nc.stato, "tipo": nc.tipo,
            "descrizione": nc.descrizione, "lotto_id": nc.lotto_id,
            "lavorazione_id": nc.lavorazione_id, "controllo_qualita_id": nc.controllo_qualita_id,
            "azioni": list(nc.azioni.values("id", "tipo_azione", "descrizione", "movimento_id", "lavorazione_id", "eseguita_da_id")),
            "verifiche": list(nc.verifiche.values("id", "esito", "descrizione", "controllo_qualita_id", "verificata_da_id")),
            "quarantena_residua": [{"lotto_id": k[1], "ubicazione_id": k[2], "scaffale": k[3], "piano": k[4], "quantita": str(v)}
                                  for k, v in quarantine_balances(non_conformita=nc).items()],
        }
