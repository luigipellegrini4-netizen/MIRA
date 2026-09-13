from functools import wraps
from datetime import date
from uuid import uuid4, UUID
from django import forms
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Q, Sum
from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from anagrafiche.models import Articolo
from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.services import ReceivingService, MovementService, Position, Allocation
from produzione.models import (Lavorazione, NonConformitaSessioneSemplificata,
                               SessioneProduzioneSemplificata)
from produzione.services import (ProductionCycleService, WorkExecutionService, InputService,
    OutputService, RecipeInputService, InputSelection, GenealogyService, ResourceService, WorkUnitService)
from qualita.models import NonConformita
from qualita.services import QualityService, NonConformityService
from .forms import OperationForm, IngredientForm
from .models import InvioOperativo


def permitted(permission):
    def decorate(view):
        @login_required
        @wraps(view)
        def wrapped(request, *args, **kwargs):
            if not request.user.is_active or not request.user.has_perm(permission):
                raise PermissionDenied
            return view(request, *args, **kwargs)
        return wrapped
    return decorate


def token_for(request):
    return signing.dumps({"id": str(uuid4()), "user": request.user.pk, "path": request.path}, salt="mira-ui")


@transaction.atomic
def submit_once(request, token, operation):
    try:
        data = signing.loads(token, salt="mira-ui", max_age=7200)
        identifier = UUID(data["id"])
        if data["user"] != request.user.pk or data["path"] != request.path:
            raise ValueError()
    except (signing.BadSignature, ValueError, KeyError, TypeError):
        raise ValidationError("Modulo scaduto o non valido. Riapri la pagina e riprova.") from None
    _, created = InvioOperativo.objects.get_or_create(pk=identifier,
        defaults={"utente": request.user, "percorso": request.path})
    if created:
        operation()
    return created


def position(data, name):
    location = data.get(name)
    return Position(location.pk, data.get(name + "_scaffale", ""), data.get(name + "_piano", "")) if location else None


def error_form(form, exc):
    form.add_error(None, " · ".join(exc.messages))


def paged(request, queryset):
    return Paginator(queryset, 30).get_page(request.GET.get("pagina"))


@login_required
def home(request):
    stats, works, cases = [], [], []
    if request.user.has_perm("produzione.view_sessioneproduzionesemplificata"):
        active = SessioneProduzioneSemplificata.objects.filter(stato="APERTA")
        stats += [("Produzioni in corso", active.count(), "simple_sessions"),
                  ("Da avviare", SessioneProduzioneSemplificata.objects.filter(stato="PIANIFICATA").count(), "simple_sessions")]
        works = active.select_related("ricetta__articolo")[:6]
    if request.user.has_perm("qualita.view_nonconformita"):
        opened = NonConformita.objects.exclude(stato="CHIUSA")
        simple_opened = NonConformitaSessioneSemplificata.objects.exclude(stato="CHIUSA")
        stats.append(("Non conformità aperte", opened.count() + simple_opened.count(), "qualita"))
        cases = opened.select_related("lotto")[:5]
    if request.user.has_perm("magazzino.view_lotto"):
        stats.append(("Lotti tracciati", Lotto.objects.count(), "magazzino"))
    return render(request, "interfaccia/home.html", {"section": "home", "stats": stats, "works": works, "cases": cases})


