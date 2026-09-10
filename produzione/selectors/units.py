from django.core.exceptions import PermissionDenied
from produzione.models import UnitaLavorazione
from produzione.services.locking import get_record


class UnitSelector:
    @staticmethod
    def detail(*, actor, unita_lavorazione):
        if not actor or not actor.is_authenticated or not actor.is_active or not actor.has_perm("produzione.view_unitalavorazione"):
            raise PermissionDenied("Non puoi consultare le unità operative.")
        unit = get_record(UnitaLavorazione, unita_lavorazione, "Unità")
        participations = list(unit.partecipazioni.select_related("lavorazione__tipo_lavorazione").order_by("pk"))
        completed = {p.lavorazione.tipo_lavorazione_id for p in participations if p.lavorazione.stato == "COMPLETATA"}
        return {
            "id": unit.pk, "codice": unit.codice, "stato": unit.stato,
            "lotto_id": unit.lotto_id, "lavorazione_origine_id": unit.lavorazione_origine_id,
            "risorsa_produttiva_id": unit.risorsa_produttiva_id,
            "quantita": str(unit.quantita) if unit.quantita is not None else None,
            "percorso": [{"tipo_fase_id": r.tipo_fase_id, "nome": r.tipo_fase.nome,
                          "ordine": r.ordine, "obbligatorio": r.obbligatorio,
                          "completata": r.tipo_fase_id in completed}
                         for r in unit.lavorazione_origine.tipo_lavorazione.fasi_unita_richieste.select_related("tipo_fase")],
            "partecipazioni": [{"id": p.pk, "lavorazione_id": p.lavorazione_id,
                                "tipo_fase_id": p.lavorazione.tipo_lavorazione_id,
                                "stato": p.lavorazione.stato} for p in participations],
        }
