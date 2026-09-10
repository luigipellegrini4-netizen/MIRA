from django.conf import settings
from django.db import models


class InvioOperativo(models.Model):
    """Ricevuta tecnica per rendere innocuo il reinvio dello stesso modulo."""
    id = models.UUIDField(primary_key=True, editable=False)
    utente = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    percorso = models.CharField(max_length=250)
    creato_il = models.DateTimeField(auto_now_add=True)