@permitted("magazzino.view_giacenza")
def stock(request):
    query = request.GET.get("q", "").strip()[:150]
    stocks = Giacenza.objects.select_related("lotto__articolo__categoria", "ubicazione").filter(quantita__gt=0)
    if query:
        stocks = stocks.filter(
            Q(lotto__codice_lotto__icontains=query)
            | Q(lotto__articolo__codice__icontains=query)
            | Q(lotto__articolo__descrizione__icontains=query)
            | Q(ubicazione__codice__icontains=query)
            | Q(ubicazione__nome__icontains=query)
        )
    stocks = list(stocks.order_by(
        "lotto__articolo__categoria__codice", "lotto__articolo__categoria_id",
        "lotto__articolo__codice", "lotto__articolo_id", "lotto__data_scadenza", "lotto__codice_lotto",
        "ubicazione__codice", "ubicazione_id", "scaffale", "piano", "pk",
    ))
    for item in stocks:
        if item.lotto.stato_prodotto == "INVASETTATO":
            item.gruppo_giacenza, item.gruppo_codice = "Invasettato", "INV"
        elif item.lotto.stato_prodotto == "PRODOTTO_FINITO":
            item.gruppo_giacenza, item.gruppo_codice = "Prodotti finiti", "PF"
        else:
            item.gruppo_giacenza = item.lotto.articolo.categoria.nome
            item.gruppo_codice = item.lotto.articolo.categoria.codice
    stocks.sort(key=lambda item: (item.gruppo_codice, item.lotto.articolo.codice, item.lotto.codice_lotto,
                                  item.ubicazione.codice, item.scaffale, item.piano, item.pk))
    return render(request, "interfaccia/stock.html", {
        "section": "magazzino", "warehouse_tab": "giacenze",
        "stocks": stocks, "q": query,
    })


@permitted("magazzino.view_movimento")
def movements(request):
    query = request.GET.get("q", "").strip()[:150]
    records = Movimento.objects.select_related("lotto__articolo", "ubicazione_origine", "ubicazione_destinazione", "eseguito_da").order_by("-pk")
    if query:
        records = records.filter(
            Q(lotto__codice_lotto__icontains=query)
            | Q(lotto__articolo__codice__icontains=query)
            | Q(lotto__articolo__descrizione__icontains=query)
            | Q(tipo__icontains=query)
        )
    page = paged(request, records)
    source_labels = {
        "CARICO": "Fornitore / esterno",
        "PRODUZIONE": "Produzione",
        "RETTIFICA": "Rettifica in aumento",
    }
    destination_labels = {
        "CONSUMO": "Produzione",
        "VENDITA": "Cliente",
        "SCARICO": "Smaltimento",
        "SCARTO": "Scarto NC",
        "RETTIFICA": "Rettifica in diminuzione",
    }

    def location_label(location, shelf, level):
        if not location:
            return ""
        details = "/".join(value for value in (shelf, level) if value)
        return f"{location.nome} · {details}" if details else location.nome

    for movement in page:
        movement.percorso_origine = location_label(
            movement.ubicazione_origine, movement.scaffale_origine, movement.piano_origine,
        ) or source_labels.get(movement.tipo, "Origine non indicata")
        movement.percorso_destinazione = location_label(
            movement.ubicazione_destinazione, movement.scaffale_destinazione, movement.piano_destinazione,
        ) or destination_labels.get(movement.tipo, "Destinazione non indicata")
    return render(request, "interfaccia/movements.html", {
        "section": "magazzino", "warehouse_tab": "movimenti",
        "page": page, "q": query,
    })


