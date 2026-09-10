from decimal import Decimal
from django import forms
from django.core.exceptions import ValidationError
from anagrafiche.models import Articolo, Fornitore, Ubicazione
from magazzino.models import Giacenza, Lotto
from produzione.models import Ricetta, TipoLavorazione, Lavorazione, RigaRicetta, RisorsaProduttiva, UnitaLavorazione
from qualita.models import NonConformita, AzioneNonConformita


def amount(label="Quantità", required=True):
    return forms.DecimalField(label=label, min_value=Decimal(".000001"), max_digits=18,
        decimal_places=6, required=required, localize=True,
        widget=forms.TextInput(attrs={"inputmode": "decimal", "placeholder": "0,000"}))


def choice(model, label, required=True, **filters):
    return forms.ModelChoiceField(model.objects.filter(**filters), label=label, required=required)


def position_fields(fields, prefix, label, required=True):
    fields[prefix] = choice(Ubicazione, label, required, attiva=True)
    fields[prefix + "_scaffale"] = forms.CharField(label=label + " · scaffale", max_length=30, required=False)
    fields[prefix + "_piano"] = forms.CharField(label=label + " · piano", max_length=30, required=False)


def stock_label(stock):
    position = stock.ubicazione.nome
    if stock.scaffale:
        position += " · scaffale " + stock.scaffale
    if stock.piano:
        position += " · piano " + stock.piano
    return (f"{stock.lotto.codice_lotto} — {position} — "
            f"disponibili {stock.quantita:g} {stock.lotto.articolo.unita_misura}")


class StockChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, obj):
        return stock_label(obj)


