import csv
import io
import json
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core import signing
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods
from .inventory_csv import HEADERS, apply_rows, csv_response_rows, inspect_rows, read_upload
from .backup import create_backup, read_backup, reset_trial_data, restore_backup
from .views import permitted


@login_required
@require_http_methods(["GET", "POST"])
def manage_csv(request):
    if not request.user.is_active or not (
        request.user.has_perm("auth.can_adjust_inventory")
        or request.user.has_perm("auth.can_manage_backups")
    ):
        raise PermissionDenied
    if request.method == "POST" and not request.user.has_perm("auth.can_adjust_inventory"):
        raise PermissionDenied
    selected_kind = request.GET.get("tipo", "")
    context = {"section": "configurazione", "kinds": HEADERS,
               "selected_kind": selected_kind if selected_kind in HEADERS else ""}
    if request.method == "POST":
        try:
            if request.POST.get("confirm"):
                payload = signing.loads(request.POST["token"], salt="mira-csv", max_age=1800)
                reason = request.POST.get("motivazione", "").strip()
                if not reason:
                    raise ValidationError("La motivazione dell’importazione è obbligatoria.")
                changed = apply_rows(payload["kind"], payload["rows"], request.user, reason)
                messages.success(request, f"Importazione completata: {changed} modifiche registrate.")
                return redirect("ui:manage_csv")
            kind = request.POST.get("tipo")
            if kind not in HEADERS or "file" not in request.FILES:
                raise ValidationError("Scegli tipo e file CSV.")
            rows = read_upload(request.FILES["file"]); report = inspect_rows(kind, rows)
            context.update(kind=kind, report=report, errors=sum(bool(r["error"]) for r in report),
                token=signing.dumps({"kind": kind, "rows": rows}, salt="mira-csv", compress=True))
        except (ValidationError, signing.BadSignature, signing.SignatureExpired, KeyError) as exc:
            context["error"] = " · ".join(getattr(exc, "messages", ["Anteprima scaduta o non valida."]))
    return render(request, "interfaccia/manage_csv.html", context)


@permitted("auth.can_manage_backups")
def download_backup(request):
    content = json.dumps(create_backup(), ensure_ascii=False, indent=2)
    response = HttpResponse(content, content_type="application/json; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="mira_backup.json"'
    return response


@permitted("auth.can_manage_backups")
@require_http_methods(["POST"])
def restore(request):
    try:
        upload = request.FILES.get("backup")
        if not upload or upload.size > 25_000_000:
            raise ValidationError("Selezionare un backup MIRA non superiore a 25 MB.")
        if request.POST.get("conferma", "").strip().upper() != "RIPRISTINA MIRA":
            raise ValidationError("Scrivere RIPRISTINA MIRA nel campo di conferma.")
        payload = read_backup(upload.read())
        restore_backup(payload)
        messages.success(request, "Backup ripristinato correttamente.")
    except ValidationError as exc:
        messages.error(request, " · ".join(exc.messages))
    return redirect("ui:manage_csv")


@permitted("auth.can_manage_backups")
@require_http_methods(["POST"])
def reset_database(request):
    try:
        if request.POST.get("conferma", "").strip().upper() != "AZZERA MIRA":
            raise ValidationError("Scrivere AZZERA MIRA nel campo di conferma.")
        backup, removed, preserved = reset_trial_data()
        messages.success(request, f"Dati di prova azzerati. Articoli eliminati: {removed}; articoli di configurazione conservati: {preserved}. Backup: {backup}")
    except ValidationError as exc:
        messages.error(request, " · ".join(exc.messages))
    return redirect("ui:manage_csv")


@permitted("magazzino.view_giacenza")
def download_csv(request, kind):
    if kind not in HEADERS:
        raise PermissionDenied
    output = io.StringIO(); writer = csv.writer(output, delimiter=";", lineterminator="\r\n")
    writer.writerow(HEADERS[kind]); writer.writerows(csv_response_rows(kind))
    response = HttpResponse("\ufeff" + output.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = f'attachment; filename="mira_{kind}.csv"'
    return response
