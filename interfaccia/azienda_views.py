from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from magazzino.services import Allocation
from produzione.models import PostazioneLinea, TurnoOperativo, PianoProduzione, BatchPiano
from produzione.services import ShiftService, PickingPlanService, BatchService, InputSelection
from produzione.services.azienda_common import business_mutex, active_shift, recipe_mass, require_control
from qualita.services import QualityService
from .azienda_forms import AziendaActionForm, PianoConfermaForm, PianoIngredientForm, BatchPrelievoForm, ConfiguraLineeForm
from .views import permitted, token_for, submit_once, position, error_form


def can_operate(user, station):
    return user.has_perm("auth.can_execute_production") and TurnoOperativo.objects.filter(
        operatore=user, postazione=station, fine__isnull=True).exists()


def signed_state(request, state):
    return signing.dumps({"user": request.user.pk, "path": request.path, "state": state}, salt="mira-azienda-preview")


def verify_state(request, token, state):
    try:
        value = signing.loads(token, salt="mira-azienda-preview", max_age=7200)
    except signing.BadSignature:
        raise ValidationError("Proposta scaduta o non valida. Riapri la pagina.") from None
    if value != {"user": request.user.pk, "path": request.path, "state": state}:
        raise ValidationError("Il piano o i prelievi sono cambiati. Riapri la pagina e controlla la nuova proposta.")


def plan_state(plan):
    return {"revision": plan.revisioni.order_by("-numero").values_list("pk", flat=True).first(),
        "batches": list(plan.batch.exclude(lavorazione__stato__in=["ANNULLATA", "INTERROTTA"]).filter(
            lavorazione__inputs__isnull=True).order_by("pk").values_list("pk", flat=True))}


def batch_state(revision, chosen):
    return {"revision": revision.pk, "rows": [[row.pk, str(s.quantita)] for row, s in chosen]}


@permitted("auth.can_manage_process_configuration")
@permitted("auth.can_manage_quality_configuration")
@permitted("auth.can_manage_required_controls")
@require_http_methods(["GET", "POST"])
def setup(request):
    form = ConfiguraLineeForm(request.POST if request.method == "POST" else None, initial={"invio": token_for(request)})
    if request.method == "POST" and form.is_valid():
        from produzione.services.azienda_configuration import configure_lines
        try:
            submit_once(request, form.cleaned_data["invio"], lambda: configure_lines(**{
                k: v for k, v in form.cleaned_data.items() if k != "invio"}))
        except ValidationError as exc:
            error_form(form, exc)
        else:
            messages.success(request, "Linee e postazioni configurate. Nessuna produzione avviata.")
            return redirect("ui:azienda_stations")
    return render(request, "interfaccia/azienda/setup.html", {"section": "linee", "form": form})


@permitted("produzione.view_lineaproduttiva")
@require_http_methods(["GET"])
def stations(request):
    stations = list(PostazioneLinea.objects.select_related("linea", "risorsa").order_by("linea__codice", "pk"))
    shifts = {t.postazione_id: t for t in TurnoOperativo.objects.filter(fine__isnull=True).select_related("operatore")}
    for station in stations:
        station.active_shift = shifts.get(station.pk)
    return render(request, "interfaccia/azienda/stations.html", {"section": "linee", "stations": stations})


@permitted("produzione.view_postazionelinea")
@require_http_methods(["GET"])
def station(request, pk):
    from produzione.models import TankAziendale, SessioneInvasettamento
    station = get_object_or_404(PostazioneLinea.objects.select_related("linea", "risorsa"), pk=pk)
    shift = station.turni.filter(fine__isnull=True).select_related("operatore").first()
    return render(request, "interfaccia/azienda/station.html", {"section": "linee", "station": station,
        "shift": shift, "own_shift": bool(shift and shift.operatore_id == request.user.pk),
        "tanks": TankAziendale.objects.filter(linea=station.linea).select_related("lotto", "ricetta").order_by("-pk")[:30],
        "sessions": SessioneInvasettamento.objects.filter(turno__postazione=station).select_related("lotto", "ricetta").order_by("-pk")[:30],
        "plans": station.piani.select_related("ricetta__articolo").order_by("-pk")[:30]})


