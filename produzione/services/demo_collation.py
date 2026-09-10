"""Collaudo ripetibile su dati DEMO11; registra evidenze senza alterare dati aziendali."""
import json
from decimal import Decimal
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone
from magazzino.models import Giacenza, Movimento
from magazzino.services import Allocation, Position, MovementService
from produzione.models import CicloProduzione, TipoLavorazione
from produzione.services import (ProductionCycleService, WorkExecutionService, RecipeInputService,
    InputSelection, OutputService, GenealogyService)
from qualita.models import ParametroControllo, ControlloRichiestoTipoLavorazione
from qualita.services import QualityService, NonConformityService as NC
from .demo_seed import seed_demo, ensure, TAG

MARKER = "DEMO11_REPORT="


class CollationFailure(ValidationError):
    def __init__(self, message, report):
        super().__init__(message)
        self.report = report


def require(condition, message):
    if not condition:
        raise ValidationError(f"Collaudo FAIL: {message}")


def rejected(exception, operation):
    try:
        operation()
    except exception:
        return
    raise ValidationError("Collaudo FAIL: operazione vietata accettata.")


def stocks():
    return [{"id": s.pk, "lotto_id": s.lotto_id, "lotto": s.lotto.codice_lotto,
             "ubicazione": s.ubicazione.codice, "quantita": str(s.quantita)}
            for s in Giacenza.objects.filter(lotto__articolo__codice__startswith="DEMO11_").select_related("lotto", "ubicazione").order_by("pk")]


