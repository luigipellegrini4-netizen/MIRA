from django import forms
from django.forms import modelform_factory
from decimal import Decimal
from django.db.models import Q
from django.utils import timezone

from magazzino.models import Giacenza, Movimento
from produzione.models import AssociazioneTankBatch, ControlloSessioneSemplificata
from vendite.models import RigaVendita, Vendita
from .correction_services import FIELDS_BY_TYPE
from .correction_catalog import EDITABLE_FIELDS


class CorrectionReasonForm(forms.Form):
    motivazione = forms.CharField(
        min_length=5, label="Motivazione della correzione",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    annotazione = forms.CharField(
        required=False, label="Correzione richiesta per un record storico",
        widget=forms.Textarea(attrs={"rows": 4}),
    )


def catalog_form(model, *args, **kwargs):
    fields = EDITABLE_FIELDS.get(model._meta.label, ())
    if not fields:
        return None
    return modelform_factory(model, fields=fields)(*args, **kwargs)


class ControlCorrectionForm(forms.ModelForm):
    batch_associati = forms.ModelMultipleChoiceField(
        queryset=ControlloSessioneSemplificata.objects.none(), required=False,
        label="Batch associati", widget=forms.CheckboxSelectMultiple,
    )
    motivazione = forms.CharField(
        label="Motivazione della correzione", min_length=5,
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = ControlloSessioneSemplificata
        fields = (
            "inizio", "fine", "esito_tracciato_termico", "gradi_brix", "ph",
            "esito_pastorizzazione", "esito_shock_vuoto", "note",
        )
        widgets = {
            "inizio": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "fine": forms.DateTimeInput(format="%Y-%m-%dT%H:%M", attrs={"type": "datetime-local"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        control = self.instance
        allowed = set(FIELDS_BY_TYPE[control.tipo])
        for name in tuple(self.fields):
            if name not in allowed | {"motivazione", "batch_associati"}:
                self.fields.pop(name)
        if control.tipo == "TANK":
            self.fields["batch_associati"].queryset = control.sessione.controlli.filter(
                Q(associazione_tank__isnull=True) | Q(associazione_tank__tank=control),
                tipo="BATCH",
            ).order_by("numero")
            self.fields["batch_associati"].initial = list(
                AssociazioneTankBatch.objects.filter(tank=control).values_list("batch_id", flat=True)
            )
            self.fields["batch_associati"].label_from_instance = lambda batch: (
                f"Batch {batch.numero} · "
                f"{timezone.localtime(batch.inizio).strftime('%H:%M') if batch.inizio else 'inizio —'} / "
                f"{timezone.localtime(batch.fine).strftime('%H:%M') if batch.fine else 'fine —'}"
            )
        else:
            self.fields.pop("batch_associati")

    def clean(self):
        values = super().clean()
        if self.instance.tipo == "TANK" and not values.get("batch_associati"):
            self.add_error("batch_associati", "Associare almeno un batch al tank.")
        return values


class StockCorrectionForm(forms.Form):
    giacenza = forms.ModelChoiceField(
        queryset=Giacenza.objects.select_related("lotto__articolo", "ubicazione").order_by("-pk"),
        label="Lotto e posizione",
    )
    verso = forms.ChoiceField(choices=[("AUMENTO", "Aumento"), ("DIMINUZIONE", "Diminuzione")])
    quantita = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6)
    componente = forms.ChoiceField(
        choices=[("", "Non applicabile"), *Movimento.Componente.choices], required=False,
        label="Componente del prodotto finito",
    )
    motivazione = forms.CharField(
        min_length=5, label="Motivazione della rettifica",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["giacenza"].label_from_instance = lambda stock: (
            f"{stock.lotto.codice_lotto} · {stock.lotto.articolo.descrizione} · "
            f"{stock.ubicazione.codice}/{stock.scaffale or '-'}/{stock.piano or '-'} · "
            f"{stock.quantita} {stock.lotto.articolo.unita_misura}"
        )

    def clean(self):
        values = super().clean()
        stock = values.get("giacenza")
        if stock and stock.lotto.stato_prodotto == "PRODOTTO_FINITO" and not values.get("componente"):
            self.add_error("componente", "Scegliere confezionato o non confezionato.")
        return values


class SaleCorrectionForm(forms.ModelForm):
    motivazione = forms.CharField(
        min_length=5, label="Motivazione della correzione",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    class Meta:
        model = Vendita
        fields = ("numero_documento", "data_documento", "cliente", "note")
        widgets = {
            "data_documento": forms.DateInput(format="%Y-%m-%d", attrs={"type": "date"}),
            "note": forms.Textarea(attrs={"rows": 2}),
        }


class SalesLineCorrectionForm(forms.Form):
    nuova_quantita = forms.DecimalField(
        min_value=Decimal("0"), max_digits=18, decimal_places=6,
        label="Nuova quantità venduta",
    )
    giacenza = forms.ModelChoiceField(
        queryset=Giacenza.objects.none(), label="Posizione per la differenza",
    )
    motivazione = forms.CharField(
        min_length=5, label="Motivazione della correzione",
        widget=forms.Textarea(attrs={"rows": 3}),
    )

    def __init__(self, *args, riga: RigaVendita, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nuova_quantita"].initial = riga.quantita_effettiva
        self.fields["giacenza"].queryset = Giacenza.objects.filter(
            lotto_id=riga.movimento.lotto_id,
        ).select_related("ubicazione").order_by("ubicazione__codice", "scaffale", "piano")
        self.fields["giacenza"].label_from_instance = lambda stock: (
            f"{stock.ubicazione.codice}/{stock.scaffale or '-'}/{stock.piano or '-'} · "
            f"disponibili {stock.quantita}"
        )
