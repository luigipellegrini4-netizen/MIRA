from contextvars import ContextVar
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q, F
from django.utils import timezone
from anagrafiche.models.base import ValidatedModel
from magazzino.models.protections import HistoricalModel
from produzione.models.protections import ProtectedProductionQuerySet
from produzione.models import TipoLavorazione
from .rules import typed_value, evaluate

_recording = ContextVar("quality_recording", default=False)


class ParametroControllo(ValidatedModel):
    class TipoDato(models.TextChoices):
        DECIMALE = "DECIMALE", "Decimale"
        INTERO = "INTERO", "Intero"
        BOOLEANO = "BOOLEANO", "Booleano"
        TESTO = "TESTO", "Testo"
        ESITO = "ESITO", "Esito C / NC / NA"

    codice = models.CharField(max_length=60, unique=True)
    nome = models.CharField(max_length=150)
    tipo_dato = models.CharField(max_length=10, choices=TipoDato.choices)
    unita_misura = models.CharField(max_length=30, blank=True)
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        if self.pk and self.requisiti.exists():
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, f) != getattr(self, f) for f in ("codice", "nome", "tipo_dato", "unita_misura", "note")):
                raise ValidationError("Parametro già configurato: creare un nuovo parametro.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)


class ControlloRichiestoTipoLavorazione(ValidatedModel):
    tipo_lavorazione = models.ForeignKey(TipoLavorazione, on_delete=models.CASCADE, related_name="controlli_richiesti")
    parametro_controllo = models.ForeignKey(ParametroControllo, on_delete=models.PROTECT, related_name="requisiti")
    obbligatorio = models.BooleanField(default=True)
    valore_minimo = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    valore_massimo = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    minimo_esclusivo = models.BooleanField(default=False)
    massimo_esclusivo = models.BooleanField(default=False)
    funzione = models.CharField(max_length=12, blank=True, default="", choices=[
        ("", "Generico"), ("BRIX", "Brix tank"), ("PH", "pH tank"),
        ("BATCH", "Tracciato batch"), ("PAST", "Seconda pastorizzazione"), ("VUOTO", "Shock termico e vuoto")])
    valore_booleano_atteso = models.BooleanField(null=True, blank=True)
    determina_conformita = models.BooleanField(default=True)
    ordine = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        ordering = ["ordine", "pk"]
        constraints = [models.CheckConstraint(condition=Q(valore_minimo__isnull=True) | Q(valore_massimo__isnull=True) | Q(valore_minimo__lte=F("valore_massimo")), name="quality_limits_order")]

    def __str__(self):
        return f"{self.tipo_lavorazione}: {self.parametro_controllo}"

    def clean(self):
        super().clean()
        if self.tipo_lavorazione_id:
            self.tipo_lavorazione.ensure_editable()
        if self.pk:
            old = type(self).objects.filter(pk=self.pk).first()
            if old and old.tipo_lavorazione_id != self.tipo_lavorazione_id:
                raise ValidationError("Il controllo non può essere spostato ad altro tipo.")
        if not self.parametro_controllo_id:
            return
        kind = self.parametro_controllo.tipo_dato
        limits = (self.valore_minimo, self.valore_massimo)
        if kind in {"TESTO", "BOOLEANO", "ESITO"} and any(v is not None for v in limits):
            raise ValidationError("Limiti numerici incompatibili con il tipo dato.")
        if (self.minimo_esclusivo and self.valore_minimo is None) or (self.massimo_esclusivo and self.valore_massimo is None):
            raise ValidationError("Un limite esclusivo richiede il relativo valore numerico.")
        if self.valore_minimo is not None and self.valore_minimo == self.valore_massimo and (self.minimo_esclusivo or self.massimo_esclusivo):
            raise ValidationError("Intervallo di conformità vuoto.")
        if self.funzione and type(self).objects.filter(tipo_lavorazione_id=self.tipo_lavorazione_id, funzione=self.funzione).exclude(pk=self.pk).exists():
            raise ValidationError("Funzione di controllo già configurata per questo processo.")
        if kind != "BOOLEANO" and self.valore_booleano_atteso is not None:
            raise ValidationError("Valore atteso ammesso solo per booleani.")
        if kind == "INTERO" and any(v is not None and v != int(v) for v in limits):
            raise ValidationError("I limiti di un intero devono essere interi.")
        if all(v is not None for v in limits) and limits[0] > limits[1]:
            raise ValidationError("Minimo superiore al massimo.")
        if self.determina_conformita and ((kind in {"DECIMALE", "INTERO"} and all(v is None for v in limits)) or (kind == "BOOLEANO" and self.valore_booleano_atteso is None)):
            raise ValidationError("Un controllo determinante richiede un criterio di conformità.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            self.tipo_lavorazione = TipoLavorazione.objects.select_for_update().get(pk=self.tipo_lavorazione_id)
            self.parametro_controllo = ParametroControllo.objects.select_for_update().get(pk=self.parametro_controllo_id)
            if not self.parametro_controllo.attivo:
                raise ValidationError("Parametro inattivo.")
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            TipoLavorazione.objects.select_for_update().get(pk=self.tipo_lavorazione_id).ensure_editable()
            return super().delete(*args, **kwargs)


class ControlloQualita(HistoricalModel):
    lavorazione = models.ForeignKey("produzione.Lavorazione", on_delete=models.CASCADE, related_name="controlli_qualita")
    controllo_richiesto = models.ForeignKey(ControlloRichiestoTipoLavorazione, on_delete=models.PROTECT, related_name="misurazioni")
    valore_decimale = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    valore_intero = models.BigIntegerField(null=True, blank=True)
    valore_booleano = models.BooleanField(null=True, blank=True)
    valore_testo = models.TextField(blank=True)
    conforme = models.BooleanField()
    esito = models.CharField(max_length=2, blank=True, default="", choices=[("C", "Conforme"), ("NC", "Non conforme"), ("NA", "Non applicabile")])
    data_ora = models.DateTimeField(default=timezone.now, editable=False)
    eseguito_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["data_ora", "pk"]

    def clean(self):
        super().clean()
        req = self.controllo_richiesto
        if req.tipo_lavorazione_id != self.lavorazione.tipo_lavorazione_id:
            raise ValidationError("Controllo incompatibile con la lavorazione.")
        present = [(f, getattr(self, f)) for f in ("valore_decimale", "valore_intero", "valore_booleano", "valore_testo") if getattr(self, f) is not None and getattr(self, f) != ""]
        if len(present) != 1:
            raise ValidationError("Compilare esattamente un valore.")
        field, value = typed_value(req.parametro_controllo.tipo_dato, present[0][1])
        if field != present[0][0]:
            raise ValidationError("Campo valore incompatibile con il parametro.")
        expected = evaluate(req, value, self.conforme if req.parametro_controllo.tipo_dato == "TESTO" else None)
        if self.conforme != expected:
            raise ValidationError("Conformità incompatibile con il valore misurato.")
        expected_outcome = value if req.parametro_controllo.tipo_dato == "ESITO" else ("C" if expected else "NC")
        if self.esito and self.esito != expected_outcome:
            raise ValidationError("Esito incompatibile con la misura.")

    def save(self, *args, **kwargs):
        if not _recording.get():
            raise ValidationError("Registrare le misurazioni tramite QualityService.")
        return super().save(*args, **kwargs)


from .nc_models import NonConformita, AzioneNonConformita, VerificaNonConformita
