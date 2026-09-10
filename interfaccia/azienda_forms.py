from django import forms
from produzione.models import Ricetta
from .forms import amount, position_fields, IngredientForm
from anagrafiche.models import Articolo, CategoriaArticolo


class ConfiguraLineeForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)
    categoria_semilavorati = forms.ModelChoiceField(CategoriaArticolo.objects.filter(attiva=True), label="Categoria dei semilavorati")
    categoria_output = forms.ModelChoiceField(CategoriaArticolo.objects.filter(attiva=True), label="Categoria delle confetture")
    articolo_vasetti = forms.ModelChoiceField(Articolo.objects.filter(attivo=True, unita_misura="PZ"), label="Articolo vasetti · PZ")
    articolo_capsule = forms.ModelChoiceField(Articolo.objects.filter(attivo=True, unita_misura="PZ"), label="Articolo capsule · PZ")

    def clean(self):
        data = super().clean()
        if data.get("articolo_vasetti") and data.get("articolo_vasetti") == data.get("articolo_capsule"):
            self.add_error("articolo_capsule", "Vasetti e capsule devono essere due articoli distinti.")
        return data


class AziendaActionForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, operation, **kwargs):
        super().__init__(*args, **kwargs)
        if operation == "igienizzazione":
            self.fields["confermato"] = forms.BooleanField(label="Confermo che vasetti e capsule sono puliti e igienizzati")
        elif operation == "piano":
            self.fields["ricetta"] = forms.ModelChoiceField(Ricetta.objects.filter(attiva=True, articolo__attivo=True,
                articolo__unita_misura="KG").select_related("articolo"), label="Ricetta e versione")
            self.fields["numero_batch"] = forms.IntegerField(label="Quanti batch vuoi produrre?", min_value=1, max_value=1000, initial=1)
        elif operation == "controllo_batch":
            self.fields["esito"] = forms.ChoiceField(label="Tracciato di conformità 82 °C × 60 secondi", choices=[
                ("", "Seleziona l'esito"), ("C", "C · Conforme"), ("NC", "NC · Non conforme"), ("NA", "NA · Non applicabile")])
        elif operation == "fine_batch":
            position_fields(self.fields, "destinazione", "Destinazione del prodotto")
        elif operation == "fine_semilavorato":
            self.fields["quantita"] = amount("Semilavorato ottenuto · KG")
            position_fields(self.fields, "destinazione", "Destinazione del prodotto")


class PianoConfermaForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)
    stato_piano = forms.CharField(widget=forms.HiddenInput)
    motivo = forms.CharField(label="Conferma o motivo della revisione", max_length=1000,
        widget=forms.Textarea(attrs={"rows": 2}))


class PianoIngredientForm(IngredientForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lotto"].label = "Lotto previsto"


class BatchPrelievoForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)
    proposta = forms.CharField(widget=forms.HiddenInput)
    confermato = forms.BooleanField(label="Confermo il prelievo dei materiali e delle quantità riportati")