@permitted("magazzino.view_lotto")
def lot_detail(request, pk):
    lot = get_object_or_404(Lotto.objects.select_related("articolo", "fornitore"), pk=pk)
    initial_quantity = lot.movimenti.filter(
        tipo__in=[Movimento.Tipo.CARICO, Movimento.Tipo.PRODUZIONE]
    ).aggregate(total=Sum("quantita"))["total"] or 0
    outgoing_quantity = lot.movimenti.filter(
        tipo__in=[Movimento.Tipo.CONSUMO, Movimento.Tipo.VENDITA,
                  Movimento.Tipo.SCARTO, Movimento.Tipo.SCARICO]
    ).aggregate(total=Sum("quantita"))["total"] or 0
    sales_movements = list(lot.movimenti.filter(tipo="VENDITA").select_related(
        "riga_vendita__vendita__cliente", "riga_vendita__vendita__registrata_da",
        "ubicazione_origine",
    ).order_by("-data_ora", "-pk"))
    graph = None
    direction = "VALLE" if request.GET.get("direzione") == "VALLE" else "MONTE"
    if request.user.has_perm("auth.can_view_genealogy"):
        graph = GenealogyService.trace(actor=request.user, lotto=lot, direzione=direction)
        labels = {n["nodo"]: (n["codice"], n["unita_misura"]) for n in graph["lotti"]}
        labels.update({w["nodo"]: (f"Lavorazione {w['id']} · {w['tipo_codice']}", "") for w in graph["lavorazioni"]})
        labels.update({s["nodo"]: (f"Produzione {s['lotto_codice']}", "") for s in graph["sessioni_semplificate"]})
        nodes = {
            n["nodo"]: {"titolo": n["codice"],
                        "sottotitolo": f"{n['articolo_codice']} — {n['articolo_descrizione']}",
                        "tipo": "Lotto", "url": reverse("ui:lot", args=[n["id"]]),
                        "corrente": n["id"] == lot.pk,
                        "scadenza": date.fromisoformat(n["data_scadenza"]).strftime("%d/%m/%Y") if n["data_scadenza"] else ""}
            for n in graph["lotti"]
        }
        nodes.update({
            s["nodo"]: {"titolo": s["lotto_codice"], "sottotitolo": s["articolo_codice"],
                        "tipo": "Produzione", "url": reverse("ui:simple_session", args=[s["id"]]),
                        "corrente": False}
            for s in graph["sessioni_semplificate"]
        })
        nodes.update({
            w["nodo"]: {"titolo": f"Lavorazione #{w['id']}", "sottotitolo": w["tipo_codice"],
                        "tipo": "Storico", "url": "", "corrente": False}
            for w in graph["lavorazioni"]
        })
        for sale in graph["vendite"]:
            node_key = sale["nodo"]
            labels[node_key] = (f"Vendita {sale['documento']} · {sale['cliente']}", sale["unita_misura"])
            nodes[node_key] = {
                "titolo": f"Vendita {sale['documento']}",
                "sottotitolo": f"Cliente: {sale['cliente']} · {date.fromisoformat(sale['data']).strftime('%d/%m/%Y')}",
                "tipo": "Vendita",
                "url": reverse("ui:sales") if request.user.has_perm("auth.can_manage_sales") else "",
                "corrente": False,
            }
        for edge in graph["legami_materiali"]:
            source, unit_in = labels.get(edge["da"], (edge["da"], ""))
            target, unit_out = labels.get(edge["a"], (edge["a"], ""))
            edge.update(origine=source, destinazione=target, unita_misura=unit_in or unit_out,
                        nodo_origine=nodes.get(edge["da"]), nodo_destinazione=nodes.get(edge["a"]))
        graph["lotto_corrente"] = nodes[f"lotto:{lot.pk}"]
        graph["prelievi_sessione"] = [
            {**edge, "lotto": nodes.get(edge["da"])}
            for edge in graph["legami_materiali"] if edge.get("prelievo_sessione_id")
        ]
        for material in graph["materiali_esterni"]:
            material["scadenza_display"] = (
                date.fromisoformat(material["data_scadenza"]).strftime("%d/%m/%Y")
                if material["data_scadenza"] else ""
            )
        root_node = f"lotto:{lot.pk}"
        relations = {}
        for edge in graph["legami_materiali"]:
            start, end = (edge["a"], edge["da"]) if direction == "MONTE" else (edge["da"], edge["a"])
            relations.setdefault(start, []).append((end, edge))
        levels, frontier, seen = [[dict(nodes[root_node])]], [root_node], {root_node}
        while frontier:
            next_frontier, level = [], []
            for current in frontier:
                for node_key, edge in relations.get(current, []):
                    if node_key in seen or node_key not in nodes:
                        continue
                    seen.add(node_key)
                    next_frontier.append(node_key)
                    item = dict(nodes[node_key])
                    item.update(quantita=edge.get("quantita"), unita_misura=edge.get("unita_misura"),
                                movimenti=edge.get("movimenti_ids", []))
                    level.append(item)
            if not level:
                break
            levels.append(level)
            frontier = next_frontier
        graph["trace_levels"] = list(reversed(levels)) if direction == "MONTE" else levels
    stocks = list(Giacenza.objects.filter(lotto=lot).select_related("ubicazione")) if request.user.has_perm("magazzino.view_giacenza") else []
    current_quantity = sum((stock.quantita for stock in stocks), 0)
    return render(request, "interfaccia/lot.html", {
        "section": "tracciabilita", "lot": lot, "stocks": stocks, "graph": graph,
        "direction": direction, "sales_movements": sales_movements,
        "initial_quantity": initial_quantity, "current_quantity": current_quantity,
        "outgoing_quantity": outgoing_quantity,
    })


