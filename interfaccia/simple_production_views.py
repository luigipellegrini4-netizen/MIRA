from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction, connection
from django.db.models import Sum, F
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from datetime import datetime
from decimal import Decimal

from anagrafiche.models import Articolo
from magazzino.models import Giacenza, Movimento
from magazzino.selectors import StockProposalService
from magazzino.selectors.stock_proposals import order_stocks
from magazzino.services import MovementService, Position
from produzione.models import (NonConformitaSessioneSemplificata,
                               PrelievoSessioneSemplificata,
                               SessioneProduzioneSemplificata)
from produzione.services import ProduzioneSemplificataService
from .simple_production_forms import (AdditionalPickingForm, BatchControlFormSet, ControlForm, NCForm, OpenFillingForm, OpenLabelingForm, OpenPackagingForm, OpenRoboQboForm,
    OpenSemiFinishedForm, PickingForm, SemiFinishedPickingFormSet, SemiFinishedSummaryForm, SummaryForm,
    LabelingSummaryForm, PackagingSummaryForm, SimpleNCActionForm, SimpleNCCloseForm, SimpleNCTakeChargeForm, SimpleNCVerificationForm,
    article_ids_for_category)
from .views import permitted


@permitted("produzione.view_sessioneproduzionesemplificata")
def sessions(request):
    rows = list(SessioneProduzioneSemplificata.objects.select_related(
        "postazione__risorsa", "ricetta__articolo", "lotto_origine"
    ))
    definitions = [
        (1, "SEMILAVORATO", "Semilavorati", "SLV", "Prelievo materie prime e produzione del semilavorato.", "ui:simple_open_semifinished"),
        (2, "ROBOQBO", "RoboQbo", "RBQB", "Batch, controlli termici, tank, °Brix e pH.", "ui:simple_open_roboqbo"),
        (3, "INVASETTAMENTO", "Invasettamento", "INV", "Carrelli, pastorizzazione, shock termico e vuoto.", "ui:simple_open_filling"),
        (4, "ETICHETTATURA", "Etichettatura", "PF", "Dal lotto invasettato al prodotto finito etichettato.", "ui:simple_open_labeling"),
        (5, "CONFEZIONAMENTO", "Confezionamento", "BOX", "Confezionamento del prodotto finito senza cambiare lotto.", "ui:simple_open_packaging"),
    ]
    groups = []
    for phase, code, name, marker, description, new_url in definitions:
        group_rows = [row for row in rows if row.tipo == code]
        groups.append({
            "phase": phase, "code": code, "name": name, "marker": marker, "description": description,
            "new_url": new_url, "sessions": group_rows, "count": len(group_rows),
            "active_count": sum(row.stato in {"PIANIFICATA", "APERTA"} for row in group_rows),
            "closed_count": sum(row.stato == "CHIUSA" for row in group_rows),
        })
    return render(request, "interfaccia/semplice/sessions.html", {
        "section": "produzione-semplice", "production_groups": groups,
        "production_total": len(rows),
        "production_active": sum(row.stato in {"PIANIFICATA", "APERTA"} for row in rows),
        "production_closed": sum(row.stato == "CHIUSA" for row in rows),
    })


