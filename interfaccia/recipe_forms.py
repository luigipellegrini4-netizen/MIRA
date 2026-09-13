from django import forms
from django.forms import BaseInlineFormSet, inlineformset_factory
from anagrafiche.models import Articolo
from produzione.models import Ricetta, RigaRicetta


class RecipeForm(forms.ModelForm):
    class Meta:
        model = Ricetta
        fields = ("articolo", "nome", "versione", "attiva", "note")
        widgets = {"note": forms.Textarea(attrs={"rows": 3})}


class RecipeArticleSelect(forms.Select):
    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        if value and getattr(value, "instance", None):
            option["attrs"]["data-unit"] = value.instance.unita_misura
        return option


class RecipeLineForm(forms.ModelForm):
    class Meta:
        model = RigaRicetta
        fields = ("articolo", "quantita", "note")
        widgets = {
            "articolo": RecipeArticleSelect(attrs={"data-recipe-article": ""}),
            "quantita": forms.NumberInput(attrs={"step": "0.000001", "min": "0.000001", "data-recipe-quantity": ""}),
            "note": forms.TextInput(attrs={"placeholder": "Facoltative"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["articolo"].required = True
        self.fields["articolo"].queryset = Articolo.objects.filter(attivo=True).select_related("categoria").order_by(
            "categoria__nome", "descrizione", "codice"
        )
        self.fields["articolo"].help_text = "Scegliere un articolo preciso; le categorie generiche non sono più ammesse."
        self.fields["quantita"].label = "Quantità per batch"

    def clean(self):
        data = super().clean()
        if data.get("articolo"):
            # Converte una vecchia riga per categoria quando la ricetta è
            # ancora modificabile.
            self.instance.categoria_articolo = None
        return data


class BaseRecipeLines(BaseInlineFormSet):
    def clean(self):
        super().clean()
        if any(self.errors):
            return
        articles = {}
        active = []
        for form in self.forms:
            if not form.cleaned_data or form.cleaned_data.get("DELETE"):
                continue
            article = form.cleaned_data.get("articolo")
            quantity = form.cleaned_data.get("quantita")
            if not article or quantity is None:
                continue
            if article.pk in articles:
                form.add_error("articolo", "Questo ingrediente è già presente nella ricetta.")
                articles[article.pk].add_error("articolo", "Questo ingrediente è ripetuto.")
            else:
                articles[article.pk] = form
            active.append(form)
        if not active:
            raise forms.ValidationError("Inserire almeno un ingrediente per batch.")


RecipeLines = inlineformset_factory(
    Ricetta, RigaRicetta, form=RecipeLineForm, formset=BaseRecipeLines,
    extra=1, can_delete=True, max_num=100, validate_max=True,
)
