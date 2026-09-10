"""Attrezzature e unità operative: nessuna di queste entità rappresenta stock."""
from contextlib import contextmanager
from contextvars import ContextVar
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q, F
from anagrafiche.models.base import ValidatedModel
from magazzino.models.protections import HistoricalModel
from .protections import ProtectedProductionQuerySet
from .configurazione import TipoLavorazione

_unit_writing = ContextVar("mira_unit_writing", default=False)


@contextmanager
def _unit_write():
    token = _unit_writing.set(True)
    try:
        yield
    finally:
        _unit_writing.reset(token)


class RisorsaProduttiva(ValidatedModel):
    class Tipo(models.TextChoices):
        MACCHINA = "MACCHINA", "Macchina"
        TANK = "TANK", "Tank"
        CARRELLO = "CARRELLO", "Carrello"
        ALTRO = "ALTRO", "Altro"

    codice = models.CharField(max_length=60, unique=True)
    nome = models.CharField(max_length=150)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    attiva = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    def __str__(self):
        return f"{self.codice} — {self.nome}"

    def clean(self):
        super().clean()
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            used = self.unita.exists() or self.impieghi.exists()
            if old and used and any(getattr(old, f) != getattr(self, f) for f in ("codice", "nome", "tipo", "note")):
                raise ValidationError("Risorsa utilizzata: è modificabile solo attiva.")
            if not self.attiva and (self.unita.filter(stato="ATTIVA").exists() or self.impieghi.filter(lavorazione__stato="IN_CORSO").exists()):
                raise ValidationError("La risorsa è ancora impegnata.")
            from .azienda import TurnoOperativo
            if not self.attiva and TurnoOperativo.objects.filter(postazione__risorsa=self, fine__isnull=True).exists():
                raise ValidationError("Terminare il turno prima di disattivare la postazione.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            from .azienda import PostazioneLinea
            if self.pk and PostazioneLinea.objects.filter(risorsa=self).exists():
                from produzione.services.azienda_common import business_mutex
                business_mutex()
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Disattivare la risorsa invece di cancellarla.")


class RequisitoFaseUnitaTipoLavorazione(ValidatedModel):
    tipo_lavorazione = models.ForeignKey(TipoLavorazione, on_delete=models.CASCADE, related_name="fasi_unita_richieste")
    tipo_fase = models.ForeignKey(TipoLavorazione, on_delete=models.PROTECT, related_name="richiesta_per_unita")
    obbligatorio = models.BooleanField(default=True)
    ordine = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        ordering = ["ordine", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["tipo_lavorazione", "tipo_fase"], name="unit_route_unique_phase"),
            models.UniqueConstraint(fields=["tipo_lavorazione", "ordine"], name="unit_route_unique_order"),
            models.CheckConstraint(condition=~Q(tipo_lavorazione=F("tipo_fase")), name="unit_route_distinct_types"),
        ]

    def __str__(self):
        return f"{self.tipo_lavorazione}: {self.ordine} — {self.tipo_fase}"

    def clean(self):
        super().clean()
        if self.tipo_lavorazione_id:
            self.tipo_lavorazione.ensure_editable()
            if not self.tipo_lavorazione.genera_lotto:
                raise ValidationError("Il percorso appartiene al processo che genera il lotto delle unità.")
        if self.tipo_fase_id and self.tipo_fase.genera_lotto:
            raise ValidationError("Le fasi delle unità trattano il lotto senza generarne uno nuovo.")
        if self.tipo_lavorazione_id == self.tipo_fase_id:
            raise ValidationError("Origine e fase devono essere diverse.")
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if old and old.tipo_lavorazione_id != self.tipo_lavorazione_id:
                raise ValidationError("Un percorso esistente non può essere spostato.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            kinds = {k.pk: k for k in TipoLavorazione.objects.select_for_update().filter(pk__in=[self.tipo_lavorazione_id, self.tipo_fase_id]).order_by("pk")}
            if len(kinds) != 2:
                raise ValidationError("Selezionare due tipi di lavorazione esistenti e diversi.")
            self.tipo_lavorazione = kinds[self.tipo_lavorazione_id]
            self.tipo_fase = kinds[self.tipo_fase_id]
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            TipoLavorazione.objects.select_for_update().get(pk=self.tipo_lavorazione_id).ensure_editable()
            return super().delete(*args, **kwargs)


class RisorsaLavorazione(HistoricalModel):
    lavorazione = models.ForeignKey("produzione.Lavorazione", on_delete=models.CASCADE, related_name="risorse_utilizzate")
    risorsa_produttiva = models.ForeignKey(RisorsaProduttiva, on_delete=models.PROTECT, related_name="impieghi")
    note = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["lavorazione", "risorsa_produttiva"], name="work_resource_unique")]

    def clean(self):
        super().clean()
        if self.lavorazione.stato != "IN_CORSO" or not self.risorsa_produttiva.attiva:
            raise ValidationError("Sono richieste una lavorazione in corso e una risorsa attiva.")

    def save(self, *args, **kwargs):
        if not _unit_writing.get():
            raise ValidationError("Usare ResourceService.")
        return super().save(*args, **kwargs)


