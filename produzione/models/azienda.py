"""Flusso aziendale opt-in. Configurazioni e registrazioni restano distinte."""
from contextlib import contextmanager
from contextvars import ContextVar
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q
from django.utils import timezone
from anagrafiche.models.base import ValidatedModel
from .protections import ProtectedProductionQuerySet

_writing = ContextVar("mira_azienda_writing", default=False)
_scope = ContextVar("mira_azienda_scope", default=frozenset())


@contextmanager
def azienda_write(*work_ids):
    write = _writing.set(True)
    scope = _scope.set(_scope.get() | frozenset(work_ids))
    try:
        yield
    finally:
        _scope.reset(scope)
        _writing.reset(write)


def in_scope(work_id):
    return work_id in _scope.get()


class RegistroAziendale(ValidatedModel):
    objects = ProtectedProductionQuerySet.as_manager()
    mutable_fields = frozenset()

    class Meta:
        abstract = True

    def save(self, *args, **kwargs):
        if not _writing.get():
            raise ValidationError("Usare i servizi del flusso aziendale.")
        if self._state.adding:
            kwargs["force_insert"] = True
        else:
            old = type(self).objects.get(pk=self.pk)
            for field in self._meta.concrete_fields:
                if field.attname not in self.mutable_fields and getattr(old, field.attname) != getattr(self, field.attname):
                    raise ValidationError("Registrazione aziendale storica non modificabile.")
            if not self.mutable_fields:
                raise ValidationError("Registrazione aziendale immutabile.")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Lo storico aziendale non si cancella.")


class LineaProduttiva(ValidatedModel):
    codice = models.CharField(max_length=40, unique=True)
    nome = models.CharField(max_length=150)
    tipo_batch = models.ForeignKey("produzione.TipoLavorazione", on_delete=models.PROTECT, related_name="linee_batch")
    tipo_tank = models.ForeignKey("produzione.TipoLavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="linee_tank")
    tipo_invasettamento = models.ForeignKey("produzione.TipoLavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="linee_invasettamento")
    tipo_pastorizzazione = models.ForeignKey("produzione.TipoLavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="linee_pastorizzazione")
    tipo_vuoto = models.ForeignKey("produzione.TipoLavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="linee_vuoto")
    attiva = models.BooleanField(default=True)
    objects = ProtectedProductionQuerySet.as_manager()

    def __str__(self):
        return self.nome

    def clean(self):
        super().clean()
        if self.tipo_batch_id and self.tipo_batch.fase_operativa not in {"SEMILAVORATO", "ROBOQBO"}:
            raise ValidationError("Il processo batch deve essere semilavorati o RoboQbo.")
        for name, phase in (("tipo_tank", "TANK"), ("tipo_invasettamento", "INVASETTAMENTO"), ("tipo_pastorizzazione", "PASTORIZZAZIONE"), ("tipo_vuoto", "VUOTO")):
            if getattr(self, name + "_id") and getattr(self, name).fase_operativa != phase:
                raise ValidationError(f"Fase incompatibile: {name}.")
        if self.pk and self.postazioni.exists():
            if not self.attiva and TurnoOperativo.objects.filter(postazione__linea=self, fine__isnull=True).exists():
                raise ValidationError("Terminare i turni prima di disattivare la linea.")
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, f.attname) != getattr(self, f.attname) for f in self._meta.concrete_fields if f.name != "attiva"):
                raise ValidationError("Linea già configurata: creare una nuova linea per cambiare percorso.")

    def save(self, *args, **kwargs):
        from produzione.services.azienda_common import business_mutex
        with transaction.atomic():
            business_mutex()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Disattivare la linea invece di cancellarla.")


class PostazioneLinea(ValidatedModel):
    linea = models.ForeignKey(LineaProduttiva, on_delete=models.PROTECT, related_name="postazioni")
    risorsa = models.OneToOneField("produzione.RisorsaProduttiva", on_delete=models.PROTECT, related_name="postazione_linea")
    ruolo = models.CharField(max_length=20, choices=[("BATCH", "Batch / semilavorati"), ("INVASETTAMENTO", "Invasettamento")])
    objects = ProtectedProductionQuerySet.as_manager()

    def __str__(self):
        return f"{self.linea}: {self.risorsa}"

    def clean(self):
        super().clean()
        if self.linea_id and self.ruolo == "INVASETTAMENTO" and not self.linea.tipo_invasettamento_id:
            raise ValidationError("La linea non prevede invasettamento.")
        if self.pk and self.turni.exists():
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, f) != getattr(self, f) for f in ("linea_id", "risorsa_id", "ruolo")):
                raise ValidationError("Postazione utilizzata: configurazione storica.")

    def save(self, *args, **kwargs):
        from produzione.services.azienda_common import business_mutex
        with transaction.atomic():
            business_mutex()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Le postazioni configurate non si cancellano.")


