from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.http import Http404
from django.views.decorators.http import require_http_methods

from interfaccia.models import CorrezioneAmministrativa
from magazzino.models import CorrezioneLotto, Lotto
from magazzino.services import LotCorrectionService
from produzione.models import ControlloSessioneSemplificata
from vendite.models import RigaVendita, Vendita
from .correction_forms import (
    ControlCorrectionForm, SaleCorrectionForm, SalesLineCorrectionForm,
    StockCorrectionForm, CorrectionReasonForm, catalog_form,
)
from .correction_catalog import EDITABLE_FIELDS, correction_model, correction_models
from .correction_services import AdministrativeCorrectionService
from .lot_views import LottoCorrectionForm
from .views import permitted


@permitted("auth.can_manage_backups")
def corrections(request):
    query = request.GET.get("q", "").strip()[:100]
    lots = Lotto.objects.select_related("articolo").order_by("-pk")
    controls = ControlloSessioneSemplificata.objects.select_related(
        "sessione__lotto", "sessione__ricetta__articolo",
    ).order_by("-registrato_il", "-pk")
    sales = Vendita.objects.select_related("cliente").order_by("-data_documento", "-pk")
    sales_lines = RigaVendita.objects.select_related(
        "vendita__cliente", "movimento__lotto__articolo",
    ).order_by("-pk")
    if query:
        lots = lots.filter(Q(codice_lotto__icontains=query) | Q(articolo__codice__icontains=query))
        controls = controls.filter(
            Q(sessione__lotto__codice_lotto__icontains=query)
            | Q(sessione__ricetta__articolo__codice__icontains=query)
        )
        sales = sales.filter(
            Q(numero_documento__icontains=query) | Q(cliente__ragione_sociale__icontains=query)
            | Q(righe__movimento__lotto__codice_lotto__icontains=query)
        ).distinct()
        sales_lines = sales_lines.filter(
            Q(vendita__numero_documento__icontains=query)
            | Q(movimento__lotto__codice_lotto__icontains=query)
            | Q(movimento__lotto__articolo__codice__icontains=query)
        )
    return render(request, "interfaccia/corrections.html", {
        "section": "correzioni", "q": query, "lots": lots[:30], "controls": controls[:30],
        "sales": sales[:30], "sales_lines": sales_lines[:30],
        "control_history": CorrezioneAmministrativa.objects.select_related("eseguita_da")[:20],
        "lot_history": CorrezioneLotto.objects.select_related("lotto", "eseguita_da")[:20],
    })


@permitted("auth.can_manage_backups")
def correction_tables(request):
    return render(request, "interfaccia/correction_tables.html", {
        "section": "correzioni", "tables": [
            {"label": model._meta.label, "app": model._meta.app_label,
             "name": model._meta.model_name, "editable": model._meta.label in EDITABLE_FIELDS}
            for model in correction_models()
        ],
    })


@permitted("auth.can_manage_backups")
def correction_table(request, app_label, model_name):
    model = correction_model(app_label, model_name)
    if model is None:
        raise Http404
    query = request.GET.get("q", "").strip()[:100]
    records = model.objects.order_by("-pk")
    if query:
        from django.db.models import Q
        from django.db import models as db_models
        search = Q()
        for field in model._meta.fields:
            if isinstance(field, (db_models.CharField, db_models.TextField)) and not field.is_relation:
                search |= Q(**{f"{field.name}__icontains": query})
        if query.isdigit():
            search |= Q(pk=int(query))
        records = records.filter(search) if search else records.none()
    return render(request, "interfaccia/correction_table.html", {
        "section": "correzioni", "label": model._meta.label,
        "app_label": model._meta.app_label, "model_name": model._meta.model_name,
        "records": records[:100], "q": query,
        "editable": model._meta.label in EDITABLE_FIELDS,
    })


@permitted("auth.can_manage_backups")
@require_http_methods(["GET", "POST"])
def correct_catalog_record(request, app_label, model_name, pk):
    model = correction_model(app_label, model_name)
    if model is None:
        raise Http404
    record = get_object_or_404(model, pk=pk)
    editable = model._meta.label in EDITABLE_FIELDS
    form = catalog_form(
        model, request.POST if request.method == "POST" else None, instance=record,
    ) if editable else None
    reason_form = CorrectionReasonForm(request.POST if request.method == "POST" else None)
    if not editable:
        reason_form.fields["annotazione"].required = True
    else:
        reason_form.fields.pop("annotazione")
    if request.method == "POST" and reason_form.is_valid() and (form is None or form.is_valid()):
        data = form.cleaned_data if form else {}
        try:
            AdministrativeCorrectionService.correct_catalog_record(
                actor=request.user, model=model, record_id=record.pk,
                **reason_form.cleaned_data, **data,
            )
        except ValidationError as exc:
            reason_form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Correzione o annotazione registrata con motivazione.")
            return redirect("ui:correct_catalog_record", app_label=app_label, model_name=model_name, pk=pk)
    return render(request, "interfaccia/correction_catalog_edit.html", {
        "section": "correzioni", "label": model._meta.label,
        "app_label": model._meta.app_label, "model_name": model._meta.model_name,
        "record": record,
        "form": form, "reason_form": reason_form, "editable": editable,
        "history": CorrezioneAmministrativa.objects.filter(
            modello=model._meta.label, record_id=str(record.pk),
        ).select_related("eseguita_da")[:20],
    })


