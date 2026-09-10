from django import forms
from django.db.models import Sum
from django.utils import timezone

from anagrafiche.models import Articolo, CategoriaArticolo, Ubicazione
from magazzino.models import Giacenza
from produzione.models import (ControlloSessioneSemplificata, Ricetta,
                               SessioneProduzioneSemplificata)


def recipe_queryset_for_category(code, name_match):
    categories = list(CategoriaArticolo.objects.filter(attiva=True).select_related("categoria_padre"))
    accepted = []
    for category in categories:
        chain = [category, *category.antenati()]
        if any(c.codice.upper() == code or name_match(c.nome.upper()) for c in chain):
            accepted.append(category.pk)
    return Ricetta.objects.filter(
        attiva=True, articolo__attivo=True, articolo__categoria_id__in=accepted
    ).select_related("articolo")


class OpenRoboQboForm(forms.Form):
    ricetta = forms.ModelChoiceField(queryset=Ricetta.objects.none())
    numero_batch_previsti = forms.IntegerField(min_value=1)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ricetta"].queryset = recipe_queryset_for_category(
            "PF", lambda name: "PRODOTT" in name and "FINIT" in name
        )


class OpenSemiFinishedForm(forms.Form):
    ricetta = forms.ModelChoiceField(queryset=Ricetta.objects.none())
    numero_batch_previsti = forms.IntegerField(min_value=1, label="Numero di batch previsti")
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["ricetta"].queryset = recipe_queryset_for_category(
            "SL", lambda name: "SEMILAVORAT" in name
        )


class OpenFillingForm(forms.Form):
    lotto_origine = forms.ModelChoiceField(
        label="Lotto RoboQbo",
        queryset=SessioneProduzioneSemplificata.objects.filter(tipo="ROBOQBO", stato__in=["APERTA", "CHIUSA"]).select_related("ricetta__articolo"),
    )
    igienizzazione_confermata = forms.BooleanField(label="Vasetti e capsule sono puliti e igienizzati")
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)


class PickingForm(forms.Form):
    numero_batch = forms.IntegerField(min_value=1)
    giacenza = forms.ModelChoiceField(queryset=Giacenza.objects.none(), label="Lotto e posizione")
    quantita_kg = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        if session and session.tipo == "SEMILAVORATO":
            self.fields["numero_batch"].label = "Numero lavorazione"
        self.fields["giacenza"].queryset = Giacenza.objects.filter(quantita__gt=0).select_related("lotto__articolo", "ubicazione").order_by("lotto__articolo__codice", "lotto__codice_lotto")
        self.fields["giacenza"].label_from_instance = lambda g: (
            f"{g.lotto.articolo.codice} — {g.lotto.articolo.descrizione} · lotto {g.lotto.codice_lotto} · "
            f"{g.ubicazione.codice}/{g.scaffale or '-'}-{g.piano or '-'} · disponibili {g.quantita} "
            f"{g.lotto.articolo.unita_misura} · scadenza "
            f"{g.lotto.data_scadenza.strftime('%d/%m/%Y') if g.lotto.data_scadenza else 'non indicata'}"
        )


