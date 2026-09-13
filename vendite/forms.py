from django import forms
from django.forms import BaseFormSet, formset_factory
from django.db.models import Min

from magazzino.models import Giacenza
from .models import Cliente, Vendita


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ("codice", "ragione_sociale", "partita_iva", "indirizzo", "email", "telefono", "attivo")


class VenditaForm(forms.Form):
    numero_documento = forms.CharField(max_length=60, label="Numero documento")
    data_documento = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}), label="Data documento")
    cliente = forms.ModelChoiceField(queryset=Cliente.objects.filter(attivo=True))
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def clean_numero_documento(self):
        numero = self.cleaned_data["numero_documento"]
        if Vendita.objects.filter(numero_documento=numero).exists():
            raise forms.ValidationError("Esiste già una vendita con questo numero documento.")
        return numero


class SalesStockSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value and getattr(value, "instance", None):
            option["attrs"]["data-available"] = value.instance.quantita
            option["attrs"]["data-packed"] = value.instance.quantita_confezionata
            option["attrs"]["data-loose"] = value.instance.quantita_non_confezionata
            option["attrs"]["data-base-label"] = str(label)
        return option


class RigaVenditaForm(forms.Form):
    from interfaccia.forms import component_field
    componente = component_field()
    giacenza = forms.ModelChoiceField(queryset=Giacenza.objects.none(), required=False, label="Lotto confezionato e posizione", widget=SalesStockSelect(attrs={"data-sales-stock": ""}))
    quantita = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6, required=False, widget=forms.NumberInput(attrs={"step": "0.000001", "data-sales-quantity": ""}))

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["giacenza"].queryset = Giacenza.objects.filter(
            quantita__gt=0, ubicazione__attiva=True,
            lotto__stato_prodotto="PRODOTTO_FINITO",
        ).select_related("lotto__articolo", "ubicazione").order_by("lotto__articolo__descrizione", "lotto__codice_lotto")
        self.fields["giacenza"].label_from_instance = lambda stock: (
            f"{stock.lotto.codice_lotto} · {stock.lotto.articolo.codice} — {stock.lotto.articolo.descrizione} — "
            f"{stock.ubicazione.codice}/{stock.scaffale or '-'}/{stock.piano or '-'} — {stock.quantita:g} "
            f"{stock.lotto.articolo.unita_misura} — confezionati {stock.quantita_confezionata:g}"
            f" — non confezionati {stock.quantita_non_confezionata:g}"
        )

    def clean(self):
        data = super().clean()
        stock, quantity = data.get("giacenza"), data.get("quantita")
        if bool(stock) != bool(quantity):
            raise forms.ValidationError("Indicare sia il lotto sia la quantità.")
        if stock and quantity is not None and quantity > stock.quantita:
            self.add_error("quantita", f"Disponibilità insufficiente: {stock.quantita:g}.")
        if stock and not data.get("componente"):
            self.add_error("componente", "Scegliere Confezionato o Non confezionato.")
        return data


class BaseRigheVenditaFormSet(BaseFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        totals = {}
        stocks = {}
        for form in self.forms:
            stock, quantity = form.cleaned_data.get("giacenza"), form.cleaned_data.get("quantita")
            if not stock or not quantity:
                continue
            key = (stock.pk, form.cleaned_data["componente"])
            stocks[key] = stock
            totals[key] = totals.get(key, 0) + quantity
        for stock_id, total in totals.items():
            available = stocks[stock_id].quantita_confezionata if stock_id[1] == "CONFEZIONATO" else stocks[stock_id].quantita_non_confezionata
            if total > available:
                raise forms.ValidationError(
                    f"Le righe del lotto {stocks[stock_id].lotto.codice_lotto} superano la disponibilità {stock_id[1]}: {available:g}."
                )


RigheVenditaFormSet = formset_factory(RigaVenditaForm, formset=BaseRigheVenditaFormSet, extra=5, min_num=1, validate_min=True, max_num=30)