ACTION_TITLES = {"inizio_turno": "Inizio turno", "fine_turno": "Fine turno", "igienizzazione": "Conferma igienizzazione",
    "piano": "Nuovo piano di produzione", "inizio_batch": "Avvia batch", "controllo_batch": "Controllo RoboQbo",
    "fine_batch": "Concludi batch", "fine_semilavorato": "Concludi semilavorato"}


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def action(request, op, pk):
    if op not in ACTION_TITLES:
        raise Http404
    if op in {"inizio_turno", "piano"}:
        station = get_object_or_404(PostazioneLinea, pk=pk)
        shift = batch = None
    elif op in {"fine_turno", "igienizzazione"}:
        shift = get_object_or_404(TurnoOperativo, pk=pk)
        if shift.operatore_id != request.user.pk:
            raise PermissionDenied
        station, batch = shift.postazione, None
    else:
        batch = get_object_or_404(BatchPiano.objects.select_related("piano__postazione", "lavorazione__tipo_lavorazione"), pk=pk)
        station, shift = batch.piano.postazione, None
        if not can_operate(request.user, station):
            raise PermissionDenied
        expected = "fine_semilavorato" if batch.lavorazione.tipo_lavorazione.fase_operativa == "SEMILAVORATO" else "fine_batch"
        if op.startswith("fine_") and op != expected:
            raise Http404
    back = reverse("ui:azienda_batch", args=[batch.pk]) if batch else reverse("ui:azienda_station", args=[station.pk])
    form = AziendaActionForm(request.POST if request.method == "POST" else None,
        operation=op, initial={"invio": token_for(request)})

    def execute():
        d = form.cleaned_data
        if op == "inizio_turno":
            ShiftService.start(actor=request.user, postazione=station)
        elif op == "fine_turno":
            ShiftService.end(actor=request.user, turno=shift)
        elif op == "igienizzazione":
            ShiftService.confirm_hygiene(actor=request.user, turno=shift, confermato=d["confermato"])
        elif op == "piano":
            PickingPlanService.create(actor=request.user, postazione=station, ricetta=d["ricetta"], numero_batch=d["numero_batch"])
        elif op == "inizio_batch":
            BatchService.start(actor=request.user, batch=batch)
        else:
            business_mutex()
            active_shift(request.user, station)
            if op == "controllo_batch":
                QualityService.record(actor=request.user, lavorazione=batch.lavorazione,
                    controllo_richiesto=require_control(batch.lavorazione.tipo_lavorazione, "BATCH", "ESITO"), valore=d["esito"])
            else:
                amount = d["quantita"] if op == "fine_semilavorato" else recipe_mass(batch.piano.ricetta)
                BatchService.finish(actor=request.user, batch=batch, quantita=amount,
                    destinazioni=[Allocation(position(d, "destinazione"), amount)])

    if request.method == "POST" and form.is_valid():
        try:
            created = submit_once(request, form.cleaned_data["invio"], execute)
        except ValidationError as exc:
            error_form(form, exc)
        else:
            messages.success(request, "Operazione registrata." if created else "Operazione già registrata: nessun doppio invio.")
            return redirect(back)
    return render(request, "interfaccia/azienda/action.html", {"section": "linee", "title": ACTION_TITLES[op],
        "form": form, "back": back, "station": station, "batch": batch, "op": op})


@permitted("produzione.view_pianoproduzione")
@require_http_methods(["GET"])
def plan(request, pk):
    plan = get_object_or_404(PianoProduzione.objects.select_related("ricetta__articolo", "postazione__risorsa"), pk=pk)
    revision = plan.revisioni.order_by("-numero").first()
    return render(request, "interfaccia/azienda/plan.html", {"section": "linee", "plan": plan,
        "revision": revision, "batches": plan.batch.select_related("lavorazione").order_by("numero"),
        "remaining": PickingPlanService.remaining_batches(plan), "can_operate": can_operate(request.user, plan.postazione),
        "rows": revision.righe.select_related("lotto__articolo", "ubicazione") if revision else [],
        "revisions": plan.revisioni.select_related("confermata_da").order_by("-numero")})