@permitted("auth.can_view_genealogy")
def trace_search(request):
    query = request.GET.get("q", "").strip()[:150]
    records = Lotto.objects.select_related("articolo", "fornitore").order_by("-pk")
    if query:
        records = records.filter(
            Q(codice_lotto__icontains=query)
            | Q(articolo__codice__icontains=query)
            | Q(articolo__descrizione__icontains=query)
            | Q(fornitore__ragione_sociale__icontains=query)
        )
    else:
        records = records.none()
    return render(request, "interfaccia/trace_search.html", {
        "section": "tracciabilita", "page": paged(request, records), "q": query,
    })


@permitted("produzione.view_lavorazione")
def production(request):
    query = request.GET.get("q", "").strip()[:150]
    state = request.GET.get("stato", "")
    works = Lavorazione.objects.select_related("tipo_lavorazione", "ciclo_produzione__articolo", "ricetta").order_by("-pk")
    if query:
        works = works.filter(Q(tipo_lavorazione__nome__icontains=query) | Q(ciclo_produzione__articolo__descrizione__icontains=query))
    if state in Lavorazione.Stato.values:
        works = works.filter(stato=state)
    return render(request, "interfaccia/production.html", {"section": "produzione", "page": paged(request, works), "q": query, "state": state, "states": Lavorazione.Stato.choices})


@permitted("produzione.view_lavorazione")
def work_detail(request, pk):
    work = get_object_or_404(Lavorazione.objects.select_related("tipo_lavorazione", "ricetta__articolo", "ciclo_produzione__articolo"), pk=pk)
    if work.tipo_lavorazione.fase_operativa in {"ROBOQBO", "SEMILAVORATO"}:
        from produzione.models import BatchPiano
        batch = BatchPiano.objects.filter(lavorazione=work).first()
        if batch:
            return redirect("ui:azienda_batch", pk=batch.pk)
    elif work.tipo_lavorazione.fase_operativa == "TANK":
        from produzione.models import TankAziendale
        tank = TankAziendale.objects.filter(lavorazione=work).first()
        if tank:
            return redirect("ui:azienda_tank", pk=tank.pk)
    elif work.tipo_lavorazione.fase_operativa == "INVASETTAMENTO":
        from produzione.models import SessioneInvasettamento
        session = SessioneInvasettamento.objects.filter(lavorazione=work).first()
        if session:
            return redirect("ui:azienda_session", pk=session.pk)
    return render(request, "interfaccia/work.html", {"section": "produzione", "work": work,
        "inputs": work.inputs.select_related("lotto__articolo", "riga_ricetta", "requisito_input"),
        "outputs": work.outputs.select_related("lotto__articolo"),
        "controls": work.controlli_qualita.select_related("controllo_richiesto__parametro_controllo"),
        "requirements": work.tipo_lavorazione.controlli_richiesti.select_related("parametro_controllo"),
        "units": work.unita_generate.select_related("lotto", "risorsa_produttiva"),
        "participations": work.partecipazioni_unita.select_related("unita_lavorazione"),
        "resources": work.risorse_utilizzate.select_related("risorsa_produttiva")})


@permitted("qualita.view_nonconformita")
def quality(request):
    query = request.GET.get("q", "").strip()[:150]
    cases = NonConformita.objects.select_related("lotto", "lavorazione").order_by("-numero")
    production_cases = NonConformitaSessioneSemplificata.objects.select_related(
        "sessione__lotto_prodotto", "sessione__ricetta__articolo"
    )
    if query:
        cases = cases.filter(Q(descrizione__icontains=query) | Q(lotto__codice_lotto__icontains=query))
        production_cases = production_cases.filter(
            Q(descrizione__icontains=query) | Q(sessione__lotto_codice__icontains=query)
            | Q(sessione__ricetta__articolo__descrizione__icontains=query)
        )
    rows = [{
        "numero": str(case.numero), "data": case.data_ora_apertura,
        "descrizione": case.descrizione, "origine": case.get_tipo_display(),
        "lotto": case.lotto.codice_lotto if case.lotto_id else "",
        "stato": case.stato, "stato_label": case.get_stato_display(),
        "url": reverse("ui:case", args=[case.pk]),
    } for case in cases]
    rows.extend({
        "numero": f"P-{case.pk}", "data": case.aperta_il,
        "descrizione": case.descrizione,
        "origine": f"Produzione · {case.sessione.get_tipo_display()}",
        "lotto": case.sessione.lotto_prodotto.codice_lotto if case.sessione.lotto_prodotto_id else case.sessione.lotto_codice,
        "stato": case.stato, "stato_label": case.get_stato_display(),
        "url": reverse("ui:simple_case", args=[case.pk]),
    } for case in production_cases)
    rows.sort(key=lambda row: row["data"], reverse=True)
    return render(request, "interfaccia/quality.html", {
        "section": "qualita", "page": paged(request, rows), "q": query,
    })


