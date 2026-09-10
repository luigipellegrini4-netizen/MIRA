from decimal import Decimal

from django.apps import apps
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q

from anagrafiche.models.base import ValidatedModel


class RecipeQuerySet(models.QuerySet):
    def update(self, **kwargs):
        # La disattivazione non cambia la formula storica.
        if set(kwargs) != {"attiva"} or not isinstance(kwargs["attiva"], bool):
            raise ValidationError("Modificare la ricetta tramite i servizi, senza update massivi.")
        return super().update(**kwargs)

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Creare le ricette tramite i servizi.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Modificare le ricette tramite i servizi.")

    def delete(self):
        raise ValidationError("Disattivare le ricette invece di cancellarle in massa.")


class Ricetta(ValidatedModel):
    articolo = models.ForeignKey("anagrafiche.Articolo", on_delete=models.PROTECT, related_name="ricette")
    nome = models.CharField(max_length=150)
    versione = models.CharField(max_length=30)
    attiva = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    objects = RecipeQuerySet.as_manager()

    class Meta:
        ordering = ["articolo__codice", "versione", "pk"]
        verbose_name_plural = "Ricette"
        constraints = [
            models.UniqueConstraint(fields=["articolo", "versione"], name="ricetta_articolo_versione_unica"),
            models.CheckConstraint(condition=~Q(versione=""), name="ricetta_versione_non_vuota"),
        ]

    def __str__(self):
        return f"{self.nome} — v{self.versione}"

    @property
    def utilizzata(self):
        if self.pk is None:
            return False
        # Si consulta la FK reale, senza uno stato storico duplicato.
        try:
            work_model = apps.get_model("produzione", "Lavorazione")
        except LookupError:
            return False
        return work_model.objects.filter(ricetta_id=self.pk).exists()

    def ensure_formula_editable(self):
        if self.utilizzata:
            raise ValidationError("Ricetta già utilizzata: creare una nuova versione per cambiare formula.")

    def clean(self):
        super().clean()
        if not self.nome.strip() or not self.versione.strip():
            raise ValidationError("Nome e versione della ricetta sono obbligatori.")
        if self.pk and self.utilizzata:
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, name) != getattr(self, name) for name in ("articolo_id", "nome", "versione", "note")):
                raise ValidationError("Ricetta storica: è consentito soltanto modificarne l'attivazione.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                # Anche la futura pianificazione deve acquisire questo lock.
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().get(pk=self.pk)
            self.ensure_formula_editable()
            return super().delete(*args, **kwargs)


class RecipeLineQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Modificare le righe tramite RecipeService.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Creare le righe tramite RecipeService.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Modificare le righe tramite RecipeService.")

    def delete(self):
        raise ValidationError("Rimuovere le righe singolarmente tramite RecipeService.")


class RigaRicetta(ValidatedModel):
    ricetta = models.ForeignKey(Ricetta, on_delete=models.CASCADE, related_name="righe")
    categoria_articolo = models.ForeignKey("anagrafiche.CategoriaArticolo", null=True, blank=True, on_delete=models.PROTECT, related_name="righe_ricetta")
    articolo = models.ForeignKey("anagrafiche.Articolo", null=True, blank=True, on_delete=models.PROTECT, related_name="righe_ricetta")
    quantita = models.DecimalField(max_digits=18, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    note = models.TextField(blank=True)
    objects = RecipeLineQuerySet.as_manager()

    class Meta:
        ordering = ["pk"]
        verbose_name_plural = "Righe ricetta"
        constraints = [
            models.CheckConstraint(condition=Q(quantita__gt=0), name="riga_ricetta_quantita_positiva"),
            models.CheckConstraint(condition=(Q(articolo__isnull=False, categoria_articolo__isnull=True) | Q(articolo__isnull=True, categoria_articolo__isnull=False)), name="riga_ricetta_un_solo_target"),
        ]

    def __str__(self):
        return f"{self.ricetta} — {self.articolo or self.categoria_articolo}: {self.quantita}"

    def clean(self):
        super().clean()
        if (self.articolo_id is None) == (self.categoria_articolo_id is None):
            raise ValidationError("Specificare esattamente uno tra articolo e categoria.")
        if self.ricetta_id:
            self.ricetta.ensure_formula_editable()
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if old is not None and old.ricetta_id != self.ricetta_id:
                raise ValidationError("Una riga esistente non può essere spostata a un'altra ricetta.")

    def accetta_articolo(self, articolo):
        if articolo.pk is None:
            return False
        if self.articolo_id is not None:
            return self.articolo_id == articolo.pk
        if self.categoria_articolo_id is not None:
            return articolo.appartiene_a_categoria_o_discendenti(self.categoria_articolo)
        return False

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.ricetta_id:
                self.ricetta = Ricetta.objects.select_for_update().get(pk=self.ricetta_id)
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            recipe = Ricetta.objects.select_for_update().get(pk=self.ricetta_id)
            recipe.ensure_formula_editable()
            return super().delete(*args, **kwargs)
