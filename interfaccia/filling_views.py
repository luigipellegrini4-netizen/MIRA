from decimal import Decimal
from django import forms
from django.contrib import messages
from django.core import signing
from django.core.exceptions import ValidationError, PermissionDenied
from django.shortcuts import get_object_or_404, render, redirect
from django.urls import reverse
from django.views.decorators.http import require_http_methods
from magazzino.models import Giacenza
from magazzino.services import Allocation, Position
from produzione.models import PostazioneLinea, TankAziendale, SessioneInvasettamento, CarrelloSessione
from produzione.services import TankService, FillingService, InputSelection
from produzione.services.azienda_common import business_mutex, active_shift, open_session, require_control, rounded
from qualita.services import QualityService
from .views import permitted, token_for, submit_once, position, error_form
from .azienda_views import can_operate, signed_state, verify_state
from .filling_forms import TankSelectionForm, TankQualityForm, CartForm, TreatmentForm, ClosureForm, PackagingRowForm


def material_stocks(station, recipe_id, batches=False):
    qs = Giacenza.objects.filter(quantita__gt=0, ubicazione__attiva=True)
    if batches:
        qs = qs.filter(lotto__lavorazione_origine__batch_piano__piano__postazione__linea=station.linea,
            lotto__lavorazione_origine__batch_piano__piano__ricetta_id=recipe_id, lotto__lavorazione_origine__stato="COMPLETATA")
    else:
        qs = qs.filter(lotto__tank_aziendale__linea=station.linea, lotto__tank_aziendale__ricetta_id=recipe_id,
            lotto__tank_aziendale__pronto_il__isnull=False, lotto__lavorazione_origine__stato="COMPLETATA")
    return qs.select_related("lotto__articolo", "ubicazione").order_by("lotto_id", "pk")


def stock_signature(request, stocks):
    return signed_state(request, {str(s.pk): str(s.quantita) for s in stocks})


def verify_stocks(request, signature, stocks):
    try:
        payload = signing.loads(signature, salt="mira-azienda-preview", max_age=7200)
        all_stocks = payload["state"]
        if payload["user"] != request.user.pk or payload["path"] != request.path:
            raise ValueError()
        if any(all_stocks.get(str(s.pk)) != str(s.quantita) for s in stocks):
            raise ValueError()
    except (signing.BadSignature, ValueError, KeyError, TypeError, AttributeError):
        raise ValidationError("Le quantità selezionate sono cambiate o la proposta è scaduta. Riapri la pagina.") from None


def stock_selections(stocks, requirement):
    return [InputSelection(s.lotto_id, s.quantita, [Allocation(Position(s.ubicazione_id, s.scaffale, s.piano), s.quantita)], requisito_input=requirement) for s in stocks]


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def select_materials(request, pk, mode, session_pk=None):
    station = get_object_or_404(PostazioneLinea.objects.select_related("linea"), pk=pk)
    if not can_operate(request.user, station):
        raise PermissionDenied
    session = get_object_or_404(SessioneInvasettamento, pk=session_pk, turno__postazione=station) if session_pk else None
    if mode not in {"tank", "session", "add_tanks"} or (mode == "tank" and not station.linea.tipo_tank_id) or (mode != "tank" and not station.linea.tipo_invasettamento_id):
        raise PermissionDenied
    recipe_value = session.ricetta_id if session else (request.POST.get("ricetta") if request.method == "POST" else request.GET.get("ricetta"))
    try:
        recipe_id = int(recipe_value)
    except (ValueError, TypeError):
        recipe_id = None
    stocks = material_stocks(station, recipe_id, batches=mode == "tank")
    form = TankSelectionForm(request.POST if request.method == "POST" else None, stocks=stocks, mode=mode,
        kind=station.linea.tipo_invasettamento, initial={"invio": token_for(request), "proposta": stock_signature(request, stocks), "ricetta": recipe_id})
    if session:
        form.fields["ricetta"].disabled = True
    back = reverse("ui:azienda_session", args=[session.pk]) if session else reverse("ui:azienda_station", args=[pk])
    result = []
    if request.method == "POST" and form.is_valid():
        def execute():
            business_mutex()
            selected = list(form.cleaned_data["materiali"])
            current = list(material_stocks(station, form.cleaned_data["ricetta"].pk, batches=mode == "tank").filter(pk__in=[s.pk for s in selected]))
            if len(current) != len(selected):
                raise ValidationError("Materiali non più disponibili. Riapri la pagina.")
            verify_stocks(request, form.cleaned_data["proposta"], current)
            kind = station.linea.tipo_tank if mode == "tank" else station.linea.tipo_invasettamento
            origin = station.linea.tipo_batch if mode == "tank" else station.linea.tipo_tank
            requirements = list(kind.requisiti_input.filter(tipo_lavorazione_origine=origin))
            if len(requirements) != 1:
                raise ValidationError("Configurare un solo requisito per i materiali di origine.")
            selections = stock_selections(current, requirements[0])
            if mode == "tank":
                amount = sum(s.quantita for s in current)
                result.append(TankService.form(actor=request.user, postazione=station, ricetta=form.cleaned_data["ricetta"],
                    selections=selections, destinazioni=[Allocation(position(form.cleaned_data, "destinazione"), amount)]))
            elif mode == "session":
                jars, caps = form.cleaned_data["vasetti"], form.cleaned_data["capsule"]
                result.append(FillingService.open(actor=request.user, postazione=station, ricetta=form.cleaned_data["ricetta"], selections=selections,
                    articolo_vasetti=jars.articolo, articolo_capsule=caps.articolo, requisito_vasetti=jars, requisito_capsule=caps))
            else:
                FillingService.add_tanks(actor=request.user, sessione=session, selections=selections)
        try:
            created = submit_once(request, form.cleaned_data["invio"], execute)
        except ValidationError as exc:
            error_form(form, exc)
        else:
            messages.success(request, "Materiali registrati." if created else "Operazione già registrata.")
            if result:
                return redirect("ui:azienda_tank" if mode == "tank" else "ui:azienda_session", pk=result[0].pk)
            return redirect(back)
    return render(request, "interfaccia/azienda/select_materials.html", {"section": "linee", "form": form, "back": back,
        "station": station, "recipe_id": recipe_id, "mode": mode, "session": session})