class TurnoOperativo(RegistroAziendale):
    postazione = models.ForeignKey(PostazioneLinea, on_delete=models.PROTECT, related_name="turni")
    operatore = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="turni_operativi")
    postazione_attiva = models.OneToOneField(PostazioneLinea, null=True, blank=True, on_delete=models.PROTECT, related_name="turno_attivo")
    operatore_attivo = models.OneToOneField(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="turno_attivo_mira")
    inizio = models.DateTimeField(default=timezone.now)
    fine = models.DateTimeField(null=True, blank=True)
    igienizzazione_confermata_il = models.DateTimeField(null=True, blank=True)
    mutable_fields = frozenset({"fine", "postazione_attiva_id", "operatore_attivo_id", "igienizzazione_confermata_il"})

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(fine__isnull=True, postazione_attiva__isnull=False, operatore_attivo__isnull=False) | Q(fine__isnull=False, postazione_attiva__isnull=True, operatore_attivo__isnull=True), name="turno_attivita_coerente")]

    def clean(self):
        super().clean()
        if self.fine is None and (self.postazione_attiva_id != self.postazione_id or self.operatore_attivo_id != self.operatore_id):
            raise ValidationError("Turno attivo incoerente.")
        if self.fine and self.fine < self.inizio:
            raise ValidationError("Fine turno precedente all'inizio.")


class PianoProduzione(RegistroAziendale):
    postazione = models.ForeignKey(PostazioneLinea, on_delete=models.PROTECT, related_name="piani")
    ricetta = models.ForeignKey("produzione.Ricetta", on_delete=models.PROTECT, related_name="piani_aziendali")
    ciclo = models.OneToOneField("produzione.CicloProduzione", on_delete=models.PROTECT, related_name="piano_aziendale")
    numero_batch = models.PositiveIntegerField()
    creato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    creato_il = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(numero_batch__gt=0), name="piano_batch_positivo")]


class BatchPiano(RegistroAziendale):
    piano = models.ForeignKey(PianoProduzione, on_delete=models.PROTECT, related_name="batch")
    lavorazione = models.OneToOneField("produzione.Lavorazione", on_delete=models.PROTECT, related_name="batch_piano")
    numero = models.PositiveIntegerField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=["piano", "numero"], name="batch_numero_per_piano")]


class RevisionePrelievo(RegistroAziendale):
    piano = models.ForeignKey(PianoProduzione, on_delete=models.PROTECT, related_name="revisioni")
    numero = models.PositiveIntegerField()
    motivo = models.TextField()
    confermata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    confermata_il = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["piano", "numero"], name="revisione_numero_per_piano")]


class RigaPianoPrelievo(RegistroAziendale):
    revisione = models.ForeignKey(RevisionePrelievo, on_delete=models.PROTECT, related_name="righe")
    riga_ricetta = models.ForeignKey("produzione.RigaRicetta", on_delete=models.PROTECT)
    lotto = models.ForeignKey("magazzino.Lotto", on_delete=models.PROTECT)
    ubicazione = models.ForeignKey("anagrafiche.Ubicazione", on_delete=models.PROTECT)
    scaffale = models.CharField(max_length=30, blank=True)
    piano = models.CharField(max_length=30, blank=True)
    quantita = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        ordering = ["pk"]
        constraints = [models.CheckConstraint(condition=Q(quantita__gt=0), name="riga_piano_quantita_positiva")]


class PrelievoDaPiano(RegistroAziendale):
    riga_piano = models.ForeignKey(RigaPianoPrelievo, on_delete=models.PROTECT, related_name="prelievi")
    input = models.OneToOneField("produzione.InputLavorazione", on_delete=models.PROTECT, related_name="prelievo_pianificato")


