from django import forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from anagrafiche.models import Fornitore
from .views import paged, permitted


class FornitoreForm(forms.ModelForm):
    class Meta:
        model = Fornitore
        fields = ("codice", "ragione_sociale", "partita_iva", "codice_fiscale", "indirizzo",
                  "cap", "comune", "provincia", "nazione", "telefono", "email", "attivo", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


@permitted("anagrafiche.view_fornitore")
def suppliers(request):
    query = request.GET.get("q", "").strip()[:150]
    rows = Fornitore.objects.all()
    if query:
        rows = rows.filter(Q(codice__icontains=query) | Q(ragione_sociale__icontains=query) |
                           Q(partita_iva__icontains=query) | Q(comune__icontains=query))
    return render(request, "interfaccia/suppliers.html", {
        "section": "anagrafiche", "catalog_tab": "fornitori", "page": paged(request, rows), "q": query,
    })


@permitted("anagrafiche.add_fornitore")
@require_http_methods(["GET", "POST"])
def supplier_new(request):
    return _supplier_form(request, None)


@permitted("anagrafiche.change_fornitore")
@require_http_methods(["GET", "POST"])
def supplier_edit(request, pk):
    return _supplier_form(request, get_object_or_404(Fornitore, pk=pk))


def _supplier_form(request, supplier):
    form = FornitoreForm(request.POST if request.method == "POST" else None, instance=supplier)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Fornitore {saved.codice} salvato.")
        return redirect("ui:suppliers")
    return render(request, "interfaccia/supplier_form.html", {
        "section": "anagrafiche", "form": form, "supplier": supplier,
        "title": "Modifica fornitore" if supplier else "Nuovo fornitore",
    })
