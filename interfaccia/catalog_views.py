from django import forms
from django.contrib import messages
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from anagrafiche.models import CategoriaArticolo, Ubicazione
from .views import permitted


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = CategoriaArticolo
        fields = ("codice", "nome", "categoria_padre", "attiva", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class UbicazioneForm(forms.ModelForm):
    class Meta:
        model = Ubicazione
        fields = ("codice", "nome", "attiva", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


@permitted("anagrafiche.view_categoriaarticolo")
def categories(request):
    query = request.GET.get("q", "").strip()[:150]
    rows = CategoriaArticolo.objects.select_related("categoria_padre")
    if query:
        rows = rows.filter(Q(codice__icontains=query) | Q(nome__icontains=query))
    return render(request, "interfaccia/categories.html", {"section": "anagrafiche", "catalog_tab": "categorie", "rows": rows, "q": query})


@permitted("anagrafiche.add_categoriaarticolo")
@require_http_methods(["GET", "POST"])
def category_new(request):
    return _form(request, CategoriaForm, None, "Nuova categoria", "ui:categories", "categoria")


@permitted("anagrafiche.change_categoriaarticolo")
@require_http_methods(["GET", "POST"])
def category_edit(request, pk):
    return _form(request, CategoriaForm, get_object_or_404(CategoriaArticolo, pk=pk), "Modifica categoria", "ui:categories", "categoria")


@permitted("anagrafiche.view_ubicazione")
def locations(request):
    query = request.GET.get("q", "").strip()[:150]
    rows = Ubicazione.objects.all()
    if query:
        rows = rows.filter(Q(codice__icontains=query) | Q(nome__icontains=query))
    return render(request, "interfaccia/locations.html", {"section": "anagrafiche", "catalog_tab": "ubicazioni", "rows": rows, "q": query})


@permitted("anagrafiche.add_ubicazione")
@require_http_methods(["GET", "POST"])
def location_new(request):
    return _form(request, UbicazioneForm, None, "Nuova ubicazione", "ui:locations", "ubicazione")


@permitted("anagrafiche.change_ubicazione")
@require_http_methods(["GET", "POST"])
def location_edit(request, pk):
    return _form(request, UbicazioneForm, get_object_or_404(Ubicazione, pk=pk), "Modifica ubicazione", "ui:locations", "ubicazione")


def _form(request, form_class, instance, title, back, label):
    form = form_class(request.POST if request.method == "POST" else None, instance=instance)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"{label.capitalize()} {saved.codice} salvata.")
        return redirect(back)
    return render(request, "interfaccia/catalog_form.html", {"section": "anagrafiche", "form": form, "title": title, "back": back})