@permitted("qualita.view_nonconformita")
def case_detail(request, pk):
    case = get_object_or_404(NonConformita.objects.select_related("lotto", "lavorazione", "aperta_da"), pk=pk)
    return render(request, "interfaccia/case.html", {"section": "qualita", "case": case,
        "actions": case.azioni.select_related("movimento", "eseguita_da"), "verifications": case.verifiche.all()})


@permitted("qualita.view_nonconformita")
def simple_case_detail(request, pk):
    case = get_object_or_404(
        NonConformitaSessioneSemplificata.objects.select_related(
            "sessione__ricetta__articolo", "sessione__lotto_prodotto",
            "controllo", "aperta_da", "presa_in_carico_da", "chiusa_da",
        ), pk=pk,
    )
    return render(request, "interfaccia/simple_case.html", {
        "section": "qualita", "case": case,
        "actions": case.azioni.select_related("registrata_da", "movimento__lotto__articolo", "movimento__ubicazione_origine"),
        "verifications": case.verifiche.select_related("verificata_da"),
    })


@permitted("anagrafiche.view_articolo")
def articles(request):
    records = Articolo.objects.select_related("categoria").order_by("categoria__nome", "codice")
    query = request.GET.get("q", "").strip()[:150]
    if query:
        records = records.filter(Q(codice__icontains=query) | Q(descrizione__icontains=query))
    return render(request, "interfaccia/articles.html", {"section": "anagrafiche", "catalog_tab": "articoli", "articles": records, "q": query})


OPERATIONS = {
    "ricevimento": ("Ricevi merce", "can_receive_goods", "magazzino"),
    "trasferimento": ("Trasferisci merce", "can_transfer_stock", "magazzino"),
    "rettifica": ("Rettifica inventariale", "can_adjust_inventory", "magazzino"),
    "scarico": ("Scarico materiale", "can_adjust_inventory", "magazzino"),
    "nc_apri": ("Apri non conformità", "can_open_nc", "qualita"),
    "nc_gestisci": ("Prendi in gestione", "can_manage_nc", "qualita"),
    "nc_azione": ("Registra azione correttiva", "can_manage_nc", "qualita"),
    "nc_verifica": ("Verifica efficacia", "can_verify_nc", "qualita"),
    "nc_chiudi": ("Chiudi non conformità", "can_close_nc", "qualita"),
}
WORK_OPERATIONS = set()
CASE_OPERATIONS = {"nc_gestisci", "nc_azione", "nc_verifica", "nc_chiudi"}


