from django import forms
from django.forms import inlineformset_factory
from anagrafiche.models import Articolo
from produzione.models import Ricetta, RigaRicetta


class RecipeForm(forms.ModelForm):
    class Meta:
        model = Ricetta
        fields = ("articolo", "nome", "versione", "attiva", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class RecipeLineForm(forms.ModelForm):
    class Meta:
        model = RigaRicetta
        fields = ("articolo", "quantita", "note")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["articolo"].required = True
        self.fields["articolo"].queryset = Articolo.objects.filter(attivo=True).select_related("categoria").order_by(
            "categoria__nome", "descrizione", "codice"
        )
        self.fields["articolo"].help_text = "Scegliere un articolo preciso; le categorie generiche non sono più ammesse."

    def clean(self):
        data = super().clean()
        if data.get("articolo"):
            # Converte una vecchia riga per categoria quando la ricetta è
            # ancora modificabile.
            self.instance.categoria_articolo = None
        return data


RecipeLines = inlineformset_factory(Ricetta, RigaRicetta, form=RecipeLineForm, extra=1, can_delete=True)
