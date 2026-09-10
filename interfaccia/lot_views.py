from django import forms
from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods

from magazzino.models import Lotto
from magazzino.services import LotCorrectionService
from .views import permitted


class LottoCorrectionForm(forms.Form):
    codice_lotto = forms.CharField(max_length=100)
    data_produzione = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    data_scadenza = forms.DateField(required=False, widget=forms.DateInput(attrs={"type": "date"}))
    note = forms.CharField(required=False, widget=forms.Textarea(attrs={"rows": 3}))
    motivazione = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), help_text="La correzione viene conservata nello storico del lotto.")


@permitted("auth.can_adjust_inventory")
@require_http_methods(["GET", "POST"])
def lot_edit(request, pk):
    lot = get_object_or_404(Lotto.objects.select_related("articolo", "fornitore"), pk=pk)
    initial = {name: getattr(lot, name) for name in ("codice_lotto", "data_produzione", "data_scadenza", "note")}
    form = LottoCorrectionForm(request.POST if request.method == "POST" else None, initial=initial)
    if request.method == "POST" and form.is_valid():
        data = form.cleaned_data.copy(); reason = data.pop("motivazione")
        try:
            LotCorrectionService.correct(actor=request.user, lotto=lot, motivazione=reason, **data)
        except ValidationError as exc:
            form.add_error(None, " · ".join(exc.messages))
        else:
            messages.success(request, "Lotto corretto; modifica registrata nello storico.")
            return redirect("ui:lot", pk=lot.pk)
    return render(request, "interfaccia/lot_edit.html", {"section": "magazzino", "lot": lot, "form": form})
