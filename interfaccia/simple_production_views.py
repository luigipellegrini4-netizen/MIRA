from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.core.exceptions import ValidationError
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from django.utils import timezone
from datetime import datetime

from magazzino.models import Movimento
from magazzino.selectors import StockProposalService
from magazzino.services import MovementService, Position
from produzione.models import (NonConformitaSessioneSemplificata,
                               PrelievoSessioneSemplificata,
                               SessioneProduzioneSemplificata)
from produzione.services import ProduzioneSemplificataService
from .simple_production_forms import (AdditionalPickingForm, BatchControlFormSet, ControlForm, NCForm, OpenFillingForm, OpenRoboQboForm,
    OpenSemiFinishedForm, PickingForm, SemiFinishedPickingFormSet, SemiFinishedSummaryForm, SummaryForm,
    SimpleNCActionForm, SimpleNCCloseForm, SimpleNCTakeChargeForm, SimpleNCVerificationForm)
from .views import permitted


@permitted("produzione.view_sessioneproduzionesemplificata")
def sessions(request):
    rows = list(SessioneProduzioneSemplificata.objects.select_related(
        "postazione__risorsa", "ricetta__articolo", "lotto_origine"
    ))
    definitions = [
        ("SEMILAVORATO", "Semilavorati", "SLV", "Prelievo materie prime e produzione del semilavorato.", "ui:simple_open_semifinished"),
        ("ROBOQBO", "RoboQbo", "RBQB", "Batch, controlli termici, tank, °Brix e pH.", "ui:simple_open_roboqbo"),
        ("INVASETTAMENTO", "Invasettamento", "INV", "Carrelli, pastorizzazione, shock termico e vuoto.", "ui:simple_open_filling"),
    ]
    groups = []
    for code, name, marker, description, new_url in definitions:
        group_rows = [row for row in rows if row.tipo == code]
        groups.append({
            "code": code, "name": name, "marker": marker, "description": description,
            "new_url": new_url, "sessions": group_rows, "count": len(group_rows),
            "active_count": sum(row.stato in {"PIANIFICATA", "APERTA"} for row in group_rows),
        })
    return render(request, "interfaccia/semplice/sessions.html", {
        "section": "produzione-semplice", "production_groups": groups,
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


@permitted("produzione.view_sessioneproduzionesemplificata")
def session(request, pk):
    obj = get_object_or_404(SessioneProduzioneSemplificata.objects.select_related("postazione__risorsa", "ricetta__articolo", "lotto_origine"), pk=pk)
    controls = list(obj.controlli.prefetch_related("associazioni_batch__batch"))
    ncs = list(obj.non_conformita_semplificate.select_related("controllo"))
    nonconforming_control_ids = {control.pk for control in controls if not control.conforme}
    nc_count = len(nonconforming_control_ids) + sum(
        1 for nc in ncs if not nc.controllo_id or nc.controllo_id not in nonconforming_control_ids
    )
    forecast = []
    if obj.tipo in {"SEMILAVORATO", "ROBOQBO"}:
        forecast = [(row.articolo, row.quantita * obj.batch_previsti)
                    for row in obj.ricetta.righe.select_related("articolo")]
    batch_formset = None
    displayed_controls = controls
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
        displayed_controls = [
            control for control in controls
            if control.tipo != "BATCH" or control.numero > obj.numero_batch_previsti
        ]
    return render(request, "interfaccia/semplice/session.html", {"section": "produzione-semplice", "session": obj,
        "controls": controls, "displayed_controls": displayed_controls, "batch_formset": batch_formset,
        "picks": obj.prelievi.select_related("lotto__articolo", "movimento__ubicazione_origine"),
        "ncs": ncs, "nc_count": nc_count, "forecast": forecast,
        "input_totals": obj.quantita_iniziale_per_unita})


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


@permitted("auth.can_record_production_consumption")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def picking(request, pk):
    obj = get_object_or_404(SessioneProduzioneSemplificata, pk=pk, tipo__in=["ROBOQBO", "SEMILAVORATO"], stato="APERTA")
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
    obj = get_object_or_404(SessioneProduzioneSemplificata, pk=pk, stato="APERTA")
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
    def close_filling(data):
        data.pop("vasetti_articolo")
        data.pop("capsule_articolo")
        return ProduzioneSemplificataService.chiudi_invasettamento(actor=request.user, sessione=obj, **data)
    return _form_view(request, SummaryForm, close_filling, "Chiudi invasettamento e calcola resa")


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
