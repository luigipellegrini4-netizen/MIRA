from django import forms
from django.contrib import messages
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from anagrafiche.models import Articolo
from .views import permitted


class ArticoloForm(forms.ModelForm):
    class Meta:
        model = Articolo
        fields = ("codice", "descrizione", "categoria", "unita_misura", "criterio_rotazione",
                  "tracciabilita_lotto", "scorta_minima", "attivo", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


@permitted("anagrafiche.change_articolo")
@require_http_methods(["GET", "POST"])
def article_edit(request, pk):
    article = get_object_or_404(Articolo, pk=pk)
    form = ArticoloForm(request.POST if request.method == "POST" else None, instance=article)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Articolo {saved.codice} aggiornato.")
        return redirect("ui:anagrafiche")
    return render(request, "interfaccia/article_form.html", {"section": "anagrafiche", "form": form, "article": article})


@permitted("anagrafiche.add_articolo")
@require_http_methods(["GET", "POST"])
def article_new(request):
    form = ArticoloForm(request.POST if request.method == "POST" else None)
    if request.method == "POST" and form.is_valid():
        saved = form.save()
        messages.success(request, f"Articolo {saved.codice} creato.")
        return redirect("ui:anagrafiche")
    return render(request, "interfaccia/article_form.html", {"section": "anagrafiche", "form": form, "article": None})
