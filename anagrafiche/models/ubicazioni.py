from django.core.exceptions import ValidationError
from django.db import models, transaction

from .base import ValidatedModel


class Ubicazione(ValidatedModel):
    codice = models.CharField(max_length=40, unique=True)
    nome = models.CharField(max_length=150)
    attiva = models.BooleanField(default=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["codice"]
        verbose_name_plural = "Ubicazioni"

    def __str__(self):
        return f"{self.codice} — {self.nome}"

    def clean(self):
        super().clean()
        if self.pk and not self.attiva and self.giacenze.filter(quantita__gt=0).exists():
            raise ValidationError({"attiva": "Un'ubicazione con stock positivo non può essere disattivata."})

    def save(self, *args, **kwargs):
        # Il servizio stock dovrà acquisire lo stesso lock prima di movimentare.
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().get(pk=self.pk)
            return super().save(*args, **kwargs)