@permitted("produzione.view_tankaziendale")
@require_http_methods(["GET", "POST"])
def tank(request, pk):
    tank = get_object_or_404(TankAziendale.objects.select_related("lotto", "lavorazione__tipo_lavorazione", "ricetta"), pk=pk)
    form = TankQualityForm(request.POST if request.method == "POST" else None, initial={"invio": token_for(request)})
    allowed = request.user.has_perm("auth.can_record_quality_control") and not tank.pronto_il and tank.lavorazione.stato == "IN_CORSO"
    present = set(tank.lavorazione.controlli_qualita.values_list("controllo_richiesto__funzione", flat=True))
    allowed = allowed and not {"BRIX", "PH"}.issubset(present)
    if request.method == "POST":
        if not request.user.has_perm("auth.can_record_quality_control"):
            raise PermissionDenied
        if form.is_valid():
            def record():
                business_mutex()
                recorded = set(tank.lavorazione.controlli_qualita.values_list("controllo_richiesto__funzione", flat=True))
                if {"BRIX", "PH"}.issubset(recorded):
                    raise ValidationError("Controlli già registrati: consultare gli esiti senza sovrascrivere lo storico.")
                values = [("BRIX", form.cleaned_data["brix"]), ("PH", form.cleaned_data["ph"])]
                values.sort(key=lambda pair: pair[0] not in recorded)
                for function, value in values:
                    QualityService.record(actor=request.user, lavorazione=tank.lavorazione,
                        controllo_richiesto=require_control(tank.lavorazione.tipo_lavorazione, function, "DECIMALE"), valore=value)
            try:
                submit_once(request, form.cleaned_data["invio"], record)
            except ValidationError as exc:
                error_form(form, exc)
            else:
                messages.success(request, "Misure registrate. Il tank viene rilasciato solo se tutti i controlli sono conformi.")
                return redirect("ui:azienda_tank", pk=pk)
    return render(request, "interfaccia/azienda/tank.html", {"section": "linee", "tank": tank, "form": form, "allowed": allowed,
        "controls": tank.lavorazione.controlli_qualita.select_related("controllo_richiesto__parametro_controllo")})


@permitted("produzione.view_sessioneinvasettamento")
@require_http_methods(["GET"])
def session(request, pk):
    session = get_object_or_404(SessioneInvasettamento.objects.select_related("turno__postazione", "lotto__articolo", "ricetta"), pk=pk)
    carts = list(session.carrelli.select_related("unita").prefetch_related("trattamenti__lavorazione__controlli_qualita"))
    for cart in carts:
        treatments = {t.fase: t for t in cart.trattamenti.all()}
        cart.show_pasteurization = "PASTORIZZAZIONE" not in treatments
        cart.show_vacuum = "VUOTO" not in treatments and "PASTORIZZAZIONE" in treatments and treatments["PASTORIZZAZIONE"].lavorazione.stato == "COMPLETATA"
    return render(request, "interfaccia/azienda/session.html", {"section": "linee", "session": session,
        "own": can_operate(request.user, session.turno.postazione) and session.turno.operatore_id == request.user.pk,
        "carts": carts,
        "inputs": session.lavorazione.inputs.select_related("lotto__articolo"), "summary": getattr(session, "riepilogo", None)})


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def cart_action(request, pk, phase=None):
    cart = get_object_or_404(CarrelloSessione, pk=pk) if phase else None
    session = cart.sessione if cart else get_object_or_404(SessioneInvasettamento, pk=pk)
    if not can_operate(request.user, session.turno.postazione) or session.turno.operatore_id != request.user.pk:
        raise PermissionDenied
    form_class = TreatmentForm if phase else CartForm
    form = form_class(request.POST if request.method == "POST" else None, initial={"invio": token_for(request)})
    if request.method == "POST" and form.is_valid():
        def execute():
            if phase:
                FillingService.treat_cart(actor=request.user, carrello=cart, fase=phase, esito=form.cleaned_data["esito"])
            else:
                FillingService.add_cart(actor=request.user, sessione=session, risorsa_produttiva=form.cleaned_data["risorsa"])
        try:
            submit_once(request, form.cleaned_data["invio"], execute)
        except ValidationError as exc:
            error_form(form, exc)
        else:
            messages.success(request, "Operazione sul carrello registrata.")
            return redirect("ui:azienda_session", pk=session.pk)
    title = "71 °C × 4 minuti" if phase == "PASTORIZZAZIONE" else "Shock termico e presenza del vuoto" if phase else "Nuovo carrello"
    return render(request, "interfaccia/azienda/action.html", {"section": "linee", "form": form, "title": title,
        "station": session.turno.postazione, "back": reverse("ui:azienda_session", args=[session.pk])})