@permitted("auth.can_plan_own_batches")
@require_http_methods(["GET", "POST"])
def picking_plan(request, pk):
    plan = get_object_or_404(PianoProduzione, pk=pk)
    if not can_operate(request.user, plan.postazione):
        raise PermissionDenied
    work = plan.batch.select_related("lavorazione").first().lavorazione
    initial, warning = [], ""
    if request.method == "GET":
        try:
            proposal = PickingPlanService.forecast(actor=request.user, piano=plan)
            for s in proposal.selections:
                p = s.origini[0].posizione
                initial.append({"riga_ricetta": s.riga_ricetta, "lotto": s.lotto, "quantita": s.quantita,
                    "origine": p.ubicazione_id, "origine_scaffale": p.scaffale, "origine_piano": p.piano})
            if not proposal.completa:
                warning = "La disponibilità non copre tutto il fabbisogno. La conferma richiede tutte le quantità previste."
        except ValidationError as exc:
            warning = " · ".join(exc.messages)
    FormSet = forms.formset_factory(PianoIngredientForm, extra=2, can_delete=True, max_num=200, validate_max=True, absolute_max=200)
    data = request.POST if request.method == "POST" else None
    formset = FormSet(data, initial=initial, form_kwargs={"work": work})
    form = PianoConfermaForm(data, initial={"invio": token_for(request), "stato_piano": signed_state(request, plan_state(plan)),
        "motivo": "Conferma del piano di prelievo"})
    if request.method == "POST" and form.is_valid() and formset.is_valid():
        def confirm():
            business_mutex()
            verify_state(request, form.cleaned_data["stato_piano"], plan_state(plan))
            selections = [InputSelection(d["lotto"], d["quantita"], [Allocation(position(d, "origine"), d["quantita"])],
                riga_ricetta=d["riga_ricetta"]) for d in formset.cleaned_data if d and not d.get("DELETE")]
            PickingPlanService.confirm(actor=request.user, piano=plan, selections=selections, motivo=form.cleaned_data["motivo"])
        try:
            created = submit_once(request, form.cleaned_data["invio"], confirm)
        except ValidationError as exc:
            error_form(form, exc)
        else:
            messages.success(request, "Piano confermato. Nessun materiale prenotato o consumato." if created else "Piano già confermato con questo modulo.")
            return redirect("ui:azienda_plan", pk=pk)
    requirements = [{"article": r.articolo, "quantity": r.quantita * PickingPlanService.remaining_batches(plan)}
        for r in plan.ricetta.righe.select_related("articolo")]
    return render(request, "interfaccia/azienda/picking_plan.html", {"section": "linee", "plan": plan,
        "form": form, "formset": formset, "warning": warning, "requirements": requirements})


@permitted("produzione.view_batchpiano")
@require_http_methods(["GET"])
def batch(request, pk):
    batch = get_object_or_404(BatchPiano.objects.select_related("piano__ricetta__articolo", "piano__postazione", "lavorazione__tipo_lavorazione"), pk=pk)
    return render(request, "interfaccia/azienda/batch.html", {"section": "linee", "batch": batch, "work": batch.lavorazione,
        "can_operate": can_operate(request.user, batch.piano.postazione), "has_inputs": batch.lavorazione.inputs.exists(),
        "inputs": batch.lavorazione.inputs.select_related("lotto__articolo"),
        "outputs": batch.lavorazione.outputs.select_related("lotto"), "controls": batch.lavorazione.controlli_qualita.all()})


@permitted("auth.can_record_production_consumption")
@require_http_methods(["GET", "POST"])
def batch_picking(request, pk):
    batch = get_object_or_404(BatchPiano, pk=pk)
    if not can_operate(request.user, batch.piano.postazione):
        raise PermissionDenied
    warning, chosen, revision = "", (), None
    form = BatchPrelievoForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        def consume():
            business_mutex()
            current_revision, current = PickingPlanService.batch_proposal(actor=request.user, batch=batch)
            verify_state(request, form.cleaned_data["proposta"], batch_state(current_revision, current))
            PickingPlanService.consume_batch(actor=request.user, batch=batch, revisione=current_revision)
        try:
            created = submit_once(request, form.cleaned_data["invio"], consume)
        except ValidationError as exc:
            error_form(form, exc)
        else:
            messages.success(request, "Prelievo del batch registrato." if created else "Prelievo già registrato con questo modulo.")
            return redirect("ui:azienda_batch", pk=pk)
    try:
        revision, chosen = PickingPlanService.batch_proposal(actor=request.user, batch=batch)
        if request.method == "GET":
            form = BatchPrelievoForm(initial={"invio": token_for(request), "proposta": signed_state(request, batch_state(revision, chosen))})
    except ValidationError as exc:
        warning = " · ".join(exc.messages)
    return render(request, "interfaccia/azienda/batch_picking.html", {"section": "linee", "batch": batch,
        "form": form, "chosen": chosen, "warning": warning, "revision": revision})