class UnitaLavorazione(ValidatedModel):
    class Stato(models.TextChoices):
        ATTIVA = "ATTIVA", "Attiva"
        CHIUSA = "CHIUSA", "Chiusa"

    lotto = models.ForeignKey("magazzino.Lotto", on_delete=models.PROTECT, related_name="unita_lavorazione")
    risorsa_produttiva = models.ForeignKey(RisorsaProduttiva, null=True, blank=True, on_delete=models.PROTECT, related_name="unita")
    lavorazione_origine = models.ForeignKey("produzione.Lavorazione", on_delete=models.PROTECT, related_name="unita_generate")
    codice = models.CharField(max_length=60, blank=True)
    quantita = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(0)])
    stato = models.CharField(max_length=10, choices=Stato.choices, default=Stato.ATTIVA)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        constraints = [
            models.CheckConstraint(condition=Q(quantita__isnull=True) | Q(quantita__gt=0), name="unit_quantity_positive"),
            models.CheckConstraint(condition=Q(stato__in=["ATTIVA", "CHIUSA"]), name="unit_state_valid"),
        ]

    def __str__(self):
        return self.codice or f"Unità {self.pk}"

    def clean(self):
        super().clean()
        if self.lotto.lavorazione_origine_id != self.lavorazione_origine_id or self.lotto.tipo != "PRODUZIONE":
            raise ValidationError("L'unità deve appartenere a un lotto generato dalla lavorazione origine.")
        if self.quantita is not None and self.quantita <= 0:
            raise ValidationError("La quantità deve essere positiva oppure non specificata.")

    def save(self, *args, **kwargs):
        if not _unit_writing.get():
            raise ValidationError("Usare WorkUnitService.")
        if self._state.adding:
            kwargs["force_insert"] = True
        else:
            old = type(self).objects.get(pk=self.pk)
            if old.stato != "ATTIVA" or self.stato != "CHIUSA" or any(getattr(old, f) != getattr(self, f) for f in ("lotto_id", "risorsa_produttiva_id", "lavorazione_origine_id", "codice", "quantita", "note")):
                raise ValidationError("Unità storica: unica modifica ammessa ATTIVA → CHIUSA.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Le unità operative non possono essere cancellate.")


class PartecipazioneUnitaLavorazione(HistoricalModel):
    unita_lavorazione = models.ForeignKey(UnitaLavorazione, on_delete=models.CASCADE, related_name="partecipazioni")
    lavorazione = models.ForeignKey("produzione.Lavorazione", on_delete=models.CASCADE, related_name="partecipazioni_unita")
    note = models.TextField(blank=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["unita_lavorazione", "lavorazione"], name="unit_work_unique")]

    def clean(self):
        super().clean()
        if self.unita_lavorazione.stato != "ATTIVA" or self.lavorazione.stato != "IN_CORSO":
            raise ValidationError("Sono richieste unità attiva e lavorazione in corso.")
        if self.lavorazione.tipo_lavorazione.genera_lotto or self.lavorazione_id == self.unita_lavorazione.lavorazione_origine_id:
            raise ValidationError("La partecipazione rappresenta un trattamento senza nuovo lotto.")

    def save(self, *args, **kwargs):
        if not _unit_writing.get():
            raise ValidationError("Usare WorkUnitService.")
        return super().save(*args, **kwargs)