class SemiFinishedPickingLineForm(forms.Form):
    articolo = forms.ModelChoiceField(queryset=Articolo.objects.all(), widget=forms.HiddenInput())
    giacenza = forms.ModelChoiceField(queryset=Giacenza.objects.none(), label="Lotto e posizione")
    quantita_kg = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6, label="Quantità da prelevare (kg)")
    note = forms.CharField(widget=forms.TextInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        article_id = self.data.get(self.add_prefix("articolo")) if self.is_bound else self.initial.get("articolo")
        stocks = Giacenza.objects.filter(quantita__gt=0)
        if article_id:
            stocks = stocks.filter(lotto__articolo_id=article_id)
        else:
            stocks = stocks.none()
        self.fields["giacenza"].queryset = stocks.select_related(
            "lotto__articolo", "ubicazione"
        ).order_by("lotto__data_scadenza", "lotto__codice_lotto", "pk")
        self.fields["giacenza"].label_from_instance = lambda g: (
            f"{g.lotto.articolo.codice} — {g.lotto.articolo.descrizione} · lotto {g.lotto.codice_lotto} · "
            f"{g.ubicazione.codice}/{g.scaffale or '-'}-{g.piano or '-'} · disponibili {g.quantita} kg · "
            f"scadenza {g.lotto.data_scadenza.strftime('%d/%m/%Y') if g.lotto.data_scadenza else 'non indicata'}"
        )


SemiFinishedPickingFormSet = forms.formset_factory(
    SemiFinishedPickingLineForm, extra=0, min_num=1, validate_min=True, max_num=100, validate_max=True
)


class AdditionalPickingForm(forms.Form):
    giacenza = forms.ModelChoiceField(queryset=Giacenza.objects.none(), label="Articolo, lotto e posizione")
    quantita = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6, label="Quantità da prelevare")
    note = forms.CharField(
        widget=forms.Textarea(attrs={"rows": 2}), required=False,
        help_text="Esempio: integrazione ingrediente, vasetti o capsule.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["giacenza"].queryset = Giacenza.objects.filter(
            quantita__gt=0, ubicazione__attiva=True
        ).select_related("lotto__articolo", "ubicazione").order_by(
            "lotto__articolo__descrizione", "lotto__data_scadenza", "lotto__codice_lotto", "pk"
        )
        self.fields["giacenza"].label_from_instance = lambda g: (
            f"{g.lotto.articolo.codice} — {g.lotto.articolo.descrizione} · lotto {g.lotto.codice_lotto} · "
            f"{g.ubicazione.codice}/{g.scaffale or '-'}-{g.piano or '-'} · disponibili {g.quantita} "
            f"{g.lotto.articolo.unita_misura} · scadenza "
            f"{g.lotto.data_scadenza.strftime('%d/%m/%Y') if g.lotto.data_scadenza else 'non indicata'}"
        )


class ControlForm(forms.Form):
    tipo = forms.ChoiceField(choices=[], widget=forms.Select(attrs={"data-control-type": ""}))
    numero = forms.IntegerField(min_value=1, label="Numero progressivo", widget=forms.NumberInput(attrs={"data-control-number": ""}))
    inizio = forms.TimeField(required=False, label="Ora di inizio", widget=forms.TimeInput(attrs={"type": "time"}))
    fine = forms.TimeField(required=False, label="Ora di fine", widget=forms.TimeInput(attrs={"type": "time"}))
    esito_tracciato_termico = forms.ChoiceField(
        required=False, label="Tracciato 82 °C × 60 s",
        choices=[("", "—"), ("C", "C"), ("NC", "NC"), ("NA", "NA")],
    )
    gradi_brix = forms.DecimalField(required=False, label="°Brix", max_digits=6, decimal_places=3)
    ph = forms.DecimalField(required=False, label="pH", max_digits=5, decimal_places=3)
    batch_associati = forms.ModelMultipleChoiceField(
        queryset=ControlloSessioneSemplificata.objects.none(), required=False,
        label="Batch associati", widget=forms.CheckboxSelectMultiple,
        help_text="Sono proposti soltanto i batch registrati e non ancora assegnati a un tank.",
    )
    esito_pastorizzazione = forms.ChoiceField(
        required=False, label="2ª pastorizzazione",
        choices=[("", "—"), ("C", "C"), ("NC", "NC"), ("NA", "NA")],
    )
    esito_shock_vuoto = forms.ChoiceField(
        required=False, label="Shock termico e vuoto",
        choices=[("", "—"), ("C", "C"), ("NC", "NC"), ("NA", "NA")],
    )
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, session, **kwargs):
        super().__init__(*args, **kwargs)
        choices = ([('BATCH', 'Batch'), ('TANK', 'Tank')] if session.tipo == "ROBOQBO" else [('CARRELLO', 'Carrello')])
        self.fields["tipo"].choices = choices
        initial_type = "TANK" if session.tipo == "ROBOQBO" else "CARRELLO"
        self.fields["tipo"].initial = initial_type
        next_numbers = {}
        for control_type, _label in choices:
            last_number = session.controlli.filter(tipo=control_type).order_by("-numero").values_list("numero", flat=True).first()
            next_numbers[control_type] = (last_number or 0) + 1
            self.fields["tipo"].widget.attrs[f"data-next-{control_type.lower()}"] = next_numbers[control_type]
        self.fields["numero"].initial = next_numbers[initial_type]
        self.fields["batch_associati"].queryset = session.controlli.filter(
            tipo="BATCH", associazione_tank__isnull=True,
        ).order_by("numero")
        self.fields["batch_associati"].label_from_instance = lambda control: (
            f"Batch {control.numero}"
            f" · {control.inizio.strftime('%H:%M') if control.inizio else 'inizio —'}"
            f" / {control.fine.strftime('%H:%M') if control.fine else 'fine —'}"
            f" · {'C' if control.conforme else 'NC'}"
        )
        field_types = {
            "inizio": "BATCH",
            "fine": "BATCH",
            "esito_tracciato_termico": "BATCH",
            "gradi_brix": "TANK",
            "ph": "TANK",
            "batch_associati": "TANK",
            "esito_pastorizzazione": "CARRELLO",
            "esito_shock_vuoto": "CARRELLO",
        }
        for field_name, control_type in field_types.items():
            self.fields[field_name].widget.attrs["data-control-for"] = control_type

    def clean(self):
        data = super().clean()
        if data.get("tipo") == "TANK" and not data.get("batch_associati"):
            self.add_error("batch_associati", "Associare almeno un batch al tank.")
        return data


