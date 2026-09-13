import csv, io
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods
from anagrafiche.models import Articolo
from produzione.models import Ricetta, RigaRicetta
from produzione.services import RecipeService
from .recipe_forms import RecipeForm, RecipeLines
from .views import paged, permitted


@permitted("produzione.view_ricetta")
def recipes(request):
    q = request.GET.get("q", "").strip()[:150]
    qs = Ricetta.objects.select_related("articolo").prefetch_related("righe").order_by("articolo__codice", "versione")
    if q: qs = qs.filter(Q(nome__icontains=q) | Q(versione__icontains=q) | Q(articolo__codice__icontains=q))
    return render(request, "interfaccia/recipes.html", {"section": "ricette", "page": paged(request, qs), "q": q})


@permitted("auth.can_manage_process_configuration")
@require_http_methods(["GET", "POST"])
@transaction.atomic
def recipe_edit(request, pk=None):
    recipe = get_object_or_404(Ricetta, pk=pk) if pk else Ricetta()
    used = bool(pk and recipe.utilizzata)
    form = RecipeForm(request.POST or None, instance=recipe)
    lines = RecipeLines(request.POST or None, instance=recipe, prefix="righe") if not used else None
    if request.method == "POST" and form.is_valid() and (used or lines.is_valid()):
        if used:
            old = Ricetta.objects.get(pk=recipe.pk)
            if any(form.cleaned_data[k] != getattr(old, k) for k in ("articolo", "nome", "versione", "note")):
                form.add_error(None, "La ricetta è già utilizzata: puoi modificare solo lo stato oppure creare una nuova versione.")
            else:
                recipe.attiva = form.cleaned_data["attiva"]; recipe.save(); return redirect("ui:recipe", pk=recipe.pk)
        else:
            recipe = form.save(); lines.instance = recipe; lines.save(); messages.success(request, "Ricetta salvata."); return redirect("ui:recipe", pk=recipe.pk)
    return render(request, "interfaccia/recipe_edit.html", {
        "section": "ricette", "recipe": recipe, "form": form, "lines": lines, "used": used,
        "readonly_lines": recipe.righe.select_related("articolo", "categoria_articolo") if used else (),
    })


@permitted("auth.can_manage_process_configuration")
@require_http_methods(["POST"])
def recipe_clone(request, pk):
    try:
        result = RecipeService.new_version(actor=request.user, ricetta=pk, versione=request.POST.get("versione", "").strip())
        messages.success(request, "Nuova versione creata dalla ricetta precedente.")
        return redirect("ui:recipe", pk=result.pk)
    except ValidationError as exc:
        messages.error(request, " · ".join(exc.messages)); return redirect("ui:recipe", pk=pk)


@permitted("produzione.view_ricetta")
def recipes_csv(request):
    out = io.StringIO(); w = csv.writer(out, delimiter=";", lineterminator="\r\n")
    w.writerow(["prodotto", "nome", "versione", "attiva", "note_ricetta", "ingrediente", "categoria_ingrediente", "quantita", "note_riga"])
    for recipe in Ricetta.objects.select_related("articolo").prefetch_related("righe__articolo", "righe__categoria_articolo"):
        rows = list(recipe.righe.all()) or [None]
        for row in rows: w.writerow([recipe.articolo.codice, recipe.nome, recipe.versione, "SI" if recipe.attiva else "NO", recipe.note,
            row.articolo.codice if row and row.articolo else "", row.categoria_articolo.codice if row and row.categoria_articolo else "",
            row.quantita if row else "", row.note if row else ""])
    response = HttpResponse("\ufeff" + out.getvalue(), content_type="text/csv; charset=utf-8")
    response["Content-Disposition"] = 'attachment; filename="mira_ricette_complete.csv"'; return response


@permitted("auth.can_manage_process_configuration")
@require_http_methods(["POST"])
@transaction.atomic
def recipes_import(request):
    try:
        upload = request.FILES.get("file")
        if not upload or upload.size > 2_000_000: raise ValidationError("Seleziona un CSV non superiore a 2 MB.")
        reader = csv.DictReader(io.StringIO(upload.read().decode("utf-8-sig")), delimiter=";")
        required = {"prodotto", "nome", "versione", "attiva", "note_ricetta", "ingrediente", "categoria_ingrediente", "quantita", "note_riga"}
        if not required.issubset(reader.fieldnames or []): raise ValidationError("Intestazioni CSV non valide.")
        groups = {}
        for n, row in enumerate(reader, 2): groups.setdefault((row["prodotto"].strip(), row["versione"].strip()), []).append((n, row))
        prepared = []
        for (product_code, version), rows in groups.items():
            if not product_code or not version:
                raise ValidationError("Prodotto e versione sono obbligatori in ogni ricetta.")
            product = Articolo.objects.get(codice=product_code, attivo=True); first = rows[0][1]
            for number, row in rows[1:]:
                if any(row[field].strip() != first[field].strip() for field in ("nome", "attiva", "note_ricetta")):
                    raise ValidationError(f"Riga {number}: dati generali diversi per la stessa ricetta.")
            active_value = first["attiva"].strip().upper()
            if active_value not in {"SI", "SÌ", "1", "TRUE", "NO", "0", "FALSE"}:
                raise ValidationError(f"{product_code} v{version}: il campo attiva deve essere SI oppure NO.")
            ingredients = []
            seen = set()
            for number, row in rows:
                if not row["quantita"].strip():
                    continue
                if row.get("categoria_ingrediente", "").strip():
                    raise ValidationError(f"Riga {number}: sostituire la categoria ingrediente con un articolo preciso.")
                code = row["ingrediente"].strip()
                if not code:
                    raise ValidationError(f"Riga {number}: indicare il codice dell’ingrediente.")
                article = Articolo.objects.get(codice=code, attivo=True)
                if article.pk in seen:
                    raise ValidationError(f"Riga {number}: l’ingrediente {code} è ripetuto nella stessa ricetta.")
                seen.add(article.pk)
                ingredients.append((number, row, article))
            if not ingredients:
                raise ValidationError(f"{product_code} v{version}: inserire almeno un ingrediente per batch.")
            prepared.append((product, version, first, ingredients))

        for product, version, first, ingredients in prepared:
            product_code = product.codice
            recipe = Ricetta.objects.filter(articolo=product, versione=version).first()
            if recipe and recipe.utilizzata: raise ValidationError(f"{product_code} v{version} è già utilizzata: importare con una nuova versione.")
            recipe = recipe or RecipeService.create(actor=request.user, articolo=product, nome=first["nome"], versione=version, note=first["note_ricetta"])
            recipe.nome=first["nome"]; recipe.note=first["note_ricetta"]; recipe.attiva=first["attiva"].strip().upper() in {"SI","SÌ","1","TRUE"}; recipe.save()
            for line in list(recipe.righe.all()): RecipeService.remove_line(actor=request.user, riga=line)
            for number, row, article in ingredients:
                RecipeService.add_line(actor=request.user, ricetta=recipe, articolo=article, quantita=row["quantita"].replace(",","."), note=row["note_riga"])
        messages.success(request, f"Importate {len(groups)} ricette.")
    except (ValidationError, UnicodeDecodeError, csv.Error, Articolo.DoesNotExist) as exc:
        transaction.set_rollback(True); messages.error(request, "Importazione annullata: " + " · ".join(getattr(exc, "messages", [str(exc)])))
    return redirect("ui:recipes")
