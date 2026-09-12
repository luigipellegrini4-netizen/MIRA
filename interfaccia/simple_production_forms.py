from django import forms
from django.db.models import Min, Sum
from django.utils import timezone

from anagrafiche.models import Articolo, CategoriaArticolo, Ubicazione
from magazzino.models import Giacenza
from produzione.models import (ConfigurazioneControlloSemplificato, ControlloSessioneSemplificata, Ricetta,
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


def article_ids_for_category(code):
    categories = list(CategoriaArticolo.objects.filter(attiva=True).select_related("categoria_padre"))
    accepted = [category.pk for category in categories if any(
        ancestor.codice.upper() == code for ancestor in [category, *category.antenati()]
    )]
    return Articolo.objects.filter(attivo=True, categoria_id__in=accepted).values_list("pk", flat=True)


def stock_label(stock):
    if stock.lotto.data_scadenza:
        date_reference = f"scadenza {stock.lotto.data_scadenza.strftime('%d/%m/%Y')}"
    elif getattr(stock, "data_carico", None):
        date_reference = f"carico {timezone.localtime(stock.data_carico).strftime('%d/%m/%Y')}"
    else:
        date_reference = "carico non indicato"
    return (
        f"{stock.lotto.articolo.codice} — {stock.lotto.articolo.descrizione} · lotto {stock.lotto.codice_lotto} · "
        f"{stock.ubicazione.codice}/{stock.scaffale or '-'}-{stock.piano or '-'} · disponibili {stock.quantita} "
        f"{stock.lotto.articolo.unita_misura} · {date_reference}"
    )


class StockByArticleSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value and getattr(value, "instance", None):
            option["attrs"]["data-article"] = value.instance.lotto.articolo_id
        return option


class StockByArticleSelectMultiple(forms.SelectMultiple):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value and getattr(value, "instance", None):
            option["attrs"]["data-article"] = value.instance.lotto.articolo_id
            option["attrs"]["data-available"] = value.instance.quantita
        return option


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
        queryset=SessioneProduzioneSemplificata.objects.none(),
    )
    igienizzazione_confermata = forms.BooleanField(label="Vasetti e capsule sono puliti e igienizzati")
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 3}), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["lotto_origine"].queryset = SessioneProduzioneSemplificata.objects.filter(
            tipo="ROBOQBO", stato__in=["APERTA", "CHIUSA"], sessioni_invasettamento__isnull=True,
        ).select_related("ricetta__articolo")


class PickingForm(forms.Form):
    numero_batch = forms.IntegerField(min_value=1)
    giacenza = forms.ModelChoiceField(queryset=Giacenza.objects.none(), label="Lotto e posizione")
    quantita_kg = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6)
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, session=None, **kwargs):
        super().__init__(*args, **kwargs)
        if session and session.tipo == "SEMILAVORATO":
            self.fields["numero_batch"].label = "Numero lavorazione"
        self.fields["giacenza"].queryset = Giacenza.objects.filter(quantita__gt=0).annotate(
            data_carico=Min("lotto__ricevimenti__data_ricevimento")
        ).select_related("lotto__articolo", "ubicazione").order_by("lotto__articolo__codice", "lotto__codice_lotto")
        self.fields["giacenza"].label_from_instance = lambda g: (
            f"{g.lotto.articolo.codice} — {g.lotto.articolo.descrizione} · lotto {g.lotto.codice_lotto} · "
            f"{g.ubicazione.codice}/{g.scaffale or '-'}-{g.piano or '-'} · disponibili {g.quantita} "
            f"{g.lotto.articolo.unita_misura} · "
            f"{('scadenza ' + g.lotto.data_scadenza.strftime('%d/%m/%Y')) if g.lotto.data_scadenza else ('carico ' + timezone.localtime(g.data_carico).strftime('%d/%m/%Y')) if g.data_carico else 'carico non indicato'}"
        )