@transaction.atomic
def run_demo():
    d = seed_demo()
    old = CicloProduzione.objects.filter(note__startswith="DEMO11_COLL_A\n").first()
    if old:
        for line in old.note.splitlines():
            if line.startswith(MARKER):
                return json.loads(line[len(MARKER):])
        raise ValidationError("Collaudo DEMO11 già presente ma privo di verbale: nessuna duplicazione automatica.")
    u, locations = d["users"], d["locations"]
    buffer = Position(locations["BUFFER_PRODUZIONE"].pk)
    main = Position(locations["MAG"].pk)
    rows = {r.articolo.codice: r for r in d["recipe"].righe.select_related("articolo")}
    strawberry, acid = rows["DEMO11_FRAGOLE"], rows["DEMO11_ACIDO"]
    report = {"eseguito_il": timezone.now().isoformat(), "scenari": {}, "problemi_architetturali": [],
              "utenti": {key: {"id": user.pk, "username": user.username} for key, user in u.items()},
              "articoli": {key: obj.pk for key, obj in d["articles"].items()}, "ricetta_id": d["recipe"].pk}

    def scenario(code, operation):
        before = stocks()
        old_movements = set(Movimento.objects.filter(lotto__articolo__codice__startswith="DEMO11_").values_list("pk", flat=True))
        try:
            details = operation()
        except Exception as exc:
            report["scenari"][code] = {"esito": "FAIL", "errore": str(exc), "giacenze_prima": before}
            report["tentativo_annullato"] = True
            report["nota_rollback"] = "Tutto il tentativo è stato annullato: anche i record degli scenari precedenti sono provvisori e non persistiti. Gli scenari successivi non sono stati eseguiti."
            raise CollationFailure(f"Scenario {code}: {exc}", report) from exc
        new_movements = Movimento.objects.filter(lotto__articolo__codice__startswith="DEMO11_").exclude(pk__in=old_movements).order_by("pk")
        report["scenari"][code] = {"esito": "PASS", "dettagli": details, "giacenze_prima": before, "giacenze_dopo": stocks(),
            "movimenti": [{"id": m.pk, "tipo": m.tipo, "lotto_id": m.lotto_id, "quantita": str(m.quantita),
                           "origine_id": m.ubicazione_origine_id, "destinazione_id": m.ubicazione_destinazione_id} for m in new_movements]}
        return details

    produced = {}

    def plan(code, kind=None, recipe=True):
        cycle = ProductionCycleService.create(actor=u["produzione"], articolo=d["articles"]["SEMILAVORATO"], note=f"DEMO11_COLL_{code}\n")
        work = WorkExecutionService.plan(actor=u["produzione"], ciclo=cycle, tipo_lavorazione=kind or d["kind"], ricetta=d["recipe"] if recipe else None)
        return cycle, WorkExecutionService.start(actor=u["operatore"], lavorazione=work)

    def produce(code, location, manual=False):
        cycle, work = plan(code)
        proposal = RecipeInputService.propose(actor=u["operatore"], lavorazione=work, ubicazioni=[locations[location]])
        require(proposal.completa, f"Disponibilità iniziale scenario {code}.")
        proposed_ids = [s.lotto for s in proposal.selections]
        if code == "A":
            require(proposed_ids == [d["lots"]["F_A"].pk, d["lots"]["A_A"].pk], "FEFO fragole e FIFO acido.")
        if code == "C":
            require([(s.lotto, s.quantita) for s in proposal.selections if s.riga_ricetta == strawberry.pk] ==
                    [(d["lots"]["FC_A"].pk, Decimal("6")), (d["lots"]["FC_B"].pk, Decimal("4"))], "Ripartizione 6+4 KG.")
        if manual:
            require(proposed_ids[0] == d["lots"]["F_A"].pk, "Proposta iniziale scenario B.")
            selections = [InputSelection(d["lots"]["F_B"], "10", [Allocation(main, "10")], riga_ricetta=strawberry),
                          InputSelection(d["lots"]["A_B"], ".050", [Allocation(main, ".050")], riga_ricetta=acid)]
            inputs = RecipeInputService.confirm(actor=u["operatore"], lavorazione=work, selections=selections)
        else:
            inputs = RecipeInputService.confirm_proposal(actor=u["operatore"], lavorazione=work, proposal=proposal)
        require(all(r.registrazione.requisito_input_id is None and r.registrazione.riga_ricetta_id for r in inputs), "Input senza requisiti duplicati.")
        output = OutputService.register(actor=u["operatore"], lavorazione=work, requisito_output=d["output"],
            quantita="9.800", destinazioni=[Allocation(buffer, "9.800")], note=TAG)
        require(output.lotto.articolo_id == d["recipe"].articolo_id and output.lotto.codice_lotto.startswith("SL"), "Articolo ricetta e prefisso SL.")
        require(output.registrazione.quantita == output.movimenti[0].quantita == Giacenza.objects.get(lotto=output.lotto).quantita == Decimal("9.8"), "Resa reale indipendente dal teorico.")
        work = WorkExecutionService.complete(actor=u["operatore"], lavorazione=work)
        genealogy = GenealogyService.upstream(actor=u["qualita"], lotto=output.lotto)
        actual = {r.lotto.pk for r in inputs}
        require({lot["id"] for lot in genealogy["lotti"]} == actual | {output.lotto.pk}, "Genealogia dei consumi effettivi.")
        for lot_id in actual:
            downstream = GenealogyService.downstream(actor=u["operatore"], lotto=lot_id)
            require(output.lotto.pk in {lot["id"] for lot in downstream["lotti"]}, "Genealogia inversa.")
        if code != "A":
            ProductionCycleService.complete(actor=u["produzione"], ciclo=cycle)
        produced[code] = (cycle, work, inputs, output)
        return {"ciclo_id": cycle.pk, "lavorazione_id": work.pk, "input_ids": [r.registrazione.pk for r in inputs],
                "output_id": output.registrazione.pk, "lotto_id": output.lotto.pk, "proposti_ids": proposed_ids,
                "lotti_effettivi_ids": sorted(actual), "quantita_reale": "9.800", "genealogia": genealogy}

    scenario("A", lambda: produce("A", "MAG"))
    scenario("B", lambda: produce("B", "MAG", True))
    scenario("C", lambda: produce("C", "C"))

    def insufficient():
        cycle, work = plan("D")
        position = Position(locations["D"].pk)
        proposal = RecipeInputService.propose(actor=u["operatore"], lavorazione=work, ubicazioni=[locations["D"]])
        require(not proposal.completa, "Rilevazione stock insufficiente.")
        rejected(ValidationError, lambda: RecipeInputService.confirm_proposal(actor=u["operatore"], lavorazione=work, proposal=proposal))
        before = stocks()
        movement_count = Movimento.objects.count()
        selections = [InputSelection(d["lots"]["FD"], "10", [Allocation(position, "10")], riga_ricetta=strawberry),
                      InputSelection(d["lots"]["AD"], ".050", [Allocation(position, ".050")], riga_ricetta=acid)]
        rejected(ValidationError, lambda: RecipeInputService.confirm(actor=u["operatore"], lavorazione=work, selections=selections))
        require(before == stocks() and Movimento.objects.count() == movement_count and not work.inputs.exists() and not work.outputs.exists(), "Rollback globale degli ingredienti.")
        WorkExecutionService.interrupt(actor=u["operatore"], lavorazione=work, note="DEMO: tentativo insufficiente, nessuna produzione consolidata")
        return {"lavorazione_id": work.pk, "esito_atteso": "Consumi annullati; nessun output", "input_creati": 0}

    scenario("D", insufficient)
    measurements = []

    def quality():
        require(not d["kind"].controlli_richiesti.exists(), "Nessun parametro aziendale inventato per i semilavorati.")
        kind = ensure(TipoLavorazione, {"codice": "DEMO11_CHECK_TECNICO"}, {"nome": "DEMO11 solo verifica tecnica qualità", "genera_lotto": False, "note": TAG})
        parameter = ensure(ParametroControllo, {"codice": "DEMO11_ESITO_TECNICO"}, {"nome": "DEMO: esito simulato, non specifica aziendale", "tipo_dato": "BOOLEANO", "note": TAG})
        req = ensure(ControlloRichiestoTipoLavorazione, {"tipo_lavorazione": kind, "parametro_controllo": parameter}, {"valore_booleano_atteso": True, "obbligatorio": True, "determina_conformita": True, "note": TAG})
        _, work = plan("E", kind, False)
        rejected(ValidationError, lambda: WorkExecutionService.complete(actor=u["operatore"], lavorazione=work))
        good = QualityService.record(actor=u["operatore"], lavorazione=work, controllo_richiesto=req, valore=True)
        WorkExecutionService.complete(actor=u["operatore"], lavorazione=work)
        _, bad_work = plan("E_NEGATIVO", kind, False)
        bad = QualityService.record(actor=u["operatore"], lavorazione=bad_work, controllo_richiesto=req, valore=False)
        rejected(ValidationError, lambda: WorkExecutionService.complete(actor=u["operatore"], lavorazione=bad_work))
        WorkExecutionService.interrupt(actor=u["operatore"], lavorazione=bad_work, note="DEMO tecnico negativo intenzionale")
        measurements.extend([good, bad])
        return {"tipo": "Controllo DEMO tecnico separato, non parametro aziendale", "controlli_ids": [good.pk, bad.pk], "lavorazioni_ids": [work.pk, bad_work.pk]}

    scenario("E", quality)

    def nonconformity():
        lot = produced["A"][3].lotto
        nc = NC.open(actor=u["operatore"], descrizione="DEMO: campione da verificare", lotto=lot)
        rejected(PermissionDenied, lambda: NC.take_charge(actor=u["operatore"], non_conformita=nc))
        rejected(PermissionDenied, lambda: NC.close(actor=u["operatore"], non_conformita=nc, note="Tentativo vietato"))
        NC.take_charge(actor=u["qualita"], non_conformita=nc)
        quarantine = Position(locations["QUARANTENA"].pk)
        actions = []
        for kind, amount, origin, target in (("QUARANTENA", "2", buffer, quarantine), ("REINTEGRO", "1.5", quarantine, buffer), ("SCARTO", ".5", quarantine, None)):
            action = NC.action(actor=u["qualita"], non_conformita=nc, tipo_azione=kind, descrizione=f"DEMO {kind}", quantita=amount, origine=origin, destinazione=target)
            require(action.movimento.tipo == kind and action.non_conformita_id == nc.pk, "Catena NC → azione → movimento.")
            actions.append(action.pk)
        verification = NC.verify(actor=u["qualita"], non_conformita=nc, esito="EFFICACE", descrizione="DEMO verifica esplicita")
        nc.refresh_from_db()
        require(nc.stato == "IN_GESTIONE", "La verifica non chiude automaticamente.")
        NC.close(actor=u["qualita"], non_conformita=nc, note="DEMO chiusura deliberata dopo verifica")
        return {"nc_id": nc.pk, "azioni_ids": actions, "verifica_id": verification.pk}

    scenario("F", nonconformity)

    def adjustment():
        require(u["magazziniere"].has_perm("magazzino.view_giacenza") and u["magazziniere"].has_perm("auth.can_count_inventory"), "Consultazione e autorizzazione conteggio.")
        require(u["multi"].has_perm("auth.can_execute_production") and u["multi"].has_perm("auth.can_adjust_inventory"), "Permessi multi-ruolo cumulativi.")
        require(not u["admin"].has_perm("auth.can_execute_production"), "Amministratore puro senza operatività.")
        def adjust(actor, note):
            return MovementService.register(actor=actor, lotto=d["lots"]["F_A"], tipo="RETTIFICA", quantita="1", origine=main, note=note)
        rejected(PermissionDenied, lambda: adjust(u["magazziniere"], "DEMO"))
        rejected(PermissionDenied, lambda: adjust(u["qualita"], "DEMO"))
        rejected(ValidationError, lambda: adjust(u["magazzino"], ""))
        before = Giacenza.objects.get(lotto=d["lots"]["F_A"], ubicazione=locations["MAG"]).quantita
        movement = adjust(u["magazzino"], "DEMO conteggio fisico simulato: un KG in meno")
        require(Giacenza.objects.get(lotto=d["lots"]["F_A"], ubicazione=locations["MAG"]).quantita == before - 1, "Rettifica motivata.")
        return {"movimento_id": movement.pk, "conteggio": "Confronto tecnico simulato e permesso verificato; nessun documento inventariale dedicato"}

    scenario("G", adjustment)

    def historical():
        _, work, inputs, output = produced["A"]
        objects = [work, inputs[0].registrazione, output.registrazione, output.movimenti[0], *measurements]
        for obj in objects:
            rejected(ValidationError, obj.save)
            rejected(ValidationError, obj.delete)
        return {"record_verificati": [{"modello": type(obj).__name__, "id": obj.pk} for obj in objects]}

    scenario("STORICO", historical)
    cycle = produced["A"][0]
    cycle.refresh_from_db()
    cycle.note += "\n" + MARKER + json.dumps(report, ensure_ascii=False)
    cycle.save()
    ProductionCycleService.complete(actor=u["produzione"], ciclo=cycle)
    return report
