from django.conf import settings
from django.db import models
from django.utils import timezone

from magazzino.models.protections import HistoricalModel


class InvioOperativo(models.Model):
    """Ricevuta tecnica per rendere innocuo il reinvio dello stesso modulo."""
    id = models.UUIDField(primary_key=True, editable=False)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    percorso = models.CharField(max_length=250)
    creato_il = models.DateTimeField(auto_now_add=True)


class CorrezioneAmministrativa(HistoricalModel):
    """Valori prima/dopo di una correzione operativa autorizzata."""

    modello = models.CharField(max_length=100)
    record_id = models.CharField(max_length=50)
    valori_precedenti = models.JSONField()
    valori_nuovi = models.JSONField()
    motivazione = models.TextField()
    eseguita_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    eseguita_il = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-eseguita_il", "-pk"]

    def clean(self):
        super().clean()
        if not self.motivazione.strip():
            from django.core.exceptions import ValidationError
            raise ValidationError({"motivazione": "La motivazione è obbligatoria."})
