"""Barriere ORM: gli scrittori interni sono riservati ai servizi espliciti.

Non è una barriera contro SQL arbitrario di un amministratore del database.
"""
from contextlib import contextmanager
from contextvars import ContextVar

from django.core.exceptions import ValidationError
from django.db import models

_writing_stock = ContextVar("mira_writing_stock", default=False)


@contextmanager
def _stock_write():
    """Solo MovementService (fase 3), nella propria transaction.atomic."""
    token = _writing_stock.set(True)
    try:
        yield
    finally:
        _writing_stock.reset(token)


class HistoricalQuerySet(models.QuerySet):
    def update(self, **kwargs):
        raise ValidationError("Lo storico non può essere modificato direttamente.")

    def delete(self):
        raise ValidationError("Lo storico non può essere cancellato.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Usare i servizi applicativi per registrare lo storico.")


class HistoricalModel(models.Model):
    objects = HistoricalQuerySet.as_manager()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("Registrazione storica: correzione solo tramite operazione tracciata.")
        self.full_clean()
        # Impedisce che un'istanza nuova con PK esplicita sovrascriva lo storico.
        kwargs["force_insert"] = True
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Lo storico non può essere cancellato.")


class StockQuerySet(models.QuerySet):
    def update(self, **kwargs):
        if not _writing_stock.get():
            raise ValidationError("Giacenza modificabile soltanto da MovementService.")
        return super().update(**kwargs)

    def delete(self):
        raise ValidationError("Le giacenze non vengono cancellate.")

    def bulk_create(self, *args, **kwargs):
        raise ValidationError("Giacenza creabile soltanto da MovementService.")