class SemiFinishedPickingLineForm(forms.Form):
    articolo = forms.ModelChoiceField(queryset=Articolo.objects.all(), widget=forms.HiddenInput())
    giacenza = forms.ModelMultipleChoiceField(
        queryset=Giacenza.objects.none(), label="Lotti e posizioni disponibili",
        widget=StockByArticleSelectMultiple(attrs={"size": 6, "data-picking-lots": ""}),
        help_text="Puoi selezionare più lotti. MIRA ripartirà tra essi la quantità indicata.",
    )
    quantita_kg = forms.DecimalField(
        min_value=0.000001, max_digits=18, decimal_places=6, label="Quantità totale da prelevare",
        widget=forms.NumberInput(attrs={"step": "0.000001", "data-picking-quantity": ""}),
    )
    note = forms.CharField(widget=forms.TextInput(), required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        article_id = self.data.get(self.add_prefix("articolo")) if self.is_bound else self.initial.get("articolo")
        stocks = Giacenza.objects.filter(quantita__gt=0)
        if article_id:
            stocks = stocks.filter(lotto__articolo_id=article_id)
        else:
            stocks = stocks.none()
        self.fields["giacenza"].queryset = stocks.annotate(
            data_carico=Min("lotto__ricevimenti__data_ricevimento")
        ).select_related(
            "lotto__articolo", "ubicazione"
        ).order_by("lotto__data_scadenza", "lotto__codice_lotto", "pk")
        self.fields["giacenza"].label_from_instance = lambda g: (
            f"{g.lotto.articolo.codice} — {g.lotto.articolo.descrizione} · lotto {g.lotto.codice_lotto} · "
            f"{g.ubicazione.codice}/{g.scaffale or '-'}-{g.piano or '-'} · disponibili {g.quantita} kg · "
            f"{('scadenza ' + g.lotto.data_scadenza.strftime('%d/%m/%Y')) if g.lotto.data_scadenza else ('carico ' + timezone.localtime(g.data_carico).strftime('%d/%m/%Y')) if g.data_carico else 'carico non indicato'}"
        )

    def clean(self):
        data = super().clean()
        article, stocks, quantity = data.get("articolo"), data.get("giacenza"), data.get("quantita_kg")
        if article and stocks and any(stock.lotto.articolo_id != article.pk for stock in stocks):
            self.add_error("giacenza", "Uno dei lotti non appartiene all’ingrediente.")
        if stocks and quantity and sum(stock.quantita for stock in stocks) < quantity:
            self.add_error("giacenza", "I lotti selezionati non coprono la quantità indicata.")
        return data


SemiFinishedPickingFormSet = forms.formset_factory(
    SemiFinishedPickingLineForm, extra=0, min_num=1, validate_min=True, max_num=100, validate_max=True,
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
        ).annotate(data_carico=Min("lotto__ricevimenti__data_ricevimento")).select_related("lotto__articolo", "ubicazione").order_by(
            "lotto__articolo__descrizione", "lotto__data_scadenza", "lotto__codice_lotto", "pk"
        )
        self.fields["giacenza"].label_from_instance = lambda g: (
            f"{g.lotto.articolo.codice} — {g.lotto.articolo.descrizione} · lotto {g.lotto.codice_lotto} · "
            f"{g.ubicazione.codice}/{g.scaffale or '-'}-{g.piano or '-'} · disponibili {g.quantita} "
            f"{g.lotto.articolo.unita_misura} · "
            f"{('scadenza ' + g.lotto.data_scadenza.strftime('%d/%m/%Y')) if g.lotto.data_scadenza else ('carico ' + timezone.localtime(g.data_carico).strftime('%d/%m/%Y')) if g.data_carico else 'carico non indicato'}"
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
        if session.tipo == "SEMILAVORATO":
            choices = [("SEMILAVORATO", "Semilavorato")]
        elif session.tipo == "ROBOQBO":
            choices = [("BATCH", "Batch"), ("TANK", "Tank")]
        else:
            choices = [("CARRELLO", "Carrello")]
        self.fields["tipo"].choices = choices
        initial_type = "TANK" if session.tipo == "ROBOQBO" else choices[0][0]
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
        field_for_code = {
            "INIZIO": "inizio", "FINE": "fine", "TRACCIATO": "esito_tracciato_termico",
            "BRIX": "gradi_brix", "PH": "ph", "PASTORIZZAZIONE": "esito_pastorizzazione",
            "SHOCK_VUOTO": "esito_shock_vuoto",
        }
        ambito_for_type = {
            "SEMILAVORATO": "SEMILAVORATO", "BATCH": "ROBOQBO_BATCH",
            "TANK": "ROBOQBO_TANK", "CARRELLO": "INVASETTAMENTO_CARRELLO",
        }
        types_for_field = {name: [] for name in field_for_code.values()}
        self.required_by_type = {control_type: [] for control_type, _label in choices}
        configurations = ConfigurazioneControlloSemplificato.objects.filter(
            attivo=True, ambito__in=[ambito_for_type[t] for t, _label in choices]
        ).order_by("ordine", "pk")
        for configuration in configurations:
            field_name = field_for_code[configuration.codice]
            control_type = next(t for t, _label in choices if ambito_for_type[t] == configuration.ambito)
            types_for_field[field_name].append(control_type)
            self.fields[field_name].label = configuration.nome
            if configuration.obbligatorio:
                self.required_by_type[control_type].append(field_name)
        types_for_field["batch_associati"] = ["TANK"] if any(t == "TANK" for t, _ in choices) else []
        for field_name, control_types in types_for_field.items():
            self.fields[field_name].widget.attrs["data-control-for"] = ",".join(control_types)

    def clean(self):
        data = super().clean()
        if data.get("tipo") == "TANK" and not data.get("batch_associati"):
            self.add_error("batch_associati", "Associare almeno un batch al tank.")
        for field_name in self.required_by_type.get(data.get("tipo"), ()):
            if data.get(field_name) in (None, ""):
                self.add_error(field_name, "Questo controllo è obbligatorio.")
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
    tipo = forms.ChoiceField(
        label="Tipo di azione", choices=[("AZIONE", "Azione documentale"), ("SCARTO", "Scarto dal magazzino")],
        widget=forms.Select(attrs={"data-nc-action-type": ""}),
    )
    descrizione = forms.CharField(label="Azione eseguita", widget=forms.Textarea(attrs={"rows": 4}))
    origine_stock = forms.ModelChoiceField(
        queryset=Giacenza.objects.none(), required=False, label="Lotto e posizione da scaricare",
        help_text="Lo scarto è disponibile quando il lotto prodotto è presente in magazzino.",
    )
    quantita = forms.DecimalField(required=False, min_value=0.000001, max_digits=18, decimal_places=6, label="Quantità da scartare")
    note = forms.CharField(widget=forms.Textarea(attrs={"rows": 2}), required=False)

    def __init__(self, *args, case, **kwargs):
        super().__init__(*args, **kwargs)
        if case.sessione.lotto_prodotto_id:
            self.fields["origine_stock"].queryset = Giacenza.objects.filter(
                lotto_id=case.sessione.lotto_prodotto_id, quantita__gt=0, ubicazione__attiva=True,
            ).select_related("lotto__articolo", "ubicazione").order_by("ubicazione__codice", "scaffale", "piano")
        self.fields["origine_stock"].label_from_instance = stock_label
        for name in ("origine_stock", "quantita"):
            self.fields[name].widget.attrs["data-nc-action-for"] = "SCARTO"

    def clean(self):
        data = super().clean()
        if data.get("tipo") == "SCARTO":
            if not data.get("origine_stock"):
                self.add_error("origine_stock", "Selezionare il lotto e la posizione.")
            if not data.get("quantita"):
                self.add_error("quantita", "Indicare la quantità da scartare.")
            elif data.get("origine_stock") and data["quantita"] > data["origine_stock"].quantita:
                self.add_error("quantita", f"Disponibilità insufficiente: massimo {data['origine_stock'].quantita:g}.")
        return data


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

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        moca_ids = article_ids_for_category("MOCA")
        stocks = Giacenza.objects.filter(
            quantita__gt=0, ubicazione__attiva=True, lotto__articolo_id__in=moca_ids,
        ).annotate(data_carico=Min("lotto__ricevimenti__data_ricevimento")).select_related("lotto__articolo", "ubicazione").order_by("lotto__articolo__descrizione", "lotto__data_scadenza", "pk")
        articles = Articolo.objects.filter(pk__in=moca_ids, lotti__giacenze__quantita__gt=0).distinct()
        for prefix, label in (("vasetti", "Vasetti"), ("capsule", "Capsule")):
            self.fields[f"{prefix}_articolo"] = forms.ModelChoiceField(
                queryset=articles, label=f"Tipo di {label.lower()}", widget=forms.Select(attrs={"data-stock-article": prefix})
            )
            self.fields[f"{prefix}_giacenza"] = forms.ModelMultipleChoiceField(
                queryset=stocks, label=f"Lotti e posizioni {label.lower()}",
                widget=StockByArticleSelectMultiple(attrs={"data-stock-for": prefix, "size": 6}),
                help_text=f"Seleziona uno o più lotti. MIRA li scaricherà nell’ordine proposto fino a coprire la quantità necessaria.",
            )
            self.fields[f"{prefix}_giacenza"].label_from_instance = stock_label

    def clean(self):
        data = super().clean()
        for prefix in ("vasetti", "capsule"):
            article, stocks = data.get(f"{prefix}_articolo"), data.get(f"{prefix}_giacenza")
            if article and stocks and any(stock.lotto.articolo_id != article.pk for stock in stocks):
                self.add_error(f"{prefix}_giacenza", "Uno dei lotti non appartiene al tipo MOCA selezionato.")
        if data.get("vasetti_articolo") and data.get("vasetti_articolo") == data.get("capsule_articolo"):
            self.add_error("capsule_articolo", "Vasetti e capsule devono essere articoli distinti.")
        if sum(data.get(field) or 0 for field in ("vasetti_buoni", "vasetti_scartati", "vasetti_quarantena")) == 0:
            self.add_error("vasetti_buoni", "Indicare almeno un vasetto prodotto.")
        jars = sum(data.get(field) or 0 for field in ("vasetti_buoni", "vasetti_scartati", "vasetti_quarantena"))
        caps = jars + (data.get("capsule_difettose") or 0)
        for prefix, required in (("vasetti", jars), ("capsule", caps)):
            stocks = data.get(f"{prefix}_giacenza")
            if stocks and sum(stock.quantita for stock in stocks) < required:
                self.add_error(f"{prefix}_giacenza", f"I lotti selezionati non coprono la quantità richiesta: {required} PZ.")
        return data


class SemiFinishedSummaryForm(forms.Form):
    quantita_finale_kg = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6, label="Quantità finale ottenuta (kg)")
    data_scadenza = forms.DateField(
        label="Data di scadenza",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
    destinazione = forms.ModelChoiceField(queryset=Ubicazione.objects.none(), label="Ubicazione finale")
    scaffale = forms.CharField(required=False, max_length=30)
    piano = forms.CharField(required=False, max_length=30)
    moca_articolo = forms.ModelChoiceField(queryset=Articolo.objects.none(), label="Tipo di MOCA", widget=forms.Select(attrs={"data-stock-article": "moca"}))
    moca_giacenza = forms.ModelMultipleChoiceField(
        queryset=Giacenza.objects.none(), label="Lotti e posizioni MOCA",
        widget=StockByArticleSelectMultiple(attrs={"data-stock-for": "moca", "size": 6}),
        help_text="Seleziona uno o più lotti. MIRA li scaricherà nell’ordine proposto fino alla quantità indicata.",
    )
    moca_quantita = forms.DecimalField(min_value=0.000001, max_digits=18, decimal_places=6, label="Quantità MOCA da prelevare")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["destinazione"].queryset = Ubicazione.objects.filter(attiva=True)
        self.fields["data_scadenza"].widget.attrs["min"] = timezone.localdate().isoformat()
        moca_ids = article_ids_for_category("MOCA")
        self.fields["moca_articolo"].queryset = Articolo.objects.filter(
            pk__in=moca_ids, lotti__giacenze__quantita__gt=0
        ).distinct()
        self.fields["moca_giacenza"].queryset = Giacenza.objects.filter(
            quantita__gt=0, ubicazione__attiva=True, lotto__articolo_id__in=moca_ids,
        ).annotate(data_carico=Min("lotto__ricevimenti__data_ricevimento")).select_related("lotto__articolo", "ubicazione").order_by("lotto__articolo__descrizione", "lotto__data_scadenza", "pk")
        self.fields["moca_giacenza"].label_from_instance = stock_label

    def clean_data_scadenza(self):
        value = self.cleaned_data["data_scadenza"]
        if value < timezone.localdate():
            raise forms.ValidationError("La scadenza non può precedere la data di produzione.")
        return value

    def clean(self):
        data = super().clean()
        article, stocks = data.get("moca_articolo"), data.get("moca_giacenza")
        if article and stocks and any(stock.lotto.articolo_id != article.pk for stock in stocks):
            self.add_error("moca_giacenza", "Uno dei lotti non appartiene al tipo MOCA selezionato.")
        if stocks and data.get("moca_quantita") and sum(stock.quantita for stock in stocks) < data["moca_quantita"]:
            self.add_error("moca_giacenza", "I lotti selezionati non coprono la quantità MOCA indicata.")
        return data