@permitted("auth.can_manage_backups")
@require_http_methods(["GET", "POST"])
def correct_sales_line(request, pk):
    line = get_object_or_404(RigaVendita.objects.select_related(
        "vendita__cliente", "movimento__lotto__articolo",
    ), pk=pk)
    form = SalesLineCorrectionForm(
        request.POST if request.method == "POST" else None, riga=line,
    )
    if request.method == "POST" and form.is_valid():
        try:
            AdministrativeCorrectionService.correct_sales_line(
                actor=request.user, riga=line, **form.cleaned_data,
            )
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Quantità venduta corretta con un movimento compensativo motivato.")
            return redirect("ui:correct_sales_line", pk=pk)
    return render(request, "interfaccia/correction_edit.html", {
        "section": "correzioni", "kind": "riga vendita", "record": line, "form": form,
        "history": CorrezioneAmministrativa.objects.filter(
            modello="vendite.RigaVendita", record_id=pk,
        ).select_related("eseguita_da")[:20],
    })


@permitted("auth.can_manage_backups")
@require_http_methods(["GET", "POST"])
def correct_stock(request):
    form = StockCorrectionForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        try:
            AdministrativeCorrectionService.correct_stock(actor=request.user, **form.cleaned_data)
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Giacenza corretta tramite movimento di rettifica motivato.")
            return redirect("ui:corrections")
    return render(request, "interfaccia/correction_edit.html", {
        "section": "correzioni", "kind": "giacenza", "record": None, "form": form,
        "history": CorrezioneAmministrativa.objects.filter(modello="magazzino.Giacenza")
        .select_related("eseguita_da")[:20],
    })


@permitted("auth.can_manage_backups")
@require_http_methods(["GET", "POST"])
def correct_sale(request, pk):
    sale = get_object_or_404(Vendita.objects.select_related("cliente"), pk=pk)
    form = SaleCorrectionForm(request.POST if request.method == "POST" else None, instance=sale)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        reason = data.pop("motivazione")
        try:
            AdministrativeCorrectionService.correct_sale(
                actor=request.user, vendita=sale, motivazione=reason, **data,
            )
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Documento di vendita corretto; modifica registrata nello storico.")
            return redirect("ui:correct_sale", pk=pk)
    return render(request, "interfaccia/correction_edit.html", {
        "section": "correzioni", "kind": "vendita", "record": sale, "form": form,
        "history": CorrezioneAmministrativa.objects.filter(
            modello="vendite.Vendita", record_id=pk,
        ).select_related("eseguita_da")[:20],
    })


@permitted("auth.can_manage_backups")
@require_http_methods(["GET", "POST"])
def correct_control(request, pk):
    control = get_object_or_404(ControlloSessioneSemplificata.objects.select_related(
        "sessione__lotto", "sessione__ricetta__articolo",
    ), pk=pk)
    form = ControlCorrectionForm(request.POST if request.method == "POST" else None, instance=control)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        reason = data.pop("motivazione")
        batch_ids = [batch.pk for batch in data.pop("batch_associati")] if control.tipo == "TANK" else None
        try:
            AdministrativeCorrectionService.correct_control(
                actor=request.user, controllo=control, motivazione=reason,
                batch_ids=batch_ids, **data,
            )
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Controllo corretto; valori precedenti e nuovi registrati nello storico.")
            return redirect("ui:correct_control", pk=pk)
    return render(request, "interfaccia/correction_edit.html", {
        "section": "correzioni", "kind": "controllo", "record": control, "form": form,
        "history": CorrezioneAmministrativa.objects.filter(
            modello="produzione.ControlloSessioneSemplificata", record_id=pk,
        ).select_related("eseguita_da")[:20],
    })


@permitted("auth.can_manage_backups")
@require_http_methods(["GET", "POST"])
def correct_lot(request, pk):
    lot = get_object_or_404(Lotto.objects.select_related("articolo", "fornitore"), pk=pk)
    initial = {name: getattr(lot, name) for name in ("codice_lotto", "data_produzione", "data_scadenza", "note")}
    form = LottoCorrectionForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy()
        reason = data.pop("motivazione")
        try:
            LotCorrectionService.correct(actor=request.user, lotto=lot, motivazione=reason, **data)
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Lotto corretto; valori precedenti e nuovi registrati nello storico.")
            return redirect("ui:correct_lot", pk=pk)
    return render(request, "interfaccia/correction_edit.html", {
        "section": "correzioni", "kind": "lotto", "record": lot, "form": form,
        "history": CorrezioneLotto.objects.filter(lotto=lot).select_related("eseguita_da")[:20],
    })
