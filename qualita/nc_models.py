from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone
from anagrafiche.models.base import ValidatedModel
from magazzino.models.protections import HistoricalModel
from produzione.models.protections import ProtectedProductionQuerySet
from .nc_protections import _nc_writing


class NonConformita(ValidatedModel):
    class Tipo(models.TextChoices):
        INTERNA = "INTERNA", "Interna"
        FORNITORE = "FORNITORE", "Fornitore"
        CLIENTE = "CLIENTE", "Cliente"
        ALTRO = "ALTRO", "Altro"

    class Stato(models.TextChoices):
        APERTA = "APERTA", "Aperta"
        IN_GESTIONE = "IN_GESTIONE", "In gestione"
        CHIUSA = "CHIUSA", "Chiusa"

    numero = models.PositiveBigIntegerField(unique=True, editable=False)
    data_ora_apertura = models.DateTimeField(default=timezone.now, editable=False)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.INTERNA)
    descrizione = models.TextField()
    stato = models.CharField(max_length=12, choices=Stato.choices, default=Stato.APERTA)
    lotto = models.ForeignKey("magazzino.Lotto", null=True, blank=True, on_delete=models.PROTECT, related_name="non_conformita")
    lavorazione = models.ForeignKey("produzione.Lavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="non_conformita")
    controllo_qualita = models.ForeignKey("qualita.ControlloQualita", null=True, blank=True, on_delete=models.PROTECT, related_name="non_conformita")
    risorsa_produttiva = models.ForeignKey("produzione.RisorsaProduttiva", null=True, blank=True, on_delete=models.PROTECT, related_name="non_conformita")
    aperta_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="nc_aperte")
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        ordering = ["-numero"]
        verbose_name_plural = "Non conformità"
        constraints = [
            models.CheckConstraint(condition=Q(numero__gt=0), name="nc_numero_positivo"),
            models.CheckConstraint(condition=Q(stato__in=["APERTA", "IN_GESTIONE", "CHIUSA"]), name="nc_stato_valido"),
        ]

    def __str__(self):
        return f"NC {self.numero} — {self.stato}"

    def clean(self):
        super().clean()
        if not self.descrizione.strip():
            raise ValidationError("La descrizione della NC è obbligatoria.")
        if self.controllo_qualita_id and self.lavorazione_id != self.controllo_qualita.lavorazione_id:
            raise ValidationError("Il controllo qualità deve appartenere alla lavorazione indicata.")

    def save(self, *args, **kwargs):
        if not _nc_writing.get():
            raise ValidationError("Usare NonConformityService.")
        if self._state.adding:
            kwargs["force_insert"] = True
            if self.stato != "APERTA":
                raise ValidationError("La NC nasce APERTA.")
        else:
            old = type(self).objects.get(pk=self.pk)
            allowed = {("APERTA", "IN_GESTIONE"), ("IN_GESTIONE", "CHIUSA")}
            if (old.stato, self.stato) not in allowed:
                raise ValidationError("Transizione NC non consentita.")
            fields = [f.attname for f in self._meta.concrete_fields if f.name not in {"stato", "note"}]
            if any(getattr(old, f) != getattr(self, f) for f in fields) or not self.note.startswith(old.note):
                raise ValidationError("I dati di apertura sono storici e non modificabili.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Le non conformità non possono essere cancellate.")