def _form_view(request, form_class, execute, title, **form_kwargs):
    form = form_class(request.POST if request.method == "POST" else None, **form_kwargs)
    if request.method == "POST" and form.is_valid():
        try:
            result = execute(form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Operazione registrata.")
            return redirect("ui:simple_session", pk=result.pk if isinstance(result, SessioneProduzioneSemplificata) else result.sessione_id)
    return render(request, "interfaccia/semplice/form.html", {"section": "produzione-semplice", "title": title, "form": form})


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def open_roboqbo(request):
    return _form_view(request, OpenRoboQboForm, lambda d: ProduzioneSemplificataService.apri_roboqbo(actor=request.user, **d), "Apri lavorazione RoboQbo")


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def open_semifinished(request):
    return _form_view(request, OpenSemiFinishedForm, lambda d: ProduzioneSemplificataService.apri_semilavorato(actor=request.user, **d), "Apri produzione semilavorato")


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def open_filling(request):
    return _form_view(request, OpenFillingForm, lambda d: ProduzioneSemplificataService.apri_invasettamento(actor=request.user, **d), "Apri invasettamento")


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def open_labeling(request):
    return _form_view(request, OpenLabelingForm, lambda d: ProduzioneSemplificataService.apri_etichettatura(actor=request.user, **d), "Apri etichettatura")


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def open_packaging(request):
    return _form_view(request, OpenPackagingForm, lambda d: ProduzioneSemplificataService.apri_confezionamento(actor=request.user, **d), "Apri confezionamento")


def _available_stock_options(article):
    """Giacenze prelevabili nello stesso ordine usato dalla proposta FIFO/FEFO."""
    from qualita.nc_selectors import blocked_quantity, quarantine_balances

    stocks = Giacenza.objects.filter(
        lotto__articolo=article, quantita__gt=0, ubicazione__attiva=True,
    ).select_related("lotto__articolo", "ubicazione")
    stocks = order_stocks(stocks, article)
    held_by_lot = {}
    rows = []
    for stock in stocks:
        if stock.lotto_id not in held_by_lot:
            held_by_lot[stock.lotto_id] = quarantine_balances(lotto=stock.lotto_id)
        blocked = blocked_quantity(
            held_by_lot[stock.lotto_id], lotto_id=stock.lotto_id,
            ubicazione_id=stock.ubicazione_id, scaffale=stock.scaffale, piano=stock.piano,
        )
        available = max(Decimal("0"), stock.quantita - blocked)
        if not available:
            continue
        rows.append({
            "stock": stock,
            "disponibile": available,
            "data_scadenza": stock.lotto.data_scadenza,
            "data_carico": stock.primo_ingresso,
        })
    return rows


@permitted("produzione.view_sessioneproduzionesemplificata")
def session(request, pk):
    obj = get_object_or_404(SessioneProduzioneSemplificata.objects.select_related("postazione__risorsa", "ricetta__articolo", "lotto_origine"), pk=pk)
    controls = list(obj.controlli.prefetch_related("associazioni_batch__batch"))
    ncs = list(obj.non_conformita_semplificate.select_related("controllo"))
    nonconforming_control_ids = {control.pk for control in controls if control.esito == "NC"}
    incomplete_count = sum(not control.completo for control in controls)
    if obj.tipo == "ROBOQBO":
        recorded_batches = {control.numero for control in controls if control.tipo == "BATCH"}
        incomplete_count += len(set(range(1, obj.numero_batch_previsti + 1)) - recorded_batches)
    nc_count = len(nonconforming_control_ids) + sum(
        1 for nc in ncs if not nc.controllo_id or nc.controllo_id not in nonconforming_control_ids
    )
    forecast = []
    if obj.tipo in {"SEMILAVORATO", "ROBOQBO"}:
        forecast = [(row.articolo, row.quantita * obj.batch_previsti)
                    for row in obj.ricetta.righe.select_related("articolo")]
    withdrawal_plan = []
    moca_articles = []
    selected_moca_ids = []
    moca_stock_groups = []
    can_view_stock = request.user.has_perm("magazzino.view_giacenza")
    if obj.stato == "PIANIFICATA" and can_view_stock:
        if obj.tipo in {"SEMILAVORATO", "ROBOQBO"} and not obj.prelievo_ricetta_registrato:
            totals = {}
            for recipe_row in obj.ricetta.righe.select_related("articolo").order_by("pk"):
                if not recipe_row.articolo_id:
                    continue
                totals.setdefault(recipe_row.articolo_id, [recipe_row.articolo, Decimal("0")])
                totals[recipe_row.articolo_id][1] += recipe_row.quantita * obj.batch_previsti
            for article, required in totals.values():
                proposal = StockProposalService.propose(actor=request.user, articolo=article, quantita=required)
                suggested = {line.giacenza_id: line.quantita for line in proposal.righe}
                options = _available_stock_options(article)
                for option in options:
                    option["proposta"] = suggested.get(option["stock"].pk, Decimal("0"))
                withdrawal_plan.append({
                    "articolo": article, "richiesta": required, "criterio": proposal.criterio,
                    "mancante": proposal.mancante, "opzioni": options,
                })

        moca_articles = list(
            Articolo.objects.filter(
                pk__in=article_ids_for_category("MOCA"), attivo=True,
                lotti__giacenze__quantita__gt=0, lotti__giacenze__ubicazione__attiva=True,
            ).distinct().order_by("descrizione", "codice")
        )
        valid_moca_ids = {article.pk for article in moca_articles}
        for raw_id in request.GET.getlist("moca"):
            try:
                article_id = int(raw_id)
            except (TypeError, ValueError):
                continue
            if article_id in valid_moca_ids and article_id not in selected_moca_ids:
                selected_moca_ids.append(article_id)
        selected_by_id = {article.pk: article for article in moca_articles}
        for article_id in selected_moca_ids:
            article = selected_by_id[article_id]
            moca_stock_groups.append({
                "articolo": article,
                "criterio": article.criterio_rotazione,
                "opzioni": _available_stock_options(article),
            })
    batch_formset = None
    displayed_controls = controls
    labeling_remaining = None
    if obj.tipo == "ETICHETTATURA" and obj.lotto_origine.lotto_prodotto_id:
        labeling_remaining = obj.lotto_origine.lotto_prodotto.giacenze.filter(
            quantita__gt=0
        ).aggregate(totale=Sum("quantita"))["totale"] or 0
    if obj.tipo == "ROBOQBO" and obj.stato == "APERTA":
        existing = {control.numero: control for control in controls if control.tipo == "BATCH"}
        initial = []
        for number in range(1, obj.numero_batch_previsti + 1):
            control = existing.get(number)
            initial.append({
                "numero": number,
                "inizio": timezone.localtime(control.inizio).time() if control and control.inizio else None,
                "fine": timezone.localtime(control.fine).time() if control and control.fine else None,
                "esito_tracciato_termico": control.esito_tracciato_termico if control else "",
            })
        batch_formset = BatchControlFormSet(initial=initial, prefix="batch")
        for form, number in zip(batch_formset.forms, range(1, obj.numero_batch_previsti + 1)):
            form.control_outcome = existing[number].esito if number in existing else "Incompleto"
        displayed_controls = [
            control for control in controls
            if control.tipo != "BATCH" or control.numero > obj.numero_batch_previsti
        ]
    return render(request, "interfaccia/semplice/session.html", {"section": "produzione-semplice", "session": obj,
        "controls": controls, "displayed_controls": displayed_controls, "batch_formset": batch_formset,
        "picks": obj.prelievi.select_related("lotto__articolo", "movimento__ubicazione_origine"),
        "ncs": ncs, "nc_count": nc_count, "incomplete_count": incomplete_count, "forecast": forecast,
        "input_totals": obj.quantita_iniziale_per_unita,
        "labeling_remaining": labeling_remaining,
        "withdrawal_plan": withdrawal_plan, "can_view_stock": can_view_stock,
        "moca_articles": moca_articles, "selected_moca_ids": selected_moca_ids,
        "moca_stock_groups": moca_stock_groups})


@permitted("auth.can_execute_production")
@require_http_methods(["POST"])
def batch_controls(request, pk):
    obj = get_object_or_404(SessioneProduzioneSemplificata, pk=pk, tipo="ROBOQBO", stato="APERTA")
    formset = BatchControlFormSet(request.POST, prefix="batch")
    if formset.is_valid():
        try:
            ProduzioneSemplificataService.registra_tabella_batch(
                actor=request.user, sessione=obj, righe=formset.cleaned_data
            )
        except ValidationError as exc:
            messages.error(request, " · ".join(exc.messages))
        else:
            messages.success(request, "Controlli dei batch salvati.")
    else:
        messages.error(request, "Controllare orari ed esiti nella tabella dei batch.")
    return redirect("ui:simple_session", pk=obj.pk)


def _picking_sessions(request, pk):
    sessions = SessioneProduzioneSemplificata.objects.all()
    if request.method == "POST":
        # SQLite non dispone di lock di riga: acquisire il lock di scrittura
        # prima di leggere stato e conferme evita due letture dello stesso stato iniziale.
        if connection.vendor == "sqlite":
            sessions.filter(pk=pk).update(note=F("note"))
        return sessions.select_for_update()
    return sessions


@permitted("auth.can_record_production_consumption")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def picking(request, pk):
    obj = get_object_or_404(_picking_sessions(request, pk), pk=pk, tipo__in=["ROBOQBO", "SEMILAVORATO"], stato="APERTA")
    if obj.tipo in {"SEMILAVORATO", "ROBOQBO"}:
        requirements = []
        initial = []
        proposal_complete = True
        totals = {}
        for recipe_row in obj.ricetta.righe.select_related("articolo").order_by("pk"):
            if not recipe_row.articolo_id:
                raise ValidationError("La ricetta deve indicare un articolo preciso per ogni ingrediente.")
            if recipe_row.articolo_id not in totals:
                totals[recipe_row.articolo_id] = [recipe_row.articolo, 0]
            totals[recipe_row.articolo_id][1] += recipe_row.quantita * obj.batch_previsti
        for article, required in totals.values():
            proposal = StockProposalService.propose(
                actor=request.user, articolo=article, quantita=required
            )
            requirements.append({
                "articolo": article, "quantita": required,
                "criterio": proposal.criterio, "mancante": proposal.mancante,
            })
            proposal_complete = proposal_complete and proposal.mancante == 0
            initial.append({
                "articolo": article.pk,
                "giacenza": [line.giacenza_id for line in proposal.righe],
                "quantita_kg": required,
            })

        already_recorded = obj.prelievi.filter(da_ricetta=True).exists()
        formset = SemiFinishedPickingFormSet(request.POST if request.method == "POST" else None, initial=initial)
        error = ""
        if request.method == "POST" and not already_recorded and formset.is_valid():
            active_rows = formset.cleaned_data
            expected_articles = {row["articolo"].pk for row in requirements}
            submitted_articles = {row["articolo"].pk for row in active_rows}
            if submitted_articles != expected_articles:
                error = "Confermare almeno un prelievo per ogni ingrediente della ricetta."
            if not error:
                try:
                    with transaction.atomic():
                        for data in active_rows:
                            remaining = data["quantita_kg"]
                            for stock in data["giacenza"]:
                                if remaining <= 0:
                                    break
                                used = min(stock.quantita, remaining)
                                movement = MovementService.register(
                                    actor=request.user, lotto=stock.lotto, tipo=Movimento.Tipo.CONSUMO,
                                    quantita=used,
                                    origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano),
                                    note=data.get("note", ""),
                                )
                                row = PrelievoSessioneSemplificata(
                                    sessione=obj, lotto=stock.lotto, movimento=movement,
                                    quantita_kg=used, numero_batch=None,
                                    da_ricetta=True, registrato_da=request.user, note=data.get("note", ""),
                                )
                                row.full_clean()
                                row.save()
                                remaining -= used
                            if remaining > 0:
                                raise ValidationError("Disponibilità cambiata: aggiornare la selezione dei lotti.")
                except ValidationError as exc:
                    error = " · ".join(exc.messages)
                else:
                    messages.success(request, "Prelievi della ricetta registrati.")
                    return redirect("ui:simple_session", pk=obj.pk)
        return render(request, "interfaccia/semplice/picking.html", {
            "section": "produzione-semplice", "session": obj, "requirements": requirements,
            "formset": formset, "proposal_complete": proposal_complete,
            "already_recorded": already_recorded, "error": error,
        })

    def execute(d):
        stock = d.pop("giacenza")
        movement = MovementService.register(actor=request.user, lotto=stock.lotto, tipo=Movimento.Tipo.CONSUMO,
            quantita=d["quantita_kg"], origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano), note=d.get("note", ""))
        row = PrelievoSessioneSemplificata(sessione=obj, lotto=stock.lotto, movimento=movement, registrato_da=request.user, **d)
        row.full_clean(); row.save(); return row
    return _form_view(request, PickingForm, execute, "Registra prelievo", session=obj)


