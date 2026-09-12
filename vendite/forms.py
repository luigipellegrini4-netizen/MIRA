from django import forms
from django.forms import formset_factory
from django.db.models import Min

from magazzino.models import Giacenza
from .models import Cliente


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ("codice", "ragione_sociale", "partita_iva", "indirizzo", "email", "telefono", "attivo")


class VenditaForm(forms.Form):
    numero_documento = forms.CharField(max_length=60, label="Numero documento")
    data_documento = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Data documento")
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.filter(attivo=True))
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


class RigaVenditaForm(forms.Form):
    giacenza = forms.ModelChoiceField(queryset=Giacenza.objects.none(), required=False, label="Lotto confezionato e posizione")
    quantita = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["giacenza"].queryset = Giacenza.objects.filter(
            quantita__gt=0, ubicazione__attiva=True,
            lotto__stato_confezionamento="CONFEZIONATO",
        ).select_related("lotto__articolo", "ubicazione").order_by("lotto__articolo__descrizione", "lotto__codice_lotto")
        self.fields["giacenza"].label_from_instance = lambda stock: (
            f"{stock.lotto.codice_lotto} · {stock.lotto.articolo.codice} — {stock.lotto.articolo.descrizione} — "
            f"{stock.ubicazione.codice}/{stock.scaffale or '-'}/{stock.piano or '-'} — {stock.quantita:g} {stock.lotto.articolo.unita_misura}"
        )

    def clean(self):
        data = super().clean()
        stock, quantity = data.get("giacenza"), data.get("quantita")
        if bool(stock) != bool(quantity):
            raise forms.ValidationError("Indicare sia il lotto sia la quantità.")
        if stock and quantity > stock.quantita:
            self.add_error("quantita", f"Disponibilità insufficiente: {stock.quantita:g}.")
        return data


RigheVenditaFormSet = formset_factory(RigaVenditaForm, extra=5, min_num=1, validate_min=True, max_num=30)