class AzioneNonConformita(HistoricalModel):
    class TipoAzione(models.TextChoices):
        QUARANTENA = "QUARANTENA", "Quarantena"
        REINTEGRO = "REINTEGRO", "Reintegro"
        SCARTO = "SCARTO", "Scarto"
        RILAVORAZIONE = "RILAVORAZIONE", "Rilavorazione"
        CORREZIONE_PROCESSO = "CORREZIONE_PROCESSO", "Correzione processo"
        ALTRO = "ALTRO", "Altro"

    non_conformita = models.ForeignKey(NonConformita, on_delete=models.CASCADE, related_name="azioni")
    data_ora = models.DateTimeField(default=timezone.now, editable=False)
    tipo_azione = models.CharField(max_length=20, choices=TipoAzione.choices)
    descrizione = models.TextField()
    movimento = models.ForeignKey("magazzino.Movimento", null=True, blank=True, on_delete=models.PROTECT, related_name="azioni_nc")
    lavorazione = models.ForeignKey("produzione.Lavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="azioni_nc")
    eseguita_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="azioni_nc_eseguite")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["data_ora", "pk"]
        constraints = [
            models.UniqueConstraint(fields=["movimento"], name="nc_azione_movimento_unico"),
            models.CheckConstraint(condition=(Q(tipo_azione__in=["QUARANTENA", "REINTEGRO", "SCARTO"], movimento__isnull=False)
                | Q(tipo_azione__in=["RILAVORAZIONE", "CORREZIONE_PROCESSO", "ALTRO"], movimento__isnull=True)), name="nc_azione_movimento_coerente"),
            models.CheckConstraint(condition=~Q(tipo_azione="RILAVORAZIONE") | Q(lavorazione__isnull=False), name="nc_rilavorazione_riferita"),
        ]

    def clean(self):
        super().clean()
        if not self.descrizione.strip():
            raise ValidationError("Descrivere l'azione eseguita.")
        if self.non_conformita.stato != "IN_GESTIONE":
            raise ValidationError("La NC deve essere IN_GESTIONE.")
        physical = self.tipo_azione in {"QUARANTENA", "REINTEGRO", "SCARTO"}
        if physical != bool(self.movimento_id):
            raise ValidationError("Le azioni fisiche richiedono un movimento, le altre no.")
        if self.movimento_id:
            movement = self.movimento
            if movement.tipo != self.tipo_azione or movement.eseguito_da_id != self.eseguita_da_id:
                raise ValidationError("Movimento incompatibile con azione o esecutore.")
            if self.non_conformita.lotto_id and movement.lotto_id != self.non_conformita.lotto_id:
                raise ValidationError("Lotto diverso da quello della NC.")
        if self.tipo_azione == "RILAVORAZIONE" and not self.lavorazione_id:
            raise ValidationError("Indicare la lavorazione correttiva.")
        if self.tipo_azione == "RILAVORAZIONE" and self.lavorazione_id == self.non_conformita.lavorazione_id:
            raise ValidationError("Una rilavorazione deve essere una nuova lavorazione, distinta da quella della NC.")

    def save(self, *args, **kwargs):
        if not _nc_writing.get():
            raise ValidationError("Usare NonConformityService.")
        return super().save(*args, **kwargs)


class VerificaNonConformita(HistoricalModel):
    class Esito(models.TextChoices):
        EFFICACE = "EFFICACE", "Efficace"
        NON_EFFICACE = "NON_EFFICACE", "Non efficace"

    non_conformita = models.ForeignKey(NonConformita, on_delete=models.CASCADE, related_name="verifiche")
    data_ora = models.DateTimeField(default=timezone.now, editable=False)
    esito = models.CharField(max_length=12, choices=Esito.choices)
    descrizione = models.TextField()
    controllo_qualita = models.ForeignKey("qualita.ControlloQualita", null=True, blank=True, on_delete=models.PROTECT, related_name="verifiche_nc")
    verificata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="verifiche_nc_eseguite")
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["data_ora", "pk"]
        constraints = [models.CheckConstraint(condition=Q(esito__in=["EFFICACE", "NON_EFFICACE"]), name="nc_verifica_esito_valido")]

    def clean(self):
        super().clean()
        if not self.descrizione.strip():
            raise ValidationError("Descrivere la verifica.")
        if self.non_conformita.stato != "IN_GESTIONE":
            raise ValidationError("La NC deve essere IN_GESTIONE.")
        if self.controllo_qualita_id and self.esito == "EFFICACE" and not self.controllo_qualita.conforme:
            raise ValidationError("Una misura non conforme non dimostra una verifica efficace.")

    def save(self, *args, **kwargs):
        if not _nc_writing.get():
            raise ValidationError("Usare NonConformityService.")
        return super().save(*args, **kwargs)
