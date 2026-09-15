from django.conf import settings
from django.db import models
from django.utils import timezone
from django.db.models import Sum

from magazzino.models.protections import HistoricalModel


class Cliente(models.Model):
    codice = models.CharField(max_length=40, unique=True)
    ragione_sociale = models.CharField(max_length=180)
    partita_iva = models.CharField(max_length=20, blank=True)
    indirizzo = models.CharField(max_length=250, blank=True)
    email = models.EmailField(blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["ragione_sociale", "codice"]

    def __str__(self):
        return f"{self.codice} — {self.ragione_sociale}"


class Vendita(models.Model):
    numero_documento = models.CharField(max_length=60, unique=True)
    data_documento = models.DateField(default=timezone.localdate)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="vendite")
    note = models.TextField(blank=True)
    registrata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrata_il = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-data_documento", "-pk"]

    def __str__(self):
        return f"{self.numero_documento} — {self.cliente}"


class RigaVendita(models.Model):
    vendita = models.ForeignKey(Vendita, on_delete=models.PROTECT, related_name="righe")
    movimento = models.OneToOneField("magazzino.Movimento", on_delete=models.PROTECT, related_name="riga_vendita")

    class Meta:
        ordering = ["pk"]

    @property
    def quantita_effettiva(self):
        from decimal import Decimal
        difference = self.rettifiche.aggregate(total=Sum("differenza"))["total"] or Decimal("0")
        return self.movimento.quantita + difference


class RettificaRigaVendita(HistoricalModel):
    """Correzione di quantità che conserva movimento e riga originali."""

    riga = models.ForeignKey(RigaVendita, on_delete=models.PROTECT, related_name="rettifiche")
    movimento = models.OneToOneField("magazzino.Movimento", on_delete=models.PROTECT, related_name="rettifica_riga_vendita")
    differenza = models.DecimalField(max_digits=18, decimal_places=6)
    motivazione = models.TextField()
    eseguita_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    eseguita_il = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-eseguita_il", "-pk"]
        constraints = [models.CheckConstraint(condition=~models.Q(differenza=0), name="rettifica_vendita_non_zero")]

    def clean(self):
        super().clean()
        from django.core.exceptions import ValidationError
        if not self.motivazione.strip():
            raise ValidationError({"motivazione": "La motivazione è obbligatoria."})
        if self.movimento_id and self.riga_id:
            if self.movimento.lotto_id != self.riga.movimento.lotto_id:
                raise ValidationError("La rettifica deve usare lo stesso lotto della riga venduta.")
            expected = "VENDITA" if self.differenza > 0 else "RETTIFICA"
            if self.movimento.tipo != expected or self.movimento.quantita != abs(self.differenza):
                raise ValidationError("Il movimento non coincide con la differenza di vendita.")