def execute(request, op, d, work=None, case=None):
    actor, note = request.user, d.get("note", "")
    if op == "ricevimento":
        ReceivingService.receive(actor=actor, articolo=d["articolo"], fornitore=d["fornitore"], codice_lotto=d["codice_lotto"],
            quantita_ricevuta=d["quantita"], data_scadenza=d["data_scadenza"], numero_ddt=d["numero_ddt"],
            destinazioni=[Allocation(position(d, "destinazione"), d["quantita"])], note=note)
    elif op in {"rettifica", "trasferimento", "scarico"}:
        if op in {"trasferimento", "scarico"}:
            stock = d["stock"]
            lot = stock.lotto
            origin = Position(stock.ubicazione_id, stock.scaffale, stock.piano)
            target = position(d, "destinazione") if op == "trasferimento" else None
        else:
            stock = d["stock"]
            lot = stock.lotto
            selected = Position(stock.ubicazione_id, stock.scaffale, stock.piano)
            origin, target = (selected, None) if d["verso"] == "uscita" else (None, selected)
        movement_type = {"rettifica": "RETTIFICA", "trasferimento": "TRASFERIMENTO", "scarico": "SCARICO"}[op]
        MovementService.register(actor=actor, lotto=lot, tipo=movement_type,
            quantita=d["quantita"], origine=origin, destinazione=target, note=note)
    elif op == "pianifica":
        cycle = ProductionCycleService.create(actor=actor, articolo=d["articolo"], note=note)
        WorkExecutionService.plan_batches(actor=actor, ciclo=cycle, tipo_lavorazione=d["tipo_lavorazione"], ricetta=d["ricetta"], numero_batch=d["numero_batch"])
    elif op in {"avvia", "completa", "interrompi", "annulla"}:
        method = {"avvia": "start", "completa": "complete", "interrompi": "interrupt", "annulla": "cancel"}[op]
        kwargs = {"note": note} if op in {"interrompi", "annulla"} else {}
        getattr(WorkExecutionService, method)(actor=actor, lavorazione=work, **kwargs)
    elif op == "output":
        OutputService.register(actor=actor, lavorazione=work, requisito_output=d["requisito_output"], articolo=d["articolo"],
            lotto=d["lotto"], quantita=d["quantita"], data_scadenza=d["data_scadenza"], destinazioni=[Allocation(position(d, "destinazione"), d["quantita"])], note=note)
    elif op == "prepara_lotto":
        OutputService.prepare_lot(actor=actor, lavorazione=work, requisito_output=d["requisito_output"], articolo=d["articolo"], data_scadenza=d["data_scadenza"], note=note)
    elif op == "risorsa":
        ResourceService.assign(actor=actor, lavorazione=work, risorsa_produttiva=d["risorsa_produttiva"], note=note)
    elif op == "unita":
        WorkUnitService.create(actor=actor, lavorazione_origine=work, lotto=d["lotto"], risorsa_produttiva=d["risorsa_produttiva"], codice=d["codice"], quantita=d["quantita"], note=note)
    elif op == "partecipa":
        WorkUnitService.participate(actor=actor, unita_lavorazione=d["unita_lavorazione"], lavorazione=work, note=note)
    elif op == "chiudi_unita":
        WorkUnitService.close(actor=actor, unita_lavorazione=d["unita_lavorazione"])
    elif op == "chiudi_ciclo":
        ProductionCycleService.complete(actor=actor, ciclo=work.ciclo_produzione)
    elif op == "input":
        InputService.register(actor=actor, lavorazione=work, requisito_input=d["requisito_input"], lotto=d["lotto"],
            quantita=d["quantita"], origini=[Allocation(position(d, "origine"), d["quantita"])], note=note)
    elif op == "controllo":
        QualityService.record(actor=actor, lavorazione=work, controllo_richiesto=d["controllo_richiesto"], valore=d["valore"], conforme=d["conforme"], note=note)
    elif op == "nc_apri":
        NonConformityService.open(actor=actor, tipo=d["tipo"], descrizione=d["descrizione"], lotto=d["lotto"], lavorazione=d["lavorazione"], note=note)
    elif op == "nc_gestisci":
        NonConformityService.take_charge(actor=actor, non_conformita=case, note=note)
    elif op == "nc_chiudi":
        NonConformityService.close(actor=actor, non_conformita=case, note=note)
    elif op == "nc_verifica":
        NonConformityService.verify(actor=actor, non_conformita=case, esito=d["esito"], descrizione=d["descrizione"], note=note)
    elif op == "nc_azione":
        stock = d.get("origine_stock")
        NonConformityService.action(actor=actor, non_conformita=case, tipo_azione=d["tipo_azione"], descrizione=d["descrizione"],
            lotto=d["lotto"], quantita=d["quantita"],
            origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano) if stock else None,
            destinazione=position(d, "destinazione"), lavorazione=None, note=note)