@permitted("auth.can_record_production_consumption")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def additional_picking(request, pk):
    obj = get_object_or_404(_picking_sessions(request, pk), pk=pk, stato="APERTA")
    if obj.tipo in {"SEMILAVORATO", "ROBOQBO"} and not obj.prelievo_ricetta_registrato:
        messages.warning(request, "Confermare prima il prelievo proposto dalla ricetta.")
        return redirect("ui:simple_picking", pk=obj.pk)

    def execute(data):
        stock = data.pop("giacenza")
        amount = data.pop("quantita")
        note = data.get("note", "")
        movement = MovementService.register(
            actor=request.user, lotto=stock.lotto, tipo=Movimento.Tipo.CONSUMO,
            quantita=amount, origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano),
            note=note,
        )
        row = PrelievoSessioneSemplificata(
            sessione=obj, lotto=stock.lotto, movimento=movement, quantita_kg=amount,
            numero_batch=None, da_ricetta=False, registrato_da=request.user, note=note,
        )
        row.full_clean()
        row.save()
        return row

    return _form_view(request, AdditionalPickingForm, execute, "Registra un altro prelievo")


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def control(request, pk):
    obj = get_object_or_404(SessioneProduzioneSemplificata, pk=pk, stato="APERTA")
    def execute(data):
        for field in ("inizio", "fine"):
            if data.get(field):
                data[field] = timezone.make_aware(datetime.combine(timezone.localdate(), data[field]))
        return ProduzioneSemplificataService.registra_controllo(actor=request.user, sessione=obj, **data)
    return _form_view(request, ControlForm, execute, "Registra controllo", session=obj)