def closure_args(d):
    return {k: d[k] for k in ("vasetti_buoni", "vasetti_scarti", "capsule_difettose", "peso_netto_g")}


@permitted("auth.can_execute_production")
def add_session_tanks(request, pk):
    session = get_object_or_404(SessioneInvasettamento, pk=pk)
    return select_materials(request, pk=session.turno.postazione_id, mode="add_tanks", session_pk=session.pk)


def closure_state(d):
    return {k: (getattr(v, "pk", None) if hasattr(v, "pk") else str(v)) for k, v in d.items()}


@permitted("auth.can_execute_production")
@require_http_methods(["GET", "POST"])
def close_session(request, pk):
    session = get_object_or_404(SessioneInvasettamento, pk=pk)
    if request.method == "GET" and session.chiusa_il:
        return redirect("ui:azienda_session", pk=pk)
    if not can_operate(request.user, session.turno.postazione) or session.turno.operatore_id != request.user.pk:
        raise PermissionDenied
    data = request.POST if request.method == "POST" else None
    form = ClosureForm(data)
    FormSet = forms.formset_factory(PackagingRowForm, extra=2, can_delete=True, max_num=200, validate_max=True, absolute_max=200)
    fs, values, missing = None, None, {}
    token, preview = "", ""
    if request.method == "POST" and form.is_valid():
        d = form.cleaned_data
        if request.POST.get("fase") == "conferma":
            fs = FormSet(data, form_kwargs={"session": session})
            token, preview = request.POST.get("invio", ""), request.POST.get("riepilogo", "")
            if fs.is_valid():
                def confirm():
                    business_mutex()
                    verify_state(request, preview, closure_state(d))
                    selections = []
                    for row in fs.cleaned_data:
                        if not row or row.get("DELETE"):
                            continue
                        stock = row["stock"]
                        req = session.requisito_vasetti if stock.lotto.articolo_id == session.articolo_vasetti_id else session.requisito_capsule
                        selections.append(InputSelection(stock.lotto_id, row["quantita"], [Allocation(Position(stock.ubicazione_id, stock.scaffale, stock.piano), row["quantita"])], requisito_input=req))
                    destinations = [Allocation(position(d, "destinazione"), rounded(Decimal(d["vasetti_buoni"]) * d["peso_netto_g"] / 1000))] if d["vasetti_buoni"] else []
                    FillingService.close(actor=request.user, sessione=session, **closure_args(d), selections=selections, destinazioni=destinations)
                try:
                    submit_once(request, token, confirm)
                except ValidationError as exc:
                    error_form(form, exc)
                else:
                    messages.success(request, "Sessione chiusa: confezioni prelevate, prodotto buono caricato e resa registrata.")
                    return redirect("ui:azienda_session", pk=pk)
        else:
            try:
                values, selections, missing = FillingService.packaging_forecast(actor=request.user, sessione=session, **closure_args(d))
                initial = []
                for s in selections:
                    p = s.origini[0].posizione
                    stock = Giacenza.objects.get(lotto_id=s.lotto, **p.stock_lookup())
                    initial.append({"stock": stock.pk, "quantita": int(s.quantita)})
                fs = FormSet(initial=initial, form_kwargs={"session": session})
                token, preview = token_for(request), signed_state(request, closure_state(d))
            except ValidationError as exc:
                error_form(form, exc)
    if fs is not None:
        for field in form.fields.values():
            field.widget = forms.HiddenInput()
        if values is None:
            from produzione.services.azienda_common import totals
            try:
                values = totals(buoni=d["vasetti_buoni"], scarti=d["vasetti_scarti"], capsule_difettose=d["capsule_difettose"], peso_g=d["peso_netto_g"], teorico=FillingService.theoretical_mass(session))
            except ValidationError:
                pass
    return render(request, "interfaccia/azienda/closure.html", {"section": "linee", "session": session, "form": form,
        "formset": fs, "values": values, "missing": any(missing.values()), "token": token, "preview": preview})