@login_required
@require_http_methods(["GET", "POST"])
def operation(request, op, pk=None):
    if op not in OPERATIONS:
        raise Http404
    title, permission, section = OPERATIONS[op]
    if not request.user.has_perm("auth." + permission):
        raise PermissionDenied
    work = get_object_or_404(Lavorazione, pk=pk) if op in WORK_OPERATIONS else None
    case = get_object_or_404(NonConformita, pk=pk) if op in CASE_OPERATIONS else None
    if pk is not None and work is None and case is None:
        raise Http404
    back = reverse("ui:work", args=[work.pk]) if work else reverse("ui:case", args=[case.pk]) if case else reverse("ui:" + section)
    initial = {"invio": token_for(request)}
    if op in {"trasferimento", "scarico"} and request.method == "GET":
        initial["articolo"] = request.GET.get("articolo", "")
    if op == "rettifica" and request.method == "GET":
        initial["ubicazione"] = request.GET.get("ubicazione", "")
        initial["scaffale"] = request.GET.get("scaffale", "")
    if op == "nc_apri" and request.method == "GET":
        initial["lotto"] = request.GET.get("lotto", "")
    form = OperationForm(request.POST if request.method == "POST" else None, operation=op, work=work, case=case,
        initial=initial)
    if request.method == "POST" and form.is_valid():
        try:
            created = submit_once(request, form.cleaned_data["invio"], lambda: execute(request, op, form.cleaned_data, work, case))
        except ValidationError as exc:
            error_form(form, exc)
        else:
            messages.success(request, "Operazione registrata." if created else "Questo modulo è già stato registrato. Nessuna operazione duplicata.")
            return redirect(back)
    return render(request, "interfaccia/form.html", {
        "title": title, "section": section, "form": form, "back": back,
        "work": work, "case": case,
        "warehouse_tab": op if op in {"trasferimento", "rettifica", "scarico"} else "",
    })


@permitted("auth.can_record_production_consumption")
@require_http_methods(["GET", "POST"])
def ingredients(request, pk):
    work = get_object_or_404(Lavorazione, pk=pk)
    if not work.ricetta_id:
        raise Http404
    initial, warning = [], ""
    if request.method == "GET":
        try:
            proposal = RecipeInputService.propose(actor=request.user, lavorazione=work)
            for s in proposal.selections:
                a = s.origini[0]
                initial.append({"riga_ricetta": s.riga_ricetta, "lotto": s.lotto, "quantita": s.quantita,
                    "origine": a.posizione.ubicazione_id, "origine_scaffale": a.posizione.scaffale, "origine_piano": a.posizione.piano})
            if not proposal.completa:
                warning = "Disponibilità insufficiente per il fabbisogno completo. La proposta è parziale: controlla tutte le righe e le quantità prima di confermare."
        except ValidationError as exc:
            warning = " · ".join(exc.messages)
    FormSet = forms.formset_factory(IngredientForm, extra=2, can_delete=True, max_num=100, validate_max=True, absolute_max=100)
    formset = FormSet(request.POST if request.method == "POST" else None, initial=initial, form_kwargs={"work": work})
    token = request.POST.get("invio", "") if request.method == "POST" else token_for(request)
    error = ""
    if request.method == "POST" and formset.is_valid():
        try:
            selections = [InputSelection(d["lotto"], d["quantita"], [Allocation(position(d, "origine"), d["quantita"])], riga_ricetta=d["riga_ricetta"])
                for d in formset.cleaned_data if d and not d.get("DELETE")]
            created = submit_once(request, token, lambda: RecipeInputService.confirm(actor=request.user, lavorazione=work, selections=selections))
        except ValidationError as exc:
            error = " · ".join(exc.messages)
        else:
            messages.success(request, "Ingredienti registrati." if created else "Prelievi già registrati con questo modulo.")
            return redirect("ui:work", pk=pk)
    return render(request, "interfaccia/ingredients.html", {"section": "produzione", "work": work, "formset": formset,
        "token": token, "warning": warning, "error": error, "recipe_rows": work.ricetta.righe.select_related("articolo", "categoria_articolo")})


def forbidden(request, exception=None):
    return render(request, "interfaccia/403.html", status=403)
