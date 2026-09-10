from django import forms
from magazzino.models import Giacenza
from produzione.models import Ricetta, RisorsaProduttiva
from .forms import amount, position_fields


class StockChoice(forms.ModelMultipleChoiceField):
    def label_from_instance(self, stock):
        return f"{stock.lotto.codice_lotto} · {stock.lotto.articolo.descrizione} · {stock.ubicazione} / {stock.scaffale or '—'} / {stock.piano or '—'} · {stock.quantita.normalize()} KG"


class TankSelectionForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)
    proposta = forms.CharField(widget=forms.HiddenInput)
    ricetta = forms.ModelChoiceField(Ricetta.objects.filter(attiva=True, articolo__attivo=True, articolo__unita_misura="KG"), label="Ricetta e versione")

    def __init__(self, *args, stocks, mode, kind=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["materiali"] = StockChoice(stocks, label="Batch da unire nel tank" if mode == "tank" else "Tank pronti da prelevare",
            widget=forms.CheckboxSelectMultiple)
        if mode == "tank":
            position_fields(self.fields, "destinazione", "Destinazione tank")
        elif mode == "session":
            qs = kind.requisiti_input.filter(articolo__unita_misura="PZ", articolo__attivo=True)
            for name, label in (("vasetti", "Vasetti utilizzati"), ("capsule", "Capsule utilizzate")):
                self.fields[name] = forms.ModelChoiceField(qs, label=label)
                self.fields[name].initial = qs.filter(nome__iexact=name).values_list("pk", flat=True).first()


class TankQualityForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)
    brix = forms.DecimalField(label="°Brix misurati · conforme se 40 < °Brix < 45", max_digits=18, decimal_places=6, localize=True)
    ph = forms.DecimalField(label="pH misurato · conforme se pH ≤ 4,1", max_digits=18, decimal_places=6, localize=True)


class CartForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)
    risorsa = forms.ModelChoiceField(RisorsaProduttiva.objects.filter(tipo="CARRELLO", attiva=True), required=False,
        label="Carrello fisico (facoltativo)", help_text="L'identificativo CRL viene assegnato automaticamente.")


class TreatmentForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)
    esito = forms.ChoiceField(label="Esito del trattamento", choices=[("", "Seleziona"), ("C", "C · Conforme"), ("NC", "NC · Non conforme"), ("NA", "NA · Non applicabile")])


class ClosureForm(forms.Form):
    vasetti_buoni = forms.IntegerField(label="Numero vasetti buoni", min_value=0, max_value=2147483647)
    vasetti_scarti = forms.IntegerField(label="Numero vasetti da scartare", min_value=0, max_value=2147483647)
    capsule_difettose = forms.IntegerField(label="Capsule difettose complessive", min_value=0, max_value=2147483647)
    peso_netto_g = amount("Peso netto del singolo vasetto · g")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        position_fields(self.fields, "destinazione", "Destinazione prodotto buono", required=False)

    def clean(self):
        d = super().clean()
        if d.get("vasetti_buoni", 0) > 0 and not d.get("destinazione"):
            self.add_error("destinazione", "Indica la destinazione dei vasetti buoni.")
        return d


class PackagingRowForm(forms.Form):
    stock = forms.ModelChoiceField(Giacenza.objects.none(), label="Lotto e posizione della confezione")
    quantita = forms.IntegerField(label="Pezzi da prelevare", min_value=1, max_value=2147483647)

    def __init__(self, *args, session, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["stock"].queryset = Giacenza.objects.filter(lotto__articolo_id__in=[session.articolo_vasetti_id, session.articolo_capsule_id],
            quantita__gt=0, ubicazione__attiva=True).select_related("lotto__articolo", "ubicazione")
        self.fields["stock"].label_from_instance = lambda stock: f"{stock.lotto.articolo.descrizione} · {stock.lotto.codice_lotto} · {stock.ubicazione} / {stock.scaffale or '—'} / {stock.piano or '—'} · disponibili {stock.quantita.normalize()} PZ"