class BatchControlLineForm(forms.Form):
    numero = forms.IntegerField(min_value=1, widget=forms.HiddenInput())
    inizio = forms.TimeField(required=False, label="Ora inizio", widget=forms.TimeInput(attrs={"type": "time"}))
    fine = forms.TimeField(required=False, label="Ora fine", widget=forms.TimeInput(attrs={"type": "time"}))
    esito_tracciato_termico = forms.ChoiceField(
        required=False, label="Tracciato 82 °C × 60 secondi",
        choices=[("", "—"), ("C", "C"), ("NC", "NC"), ("NA", "NA")],
    )


BatchControlFormSet = forms.formset_factory(
    BatchControlLineForm, extra=0, min_num=1, validate_min=True, max_num=500, validate_max=True
)


class NCForm(forms.Form):
    descrizione = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}))
    controllo = forms.ModelChoiceField(queryset=None, required=False)
    quantita_coinvolta_kg = forms.DecimalField(required=False, min_value=0.000001, max_digits=18, decimal_places=6)
    vasetti_coinvolti = forms.IntegerField(required=False, min_value=1)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, session, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["controllo"].queryset = session.controlli.all()


class SimpleNCTakeChargeForm(forms.Form):
    note = forms.CharField(label="Note di presa in carico", widget=forms.Textarea(attrs={"rows": 3}), required=False)


class SimpleNCActionForm(forms.Form):
    descrizione = forms.CharField(label="Azione eseguita", widget=forms.Textarea(attrs={"rows": 4}))
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class SimpleNCVerificationForm(forms.Form):
    esito = forms.ChoiceField(label="Esito", choices=[("EFFICACE", "Efficace"), ("NON_EFFICACE", "Non efficace")])
    descrizione = forms.CharField(label="Verifica eseguita", widget=forms.Textarea(attrs={"rows": 4}))
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)


class SimpleNCCloseForm(forms.Form):
    note = forms.CharField(label="Motivazione di chiusura", widget=forms.Textarea(attrs={"rows": 4}))


class SummaryForm(forms.Form):
    vasetti_buoni = forms.IntegerField(min_value=0)
    vasetti_scartati = forms.IntegerField(min_value=0)
    vasetti_quarantena = forms.IntegerField(min_value=0)
    capsule_difettose = forms.IntegerField(min_value=0)
    peso_netto_g = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6)


class SemiFinishedSummaryForm(forms.Form):
    quantita_finale_kg = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6, label="Quantità finale ottenuta (kg)")
    data_scadenza = forms.DateField(
        label="Data di scadenza",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    destinazione = forms.ModelChoiceField(queryset=Ubicazione.objects.none(), label="Ubicazione finale")
    scaffale = forms.CharField(required=False, max_length=30)
    piano = forms.CharField(required=False, max_length=30)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destinazione"].queryset = Ubicazione.objects.filter(attiva=True)
        self.fields["data_scadenza"].widget.attrs["min"] = timezone.localdate().isoformat()

    def clean_data_scadenza(self):
        value = self.cleaned_data["data_scadenza"]
        if value < timezone.localdate():
            raise forms.ValidationError("La scadenza non può precedere la data di produzione.")
        return value
