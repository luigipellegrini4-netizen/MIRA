from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import F, Q
from django.utils import timezone

from anagrafiche.models.base import ValidatedModel
from .configurazione import TipoLavorazione
from .protections import ProtectedProductionQuerySet, _execution_writing
from .ricette import Ricetta


class CicloProduzione(ValidatedModel):
    class Stato(models.TextChoices):
        PIANIFICATO = "PIANIFICATO", "Pianificato"
        IN_CORSO = "IN_CORSO", "In corso"
        COMPLETATO = "COMPLETATO", "Completato"
        ANNULLATO = "ANNULLATO", "Annullato"

    articolo = models.ForeignKey("anagrafiche.Articolo", on_delete=models.PROTECT, related_name="cicli_produzione")
    data = models.DateField(default=timezone.localdate)
    stato = models.CharField(max_length=11, choices=Stato.choices, default=Stato.PIANIFICATO)
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="cicli_creati")
    data_chiusura = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        ordering = ["-data", "-pk"]
        verbose_name_plural = "Cicli produzione"
        constraints = [
            models.CheckConstraint(condition=Q(stato__in=["PIANIFICATO", "IN_CORSO", "COMPLETATO", "ANNULLATO"]), name="ciclo_stato_valido"),
            models.CheckConstraint(condition=Q(stato__in=["PIANIFICATO", "IN_CORSO"], data_chiusura__isnull=True) | Q(stato__in=["COMPLETATO", "ANNULLATO"], data_chiusura__isnull=False), name="ciclo_chiusura_coerente"),
        ]

    def __str__(self):
        return f"Ciclo {self.pk} — {self.articolo.codice} — {self.data}"

    def clean(self):
        super().clean()
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if old and old.stato in {self.Stato.COMPLETATO, self.Stato.ANNULLATO}:
            raise ValidationError("Un ciclo chiuso non può essere modificato.")
        previous = old.stato if old else self.Stato.PIANIFICATO
        if self.stato != previous and not _execution_writing.get():
            raise ValidationError("Le transizioni di stato richiedono ProductionCycleService.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Annullare il ciclo tramite il servizio; non cancellarlo.")


class Lavorazione(ValidatedModel):
    class Stato(models.TextChoices):
        PIANIFICATA = "PIANIFICATA", "Pianificata"
        IN_CORSO = "IN_CORSO", "In corso"
        COMPLETATA = "COMPLETATA", "Completata"
        ANNULLATA = "ANNULLATA", "Annullata"
        INTERROTTA = "INTERROTTA", "Interrotta"

    ciclo_produzione = models.ForeignKey(CicloProduzione, on_delete=models.PROTECT, related_name="lavorazioni")
    tipo_lavorazione = models.ForeignKey(TipoLavorazione, on_delete=models.PROTECT, related_name="lavorazioni")
    ricetta = models.ForeignKey(Ricetta, null=True, blank=True, on_delete=models.PROTECT, related_name="lavorazioni")
    stato = models.CharField(max_length=11, choices=Stato.choices, default=Stato.PIANIFICATA)
    data_ora_inizio = models.DateTimeField(null=True, blank=True)
    data_ora_fine = models.DateTimeField(null=True, blank=True)
    eseguita_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="lavorazioni_eseguite")
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        ordering = ["pk"]
        verbose_name_plural = "Lavorazioni"
        constraints = [
            models.CheckConstraint(condition=Q(stato__in=["PIANIFICATA", "IN_CORSO", "COMPLETATA", "ANNULLATA", "INTERROTTA"]), name="lavorazione_stato_valido"),
            models.CheckConstraint(condition=(
                Q(stato__in=["PIANIFICATA", "ANNULLATA"], data_ora_inizio__isnull=True, data_ora_fine__isnull=True, eseguita_da__isnull=True)
                | Q(stato="IN_CORSO", data_ora_inizio__isnull=False, data_ora_fine__isnull=True, eseguita_da__isnull=False)
                | Q(stato__in=["COMPLETATA", "INTERROTTA"], data_ora_inizio__isnull=False, data_ora_fine__isnull=False, eseguita_da__isnull=False)
            ), name="lavorazione_tempi_stato"),
            models.CheckConstraint(condition=Q(data_ora_fine__isnull=True) | Q(data_ora_fine__gte=F("data_ora_inizio")), name="lavorazione_fine_dopo_inizio"),
        ]

    def __str__(self):
        return f"Lavorazione {self.pk} — {self.tipo_lavorazione.codice}"

    def clean(self):
        super().clean()
        old = type(self).objects.filter(pk=self.pk).first() if self.pk else None
        if old and old.stato in {self.Stato.COMPLETATA, self.Stato.ANNULLATA, self.Stato.INTERROTTA}:
            raise ValidationError("Una lavorazione terminata è storica e non può essere modificata.")
        previous = old.stato if old else self.Stato.PIANIFICATA
        if old and old.tipo_lavorazione.fase_operativa:
            if any(getattr(old, f) != getattr(self, f) for f in ("ciclo_produzione_id", "tipo_lavorazione_id", "ricetta_id")):
                raise ValidationError("Processo e ricetta del piano aziendale sono storici.")
        if self.stato != previous and not _execution_writing.get():
            raise ValidationError("Le transizioni richiedono WorkExecutionService.")
        if old and old.stato != self.Stato.PIANIFICATA:
            if any(getattr(old, f) != getattr(self, f) for f in ("ciclo_produzione_id", "tipo_lavorazione_id", "ricetta_id")):
                raise ValidationError("La configurazione di una lavorazione iniziata non può cambiare.")
        if not old and self.ciclo_produzione_id and self.ciclo_produzione.stato in {CicloProduzione.Stato.COMPLETATO, CicloProduzione.Stato.ANNULLATO}:
            raise ValidationError("Non si possono aggiungere lavorazioni a un ciclo chiuso.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            # Ordine richiesto anche ai servizi futuri: tipo, ricetta, ciclo, lavoro.
            if self.tipo_lavorazione_id:
                self.tipo_lavorazione = TipoLavorazione.objects.select_for_update().get(pk=self.tipo_lavorazione_id)
            if self.ricetta_id:
                self.ricetta = Ricetta.objects.select_for_update().get(pk=self.ricetta_id)
            if self.ciclo_produzione_id:
                self.ciclo_produzione = CicloProduzione.objects.select_for_update().get(pk=self.ciclo_produzione_id)
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Annullare/interrompere la lavorazione tramite il servizio.")
