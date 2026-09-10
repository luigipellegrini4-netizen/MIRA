from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models

_execution_writing = ContextVar("mira_execution_writing", default=False)


@contextmanager
def _execution_write():
    """Riservato ai servizi di esecuzione della fase 6 e ai test di schema."""
    token = _execution_writing.set(True)
    try:
        yield
    finally:
        _execution_writing.reset(token)


class ProtectedProductionQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Usare i servizi produzione; aggiornamenti massivi non consentiti.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Usare i servizi produzione.")

    def bulk_update(self, *args, **kwargs):
        raise ValidationError("Usare i servizi produzione.")

    def delete(self):
        raise ValidationError("Lo storico produttivo non è cancellabile in massa.")
