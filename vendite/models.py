from django.conf import settings
from django.db import models
from django.utils import timezone


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