@permitted("auth.can_open_nc")
@require_http_methods(["GET", "POST"])
def nc(request, pk):
    obj = get_object_or_404(SessioneProduzioneSemplificata, pk=pk)
    return _form_view(request, NCForm, lambda d: ProduzioneSemplificataService.segnala_nc(actor=request.user, sessione=obj, **d), "Registra non conformità", session=obj)


@login_required
@require_http_methods(["GET", "POST"])
def manage_nc(request, pk, action):
    configurations = {
        "prendi-in-carico": ("auth.can_manage_nc", "Prendi in gestione", SimpleNCTakeChargeForm, ProduzioneSemplificataService.prendi_in_carico_nc),
        "azione": ("auth.can_manage_nc", "Registra azione", SimpleNCActionForm, ProduzioneSemplificataService.registra_azione_nc),
        "verifica": ("auth.can_verify_nc", "Verifica efficacia", SimpleNCVerificationForm, ProduzioneSemplificataService.verifica_nc),
        "chiudi": ("auth.can_close_nc", "Chiudi non conformità", SimpleNCCloseForm, ProduzioneSemplificataService.chiudi_nc),
    }
    if action not in configurations:
        raise ValidationError("Operazione NC non riconosciuta.")
    permission, title, form_class, service = configurations[action]
    if not request.user.has_perm(permission):
        raise PermissionDenied
    case = get_object_or_404(NonConformitaSessioneSemplificata, pk=pk)
    form_kwargs = {"case": case} if action == "azione" else {}
    form = form_class(request.POST if request.method == "POST" else None, **form_kwargs)
    if request.method == "POST" and form.is_valid():
        try:
            service(actor=request.user, non_conformita=case, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Gestione della non conformità aggiornata.")
            return redirect("ui:simple_case", pk=case.pk)
    return render(request, "interfaccia/simple_case_operation.html", {
        "section": "qualita", "case": case, "title": title, "form": form,
    })


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def close(request, pk):
    obj = get_object_or_404(SessioneProduzioneSemplificata, pk=pk, stato="APERTA")
    if obj.tipo == "SEMILAVORATO":
        def close_semi(d):
            location = d.pop("destinazione")
            d.pop("moca_articolo")
            return ProduzioneSemplificataService.chiudi_semilavorato(actor=request.user, sessione=obj,
                destinazione=Position(location.pk, d.pop("scaffale"), d.pop("piano")), **d)
        return _form_view(request, SemiFinishedSummaryForm, close_semi, "Chiudi semilavorato")
    if obj.tipo == "ROBOQBO":
        if request.method == "POST":
            ProduzioneSemplificataService.chiudi_roboqbo(actor=request.user, sessione=obj)
            messages.success(request, "Lavorazione RoboQbo chiusa.")
            return redirect("ui:simple_session", pk=obj.pk)
        return render(request, "interfaccia/semplice/confirm.html", {"section": "produzione-semplice", "session": obj})
    if obj.tipo == "INVASETTAMENTO":
        def close_filling(data):
            data.pop("vasetti_articolo")
            data.pop("capsule_articolo")
            location = data.pop("destinazione")
            data["destinazione"] = Position(location.pk, data.pop("scaffale"), data.pop("piano"))
            return ProduzioneSemplificataService.chiudi_invasettamento(actor=request.user, sessione=obj, **data)
        return _form_view(request, SummaryForm, close_filling, "Chiudi invasettamento e calcola resa")
    if obj.tipo == "ETICHETTATURA":
        def close_labeling(data):
            location = data.pop("destinazione")
            data["destinazione"] = Position(location.pk, data.pop("scaffale"), data.pop("piano"))
            return ProduzioneSemplificataService.chiudi_etichettatura(actor=request.user, sessione=obj, **data)
        return _form_view(request, LabelingSummaryForm, close_labeling, "Chiudi etichettatura", session=obj)
    return _form_view(
        request, PackagingSummaryForm,
        lambda data: ProduzioneSemplificataService.chiudi_confezionamento(actor=request.user, sessione=obj, **data),
        "Chiudi confezionamento", session=obj,
    )


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def lifecycle(request, pk, action):
    obj = get_object_or_404(SessioneProduzioneSemplificata, pk=pk, stato="PIANIFICATA")
    if action not in {"avvia", "annulla"}:
        raise ValidationError("Operazione non valida.")
    if request.method == "POST":
        if action == "avvia":
            ProduzioneSemplificataService.avvia(actor=request.user, sessione=obj)
            messages.success(request, "Produzione avviata.")
        else:
            ProduzioneSemplificataService.annulla(actor=request.user, sessione=obj)
            messages.success(request, "Produzione annullata prima dell’avvio.")
        return redirect("ui:simple_session", pk=obj.pk)
    return render(request, "interfaccia/semplice/lifecycle.html", {
        "section": "produzione-semplice", "session": obj, "action": action,
        "title": "Avvia produzione" if action == "avvia" else "Annulla produzione",
    })
