"""Tracciabilità materiale in sola lettura, con contesto di processo separato."""
from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.utils import timezone
from accounts.permissions import require_permission
from magazzino.models import Lotto, Movimento, RicevimentoLotto
from produzione.models import (InputLavorazione, OutputLavorazione, Lavorazione,
    UnitaLavorazione, PartecipazioneUnitaLavorazione, RisorsaLavorazione,
    SessioneProduzioneSemplificata, PrelievoSessioneSemplificata,
    NonConformitaSessioneSemplificata)
from .graph import walk_lots, has_cycle, validate_limit
from .locking import get_record


def iso(value):
    return value.isoformat() if value is not None else None


class GenealogyService:
    @classmethod
    def upstream(cls, *, actor, lotto, max_lotti=1000):
        return cls.trace(actor=actor, lotto=lotto, direzione="MONTE", max_lotti=max_lotti)

    @classmethod
    def downstream(cls, *, actor, lotto, max_lotti=1000):
        return cls.trace(actor=actor, lotto=lotto, direzione="VALLE", max_lotti=max_lotti)

    @staticmethod
    def trace(*, actor, lotto, direzione, max_lotti=1000):
        require_permission(actor, "can_view_genealogy")
        if direzione not in {"MONTE", "VALLE"}:
            raise ValidationError("Direzione ammessa: MONTE oppure VALLE.")
        validate_limit(max_lotti)
        root = get_record(Lotto, lotto, "Lotto")
        material_works = set()
        material_sessions = set()

        def neighbors(frontier):
            if direzione == "MONTE":
                works = set(Lotto.objects.filter(pk__in=frontier).exclude(lavorazione_origine_id=None).values_list("lavorazione_origine_id", flat=True))
                material_works.update(works)
                sessions = set(SessioneProduzioneSemplificata.objects.filter(
                    lotto_prodotto_id__in=frontier
                ).values_list("pk", flat=True))
                pending = set(sessions)
                while pending:
                    parents = set(SessioneProduzioneSemplificata.objects.filter(
                        pk__in=pending, lotto_origine_id__isnull=False
                    ).values_list("lotto_origine_id", flat=True)) - sessions
                    sessions.update(parents)
                    pending = parents
                # I materiali usati nel confezionamento appartengono allo stesso lotto
                # prodotto dall'etichettatura, che non cambia codice in questa fase.
                packaging = set(SessioneProduzioneSemplificata.objects.filter(
                    tipo="CONFEZIONAMENTO", lotto_origine_id__in=sessions
                ).values_list("pk", flat=True))
                sessions.update(packaging)
                material_sessions.update(sessions)
                legacy = InputLavorazione.objects.filter(lavorazione_id__in=works).values_list("lotto_id", flat=True)
                simple = PrelievoSessioneSemplificata.objects.filter(sessione_id__in=sessions).values_list("lotto_id", flat=True)
                return set(legacy) | set(simple)
            works = set(InputLavorazione.objects.filter(lotto_id__in=frontier).values_list("lavorazione_id", flat=True))
            material_works.update(works)
            sessions = set(PrelievoSessioneSemplificata.objects.filter(
                lotto_id__in=frontier, sessione__lotto_prodotto__isnull=False
            ).values_list("sessione_id", flat=True))
            material_sessions.update(sessions)
            # Include le identità preparate anche prima del carico fisico.
            legacy = Lotto.objects.filter(lavorazione_origine_id__in=works).values_list("pk", flat=True)
            simple = SessioneProduzioneSemplificata.objects.filter(pk__in=sessions).values_list("lotto_prodotto_id", flat=True)
            return set(legacy) | set(simple)

        lot_ids, omitted = walk_lots(root.pk, neighbors, max_lotti)
        lots = list(Lotto.objects.filter(pk__in=lot_ids).select_related("articolo__categoria", "fornitore").order_by("pk"))
        # L'origine di ogni lotto incluso è sempre documentata, anche in VALLE.
        material_works.update(l.lavorazione_origine_id for l in lots if l.lavorazione_origine_id)
        units = list(UnitaLavorazione.objects.filter(lotto_id__in=lot_ids).select_related("risorsa_produttiva").order_by("pk"))
        participations = list(PartecipazioneUnitaLavorazione.objects.filter(unita_lavorazione_id__in=[u.pk for u in units]).order_by("pk"))
        treatment_ids = {p.lavorazione_id for p in participations}
        work_ids = material_works | treatment_ids
        works = list(Lavorazione.objects.filter(pk__in=work_ids).select_related("tipo_lavorazione", "ricetta").order_by("pk"))
        material_sessions.update(SessioneProduzioneSemplificata.objects.filter(
            lotto_prodotto_id__in=lot_ids
        ).values_list("pk", flat=True))
        sessions = list(SessioneProduzioneSemplificata.objects.filter(pk__in=material_sessions)
            .select_related("ricetta__articolo", "lotto_prodotto").order_by("pk"))

        inputs = list(InputLavorazione.objects.filter(lavorazione_id__in=material_works, lotto_id__in=lot_ids).order_by("pk"))
        outputs = list(OutputLavorazione.objects.filter(lavorazione_id__in=material_works, lotto_id__in=lot_ids).order_by("pk"))
        output_by_lot = {o.lotto_id: o for o in outputs}
        movements = Movimento.objects.filter(Q(input_lavorazione_id__in=[i.pk for i in inputs]) | Q(output_lavorazione_id__in=[o.pk for o in outputs])).order_by("pk")
        input_movements, output_movements = defaultdict(list), defaultdict(list)
        for movement in movements:
            if movement.input_lavorazione_id:
                input_movements[movement.input_lavorazione_id].append(movement.pk)
            if movement.output_lavorazione_id:
                output_movements[movement.output_lavorazione_id].append(movement.pk)
        edges = []
        for record in inputs:
            edges.append({"tipo": "CONSUMO", "da": f"lotto:{record.lotto_id}", "a": f"lavorazione:{record.lavorazione_id}",
                "input_id": record.pk, "riga_ricetta_id": record.riga_ricetta_id, "requisito_input_id": record.requisito_input_id,
                "quantita": str(record.quantita), "movimenti_ids": input_movements[record.pk]})
        for lot in lots:
            if lot.lavorazione_origine_id:
                output = output_by_lot.get(lot.pk)
                edges.append({"tipo": "PRODUZIONE", "da": f"lavorazione:{lot.lavorazione_origine_id}", "a": f"lotto:{lot.pk}",
                    "output_id": output.pk if output else None, "quantita": str(output.quantita) if output else None,
                    "movimenti_ids": output_movements[output.pk] if output else [], "output_registrato": output is not None})
        simple_inputs = list(PrelievoSessioneSemplificata.objects.filter(
            sessione_id__in=material_sessions, lotto_id__in=lot_ids
        ).select_related("movimento").order_by("pk"))
        for record in simple_inputs:
            edges.append({"tipo": "CONSUMO", "da": f"lotto:{record.lotto_id}",
                "a": f"sessione:{record.sessione_id}", "prelievo_sessione_id": record.pk,
                "da_ricetta": record.da_ricetta,
                "quantita": str(record.quantita_kg),
                "movimenti_ids": [record.movimento_id] if record.movimento_id else []})
        simple_output_movements = Movimento.objects.filter(
            sessione_semplificata_id__in=material_sessions, lotto_id__in=lot_ids
        ).order_by("pk")
        output_movements_by_session = defaultdict(list)
        for movement in simple_output_movements:
            output_movements_by_session[movement.sessione_semplificata_id].append(movement.pk)
        for session in sessions:
            if session.lotto_origine_id and session.lotto_origine_id in material_sessions:
                edges.append({"tipo": "PASSAGGIO_PRODUTTIVO", "da": f"sessione:{session.lotto_origine_id}",
                    "a": f"sessione:{session.pk}", "quantita": None, "movimenti_ids": []})
            if session.lotto_prodotto_id in lot_ids:
                edges.append({"tipo": "PRODUZIONE", "da": f"sessione:{session.pk}",
                    "a": f"lotto:{session.lotto_prodotto_id}", "sessione_id": session.pk,
                    "quantita": str(session.quantita_finale_kg) if session.quantita_finale_kg is not None else None,
                    "movimenti_ids": output_movements_by_session[session.pk], "output_registrato": True})
            elif (session.tipo == "CONFEZIONAMENTO" and session.lotto_origine_id
                  and session.lotto_origine.lotto_prodotto_id in lot_ids):
                edges.append({"tipo": "CONFEZIONAMENTO", "da": f"sessione:{session.pk}",
                    "a": f"lotto:{session.lotto_origine.lotto_prodotto_id}", "sessione_id": session.pk,
                    "quantita": str(session.quantita_finale_kg) if session.quantita_finale_kg is not None else None,
                    "movimenti_ids": [], "output_registrato": True})

        from qualita.models import ControlloQualita, NonConformita
        controls = list(ControlloQualita.objects.filter(lavorazione_id__in=work_ids).select_related("controllo_richiesto__parametro_controllo").order_by("pk"))
        resource_uses = list(RisorsaLavorazione.objects.filter(lavorazione_id__in=work_ids).select_related("risorsa_produttiva").order_by("pk"))
        resource_ids = {r.risorsa_produttiva_id for r in resource_uses} | {u.risorsa_produttiva_id for u in units if u.risorsa_produttiva_id}
        direct_case_ids = set(NonConformita.objects.filter(
            Q(lotto_id__in=lot_ids) | Q(lavorazione_id__in=work_ids) | Q(controllo_qualita_id__in=[c.pk for c in controls])
            | Q(azioni__movimento__lotto_id__in=lot_ids)
            | Q(azioni__lavorazione_id__in=work_ids)).values_list("pk", flat=True))
        cases = NonConformita.objects.filter(Q(pk__in=direct_case_ids) | Q(risorsa_produttiva_id__in=resource_ids)).order_by("pk")
        simple_cases = list(NonConformitaSessioneSemplificata.objects.filter(
            sessione_id__in=material_sessions
        ).select_related("controllo").order_by("pk"))
        receipts = RicevimentoLotto.objects.filter(lotto_id__in=lot_ids).order_by("pk")
        external_quantities = defaultdict(lambda: 0)
        for edge in edges:
            if edge["tipo"] == "CONSUMO" and edge["da"].startswith("lotto:"):
                external_quantities[int(edge["da"].split(":", 1)[1])] += Decimal(edge.get("quantita") or "0")
        external_inputs = []
        for lot in lots:
            if lot.tipo != Lotto.Tipo.ACQUISTO:
                continue
            category_chain = [lot.articolo.categoria, *lot.articolo.categoria.antenati()]
            external_inputs.append({
                "lotto_id": lot.pk, "lotto_codice": lot.codice_lotto,
                "articolo_codice": lot.articolo.codice, "articolo_descrizione": lot.articolo.descrizione,
                "unita_misura": lot.articolo.unita_misura,
                "quantita": str(external_quantities[lot.pk]),
                "fornitore": lot.fornitore.ragione_sociale if lot.fornitore_id else None,
                "moca": any(category.codice.upper() == "MOCA" for category in category_chain),
                "data_scadenza": iso(lot.data_scadenza),
            })
        external_inputs.sort(key=lambda row: (not row["moca"], row["articolo_codice"], row["lotto_codice"]))
        return {
            "versione": 1, "lotto_radice_id": root.pk, "direzione": direzione,
            "generato_il": iso(timezone.now()), "max_lotti": max_lotti,
            "troncato": bool(omitted), "frontiera_omessa_ids": sorted(omitted),
            "ciclo_materiale_rilevato": has_cycle((e["da"], e["a"]) for e in edges),
            "lotti": [{"id": l.pk, "nodo": f"lotto:{l.pk}", "codice": l.codice_lotto, "tipo": l.tipo,
                "articolo_id": l.articolo_id, "articolo_codice": l.articolo.codice,
                "articolo_descrizione": l.articolo.descrizione, "unita_misura": l.articolo.unita_misura,
                "fornitore_id": l.fornitore_id, "fornitore": l.fornitore.ragione_sociale if l.fornitore_id else None,
                "data_produzione": iso(l.data_produzione), "data_scadenza": iso(l.data_scadenza),
                "lavorazione_origine_id": l.lavorazione_origine_id} for l in lots],
            "lavorazioni": [{"id": w.pk, "nodo": f"lavorazione:{w.pk}", "ciclo_id": w.ciclo_produzione_id,
                "tipo_id": w.tipo_lavorazione_id, "tipo_codice": w.tipo_lavorazione.codice, "stato": w.stato,
                "ricetta_id": w.ricetta_id, "versione_ricetta": w.ricetta.versione if w.ricetta_id else None,
                "inizio": iso(w.data_ora_inizio), "fine": iso(w.data_ora_fine),
                "ruolo": "MATERIALE" if w.pk in material_works else "TRATTAMENTO_UNITA"} for w in works],
            "sessioni_semplificate": [{"id": s.pk, "nodo": f"sessione:{s.pk}",
                "lotto_codice": s.lotto_codice, "tipo": s.tipo, "stato": s.stato,
                "articolo_id": s.ricetta.articolo_id, "articolo_codice": s.ricetta.articolo.codice,
                "lotto_prodotto_id": s.lotto_prodotto_id, "aperta_il": iso(s.aperta_il),
                "chiusa_il": iso(s.chiusa_il)} for s in sessions],
            "legami_materiali": edges,
            "materiali_esterni": external_inputs,
            "ricevimenti": [{"id": r.pk, "lotto_id": r.lotto_id, "quantita": str(r.quantita_ricevuta),
                "data": iso(r.data_ricevimento), "numero_ddt": r.numero_ddt, "numero_fattura": r.numero_fattura} for r in receipts],
            "unita": [{"id": u.pk, "codice": u.codice, "lotto_id": u.lotto_id, "lavorazione_origine_id": u.lavorazione_origine_id,
                "stato": u.stato, "quantita": str(u.quantita) if u.quantita is not None else None,
                "risorsa_id": u.risorsa_produttiva_id, "risorsa_codice": u.risorsa_produttiva.codice if u.risorsa_produttiva_id else None} for u in units],
            "partecipazioni": [{"id": p.pk, "unita_id": p.unita_lavorazione_id, "lavorazione_id": p.lavorazione_id} for p in participations],
            "risorse_utilizzate": [{"id": r.pk, "lavorazione_id": r.lavorazione_id,
                "risorsa_id": r.risorsa_produttiva_id, "codice": r.risorsa_produttiva.codice, "tipo": r.risorsa_produttiva.tipo} for r in resource_uses],
            "controlli": [{"id": c.pk, "lavorazione_id": c.lavorazione_id,
                "parametro_id": c.controllo_richiesto.parametro_controllo_id, "parametro": c.controllo_richiesto.parametro_controllo.codice,
                "tipo_dato": c.controllo_richiesto.parametro_controllo.tipo_dato,
                "valore_decimale": str(c.valore_decimale) if c.valore_decimale is not None else None,
                "valore_intero": c.valore_intero, "valore_booleano": c.valore_booleano, "valore_testo": c.valore_testo,
                "conforme": c.conforme, "determina_conformita": c.controllo_richiesto.determina_conformita,
                "data_ora": iso(c.data_ora), "eseguito_da_id": c.eseguito_da_id} for c in controls],
            "non_conformita": [{"id": n.pk, "numero": n.numero, "stato": n.stato,
                "collegamento": "DIRETTO" if n.pk in direct_case_ids else "RISORSA_CONDIVISA",
                "lotto_id": n.lotto_id, "lavorazione_id": n.lavorazione_id,
                "controllo_qualita_id": n.controllo_qualita_id, "risorsa_id": n.risorsa_produttiva_id} for n in cases],
            "non_conformita_semplificate": [{
                "id": n.pk, "sessione_id": n.sessione_id, "stato": n.stato,
                "descrizione": n.descrizione, "controllo_id": n.controllo_id,
                "controllo": f"{n.controllo.get_tipo_display()} {n.controllo.numero}" if n.controllo_id else None,
                "quantita_coinvolta_kg": str(n.quantita_coinvolta_kg) if n.quantita_coinvolta_kg is not None else None,
                "vasetti_coinvolti": n.vasetti_coinvolti, "aperta_il": iso(n.aperta_il),
            } for n in simple_cases],
        }