class TankAziendale(RegistroAziendale):
    linea = models.ForeignKey(LineaProduttiva, on_delete=models.PROTECT, related_name="tank")
    ricetta = models.ForeignKey("produzione.Ricetta", on_delete=models.PROTECT)
    lavorazione = models.OneToOneField("produzione.Lavorazione", on_delete=models.PROTECT, related_name="tank_aziendale")
    lotto = models.OneToOneField("magazzino.Lotto", on_delete=models.PROTECT, related_name="tank_aziendale")
    massa_teorica = models.DecimalField(max_digits=18, decimal_places=6)
    pronto_il = models.DateTimeField(null=True, blank=True)
    mutable_fields = frozenset({"pronto_il"})


class SessioneInvasettamento(RegistroAziendale):
    turno = models.ForeignKey(TurnoOperativo, on_delete=models.PROTECT, related_name="sessioni")
    ricetta = models.ForeignKey("produzione.Ricetta", on_delete=models.PROTECT)
    lavorazione = models.OneToOneField("produzione.Lavorazione", on_delete=models.PROTECT, related_name="sessione_invasettamento")
    lotto = models.OneToOneField("magazzino.Lotto", on_delete=models.PROTECT, related_name="sessione_invasettamento")
    articolo_vasetti = models.ForeignKey("anagrafiche.Articolo", on_delete=models.PROTECT, related_name="sessioni_vasetti")
    articolo_capsule = models.ForeignKey("anagrafiche.Articolo", on_delete=models.PROTECT, related_name="sessioni_capsule")
    requisito_vasetti = models.ForeignKey("produzione.RequisitoInputTipoLavorazione", on_delete=models.PROTECT, related_name="sessioni_vasetti")
    requisito_capsule = models.ForeignKey("produzione.RequisitoInputTipoLavorazione", on_delete=models.PROTECT, related_name="sessioni_capsule")
    aperta_il = models.DateTimeField(default=timezone.now)
    chiusa_il = models.DateTimeField(null=True, blank=True)
    mutable_fields = frozenset({"chiusa_il"})


class CarrelloSessione(RegistroAziendale):
    sessione = models.ForeignKey(SessioneInvasettamento, on_delete=models.PROTECT, related_name="carrelli")
    unita = models.OneToOneField("produzione.UnitaLavorazione", on_delete=models.PROTECT, related_name="carrello_sessione")
    creato_il = models.DateTimeField(default=timezone.now)


class TrattamentoCarrello(RegistroAziendale):
    carrello = models.ForeignKey(CarrelloSessione, on_delete=models.PROTECT, related_name="trattamenti")
    lavorazione = models.OneToOneField("produzione.Lavorazione", on_delete=models.PROTECT, related_name="trattamento_carrello")
    fase = models.CharField(max_length=20, choices=[("PASTORIZZAZIONE", "Seconda pastorizzazione"), ("VUOTO", "Shock termico e vuoto")])

    class Meta:
        constraints = [models.UniqueConstraint(fields=["carrello", "fase"], name="trattamento_fase_carrello")]


class RiepilogoInvasettamento(RegistroAziendale):
    sessione = models.OneToOneField(SessioneInvasettamento, on_delete=models.PROTECT, related_name="riepilogo")
    vasetti_buoni = models.PositiveIntegerField()
    vasetti_scarti = models.PositiveIntegerField()
    capsule_difettose = models.PositiveIntegerField()
    peso_netto_g = models.DecimalField(max_digits=18, decimal_places=6)
    massa_teorica_kg = models.DecimalField(max_digits=18, decimal_places=6)
    massa_reale_kg = models.DecimalField(max_digits=18, decimal_places=6)
    massa_buona_kg = models.DecimalField(max_digits=18, decimal_places=6)
    resa_percentuale = models.DecimalField(max_digits=18, decimal_places=6)
    chiuso_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrato_il = models.DateTimeField(default=timezone.now)

    class Meta:
        constraints = [models.CheckConstraint(condition=Q(peso_netto_g__gt=0, massa_teorica_kg__gt=0, massa_reale_kg__gt=0), name="riepilogo_pesi_positivi")]


class CodiceProduzione(RegistroAziendale):
    articolo = models.ForeignKey("anagrafiche.Articolo", on_delete=models.PROTECT)
    giorno = models.DateField()
    famiglia = models.CharField(max_length=10, choices=[("RBQB", "RoboQbo"), ("TNK", "Tank"), ("CRL", "Carrello"), ("FINALE", "Lotto finale")])
    numero = models.PositiveIntegerField()
    codice = models.CharField(max_length=100)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["articolo", "giorno", "famiglia", "numero"], name="codice_progressivo_unico"),
            models.UniqueConstraint(fields=["articolo", "codice"], name="codice_articolo_unico")]