class OperationForm(forms.Form):
    invio = forms.CharField(widget=forms.HiddenInput)

    def __init__(self, *args, operation, work=None, case=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.operation, self.work = operation, work
        f = self.fields
        if operation == "ricevimento":
            f["articolo"] = choice(Articolo, "Articolo", attivo=True)
            f["fornitore"] = choice(Fornitore, "Fornitore", attivo=True)
            f["codice_lotto"] = forms.CharField(label="Lotto fornitore", max_length=100, required=False,
                help_text="Obbligatorio per gli articoli con tracciabilità del lotto.")
            f["numero_ddt"] = forms.CharField(label="Numero DDT", max_length=100, required=False)
            f["data_scadenza"] = forms.DateField(label="Scadenza", required=False, widget=forms.DateInput(attrs={"type": "date"}))
            f["quantita"] = amount("Quantità ricevuta · unità dell'articolo")
            position_fields(f, "destinazione", "Destinazione")
        elif operation == "trasferimento":
            f["articolo"] = forms.ModelChoiceField(
                Articolo.objects.filter(attivo=True, lotti__giacenze__quantita__gt=0).distinct().order_by("codice"),
                label="Articolo",
                widget=forms.Select(attrs={
                    "onchange": "window.location.href=window.location.pathname+'?articolo='+encodeURIComponent(this.value)",
                }),
            )
            article_id = self.data.get("articolo") if self.is_bound else self.initial.get("articolo")
            stocks = Giacenza.objects.none()
            if str(article_id or "").isdigit():
                stocks = Giacenza.objects.filter(
                    lotto__articolo_id=article_id, quantita__gt=0, ubicazione__attiva=True,
                ).select_related("lotto__articolo", "ubicazione").order_by(
                    "lotto__data_scadenza", "lotto__codice_lotto", "ubicazione__codice", "scaffale", "piano",
                )
            f["stock"] = StockChoiceField(
                stocks, label="Lotto, ubicazione e disponibilità",
                empty_label="Seleziona lotto e posizione" if article_id else "Scegli prima l’articolo",
            )
            f["quantita"] = amount("Quantità da trasferire · unità dell'articolo")
            position_fields(f, "destinazione", "Destinazione")
        elif operation == "rettifica":
            f["ubicazione"] = forms.ModelChoiceField(
                Ubicazione.objects.filter(attiva=True, giacenze__quantita__gt=0).distinct().order_by("codice"),
                label="Ubicazione",
                widget=forms.Select(attrs={
                    "onchange": "const p=new URLSearchParams();p.set('ubicazione',this.value);window.location.search=p",
                }),
            )
            location_id = self.data.get("ubicazione") if self.is_bound else self.initial.get("ubicazione")
            shelf_value = self.data.get("scaffale") if self.is_bound else self.initial.get("scaffale")
            shelves = []
            if str(location_id or "").isdigit():
                shelves = list(Giacenza.objects.filter(
                    ubicazione_id=location_id, quantita__gt=0,
                ).order_by("scaffale").values_list("scaffale", flat=True).distinct())
            shelf_choices = [("", "Seleziona scaffale" if location_id else "Scegli prima l’ubicazione")]
            shelf_choices.extend((value or "__SENZA_SCAFFALE__", value or "Senza scaffale") for value in shelves)
            f["scaffale"] = forms.ChoiceField(
                label="Scaffale", choices=shelf_choices,
                widget=forms.Select(attrs={
                    "onchange": "const p=new URLSearchParams();p.set('ubicazione',document.getElementById('id_ubicazione').value);p.set('scaffale',this.value);window.location.search=p",
                }),
            )
            stocks = Giacenza.objects.none()
            if str(location_id or "").isdigit() and shelf_value:
                selected_shelf = "" if shelf_value == "__SENZA_SCAFFALE__" else shelf_value
                stocks = Giacenza.objects.filter(
                    ubicazione_id=location_id, scaffale=selected_shelf, quantita__gt=0,
                ).select_related("lotto__articolo", "ubicazione").order_by(
                    "lotto__articolo__codice", "lotto__data_scadenza", "lotto__codice_lotto", "piano",
                )
            f["stock"] = StockChoiceField(
                stocks, label="Lotto presente sullo scaffale",
                empty_label="Seleziona lotto e posizione" if shelf_value else "Scegli prima lo scaffale",
            )
            f["verso"] = forms.ChoiceField(label="Tipo di rettifica", choices=[("uscita", "Diminuzione"), ("entrata", "Aumento")])
            f["quantita"] = amount("Quantità · unità dell'articolo")
        elif operation == "pianifica":
            f["articolo"] = choice(Articolo, "Articolo del ciclo", attivo=True)
            f["tipo_lavorazione"] = choice(TipoLavorazione, "Processo", attivo=True)
            f["ricetta"] = choice(Ricetta, "Ricetta e versione", False, attiva=True)
            f["numero_batch"] = forms.IntegerField(label="Numero di batch", min_value=1, max_value=100, initial=1)
        elif operation in {"output", "prepara_lotto"}:
            f["requisito_output"] = forms.ModelChoiceField(work.tipo_lavorazione.requisiti_output.all(), label="Prodotto previsto")
            f["articolo"] = choice(Articolo, "Articolo prodotto", False, attivo=True)
            f["articolo"].help_text = "Per l'output principale con ricetta viene determinato automaticamente."
            f["data_scadenza"] = forms.DateField(label="Scadenza", required=False, widget=forms.DateInput(attrs={"type": "date"}))
            if operation == "output":
                f["lotto"] = forms.ModelChoiceField(work.lotti_generati.filter(outputlavorazione_records__isnull=True),
                    required=False, label="Lotto già preparato", help_text="Lascia vuoto per generare un nuovo lotto. Con un lotto preparato lascia vuota la scadenza.")
                f["quantita"] = amount("Resa reale · unità dell'articolo prodotto")
                position_fields(f, "destinazione", "Destinazione")
        elif operation in {"risorsa", "unita"}:
            f["risorsa_produttiva"] = choice(RisorsaProduttiva, "Risorsa produttiva", operation == "risorsa", attiva=True)
            if operation == "unita":
                f["lotto"] = forms.ModelChoiceField(work.lotti_generati.all(), label="Lotto della lavorazione")
                f["codice"] = forms.CharField(label="Codice unità", required=False, max_length=60)
                f["quantita"] = amount(required=False)
        elif operation in {"partecipa", "chiudi_unita"}:
            f["unita_lavorazione"] = forms.ModelChoiceField(
                UnitaLavorazione.objects.filter(stato="ATTIVA") if operation == "partecipa" else work.unita_generate.filter(stato="ATTIVA"), label="Unità di lavorazione")
        elif operation == "input":
            f["requisito_input"] = forms.ModelChoiceField(work.tipo_lavorazione.requisiti_input.all(), label="Requisito del processo")
            f["lotto"] = choice(Lotto, "Lotto")
            f["quantita"] = amount()
            position_fields(f, "origine", "Origine")
        elif operation == "controllo":
            f["controllo_richiesto"] = forms.ModelChoiceField(work.tipo_lavorazione.controlli_richiesti.select_related("parametro_controllo"), label="Controllo")
            f["valore"] = forms.CharField(label="Valore rilevato", help_text="Numero, testo, oppure sì/no per un controllo booleano.")
            f["conforme"] = forms.ChoiceField(label="Esito manuale per controlli testuali", required=False,
                choices=[("", "Calcolo automatico"), ("si", "Conforme"), ("no", "Non conforme")])
        elif operation == "nc_apri":
            f["tipo"] = forms.ChoiceField(label="Tipo", choices=NonConformita.Tipo.choices)
            f["lotto"] = choice(Lotto, "Lotto coinvolto", False)
            f["lavorazione"] = choice(Lavorazione, "Lavorazione coinvolta", False)
            f["descrizione"] = forms.CharField(label="Descrizione del problema", widget=forms.Textarea(attrs={"rows": 4}))
        elif operation == "nc_azione":
            f["tipo_azione"] = forms.ChoiceField(label="Azione", choices=AzioneNonConformita.TipoAzione.choices)
            f["descrizione"] = forms.CharField(label="Descrizione", widget=forms.Textarea(attrs={"rows": 3}))
            f["lotto"] = choice(Lotto, "Lotto (se non già associato alla NC)", False)
            f["quantita"] = amount(required=False)
            position_fields(f, "origine", "Origine", False)
            position_fields(f, "destinazione", "Destinazione", False)
            f["lavorazione"] = choice(Lavorazione, "Nuova lavorazione correttiva", False)
        elif operation == "nc_verifica":
            f["esito"] = forms.ChoiceField(label="Esito", choices=[("EFFICACE", "Efficace"), ("NON_EFFICACE", "Non efficace")])
            f["descrizione"] = forms.CharField(label="Verifica eseguita", widget=forms.Textarea(attrs={"rows": 3}))
        f["note"] = forms.CharField(label="Motivazione" if operation in {"rettifica", "interrompi", "nc_chiudi"} else "Note",
            required=operation in {"rettifica", "interrompi", "nc_chiudi"}, widget=forms.Textarea(attrs={"rows": 3}))

    def clean(self):
        data = super().clean()
        if self.operation == "trasferimento":
            stock, article = data.get("stock"), data.get("articolo")
            if stock and article and stock.lotto.articolo_id != article.pk:
                self.add_error("stock", "La posizione non appartiene all’articolo scelto.")
            if stock and data.get("quantita") and data["quantita"] > stock.quantita:
                self.add_error("quantita", f"Disponibilità insufficiente: massimo {stock.quantita:g} {stock.lotto.articolo.unita_misura}.")
        if self.operation == "rettifica":
            stock, location = data.get("stock"), data.get("ubicazione")
            shelf = data.get("scaffale")
            selected_shelf = "" if shelf == "__SENZA_SCAFFALE__" else shelf
            if stock and (not location or stock.ubicazione_id != location.pk or stock.scaffale != selected_shelf):
                self.add_error("stock", "Il lotto non appartiene all’ubicazione e allo scaffale scelti.")
            if stock and data.get("verso") == "uscita" and data.get("quantita") and data["quantita"] > stock.quantita:
                self.add_error("quantita", f"Disponibilità insufficiente: massimo {stock.quantita:g} {stock.lotto.articolo.unita_misura}.")
        if self.operation == "controllo" and data.get("controllo_richiesto") and "valore" in data:
            kind = data["controllo_richiesto"].parametro_controllo.tipo_dato
            value = data["valore"].strip()
            try:
                if kind == "BOOLEANO":
                    mapping = {"si": True, "sì": True, "true": True, "no": False, "false": False}
                    if value.lower() not in mapping:
                        raise ValueError()
                    value = mapping[value.lower()]
                elif kind == "DECIMALE":
                    value = forms.DecimalField(max_digits=18, decimal_places=6, localize=True).clean(value)
                elif kind == "INTERO":
                    value = forms.IntegerField().clean(value)
                data["valore"] = value
                data["conforme"] = {"si": True, "no": False}.get(data.get("conforme"))
            except (ValueError, ValidationError):
                self.add_error("valore", "Il valore non è valido per il tipo di controllo selezionato.")
        return data


class IngredientForm(forms.Form):
    riga_ricetta = forms.ModelChoiceField(RigaRicetta.objects.none(), label="Ingrediente della ricetta")
    lotto = forms.ModelChoiceField(Lotto.objects.none(), label="Lotto da consumare")
    quantita = amount()

    def __init__(self, *args, work, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["riga_ricetta"].queryset = work.ricetta.righe.all()
        self.fields["lotto"].queryset = Lotto.objects.select_related("articolo").all()
        position_fields(self.fields, "origine", "Ubicazione")

    def clean(self):
        data = super().clean()
        row, lot = data.get("riga_ricetta"), data.get("lotto")
        if row and lot and not row.accetta_articolo(lot.articolo):
            self.add_error("lotto", "Il lotto non corrisponde a questo ingrediente.")
        return data
