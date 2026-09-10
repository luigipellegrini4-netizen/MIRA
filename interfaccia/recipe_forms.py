from django import forms
from django.forms import inlineformset_factory
from anagrafiche.models import Articolo, CategoriaArticolo
from produzione.models import Ricetta, RigaRicetta


class RecipeForm(forms.ModelForm):
    class Meta:
        model = Ricetta
        fields = ("articolo", "nome", "versione", "attiva", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class RecipeLineForm(forms.ModelForm):
    class Meta:
        model = RigaRicetta
        fields = ("articolo", "categoria_articolo", "quantita", "note")


RecipeLines = inlineformset_factory(Ricetta, RigaRicetta, form=RecipeLineForm, extra=1, can_delete=True)
