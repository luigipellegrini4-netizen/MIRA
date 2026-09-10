from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from .protections import HistoricalModel, StockQuerySet, _writing_stock


def normalizza_codice(value):
    return (value or "").strip().upper()


class Giacenza(models.Model):
    lotto = models.ForeignKey("magazzino.Lotto", on_delete=models.PROTECT, related_name="giacenze")
    ubicazione = models.ForeignKey("anagrafiche.Ubicazione", on_delete=models.PROTECT, related_name="giacenze")
    scaffale = models.CharField(max_length=30, blank=True, default="")
    piano = models.CharField(max_length=30, blank=True, default="")
    quantita = models.DecimalField(max_digits=18, decimal_places=6, default=0, validators=[MinValueValidator(Decimal("0"))])
    objects = StockQuerySet.as_manager()

    class Meta:
        verbose_name_plural = "Giacenze"
        constraints = [
            models.UniqueConstraint(fields=["lotto", "ubicazione", "scaffale", "piano"], name="giacenza_posizione_univoca"),
            models.CheckConstraint(condition=Q(quantita__gte=0), name="giacenza_non_negativa"),
        ]

    def clean(self):
        super().clean()
        self.scaffale = normalizza_codice(self.scaffale)
        self.piano = normalizza_codice(self.piano)

    def save(self, *args, **kwargs):
        if not _writing_stock.get():
            raise ValidationError("Giacenza modificabile soltanto da MovementService.")
        self.full_clean()
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Le giacenze non vengono cancellate.")

    def __str__(self):
        return f"{self.lotto} — {self.ubicazione} — {self.quantita}"


class Movimento(HistoricalModel):
    class Tipo(models.TextChoices):
        CARICO = "CARICO", "Carico"
        TRASFERIMENTO = "TRASFERIMENTO", "Trasferimento"
        CONSUMO = "CONSUMO", "Consumo"
        PRODUZIONE = "PRODUZIONE", "Produzione"
        VENDITA = "VENDITA", "Vendita"
        QUARANTENA = "QUARANTENA", "Quarantena"
        REINTEGRO = "REINTEGRO", "Reintegro"
        SCARTO = "SCARTO", "Scarto"
        RETTIFICA = "RETTIFICA", "Rettifica"

    data_ora = models.DateTimeField(default=timezone.now)
    tipo = models.CharField(max_length=13, choices=Tipo.choices)
    lotto = models.ForeignKey("magazzino.Lotto", on_delete=models.PROTECT, related_name="movimenti")
    quantita = models.DecimalField(max_digits=18, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    ubicazione_origine = models.ForeignKey("anagrafiche.Ubicazione", null=True, blank=True, on_delete=models.PROTECT, related_name="movimenti_in_uscita")
    scaffale_origine = models.CharField(max_length=30, blank=True, default="")
    piano_origine = models.CharField(max_length=30, blank=True, default="")
    ubicazione_destinazione = models.ForeignKey("anagrafiche.Ubicazione", null=True, blank=True, on_delete=models.PROTECT, related_name="movimenti_in_entrata")
    scaffale_destinazione = models.CharField(max_length=30, blank=True, default="")
    piano_destinazione = models.CharField(max_length=30, blank=True, default="")
    note = models.TextField(blank=True)
    eseguito_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="movimenti_eseguiti")
    input_lavorazione = models.ForeignKey("produzione.InputLavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="movimenti")
    output_lavorazione = models.ForeignKey("produzione.OutputLavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="movimenti")
    sessione_semplificata = models.ForeignKey("produzione.SessioneProduzioneSemplificata", null=True, blank=True, on_delete=models.PROTECT, related_name="movimenti_output")

    class Meta:
        ordering = ["-data_ora", "-pk"]
        verbose_name_plural = "Movimenti"
        constraints = [
            models.CheckConstraint(condition=Q(input_lavorazione__isnull=True) | Q(output_lavorazione__isnull=True), name="movimento_input_output_esclusivi"),
            models.CheckConstraint(condition=Q(input_lavorazione__isnull=True) | Q(tipo="CONSUMO"), name="movimento_input_solo_consumo"),
            models.CheckConstraint(condition=Q(output_lavorazione__isnull=True) | Q(tipo="PRODUZIONE"), name="movimento_output_solo_produzione"),
            models.CheckConstraint(condition=Q(sessione_semplificata__isnull=True) | Q(tipo="PRODUZIONE"), name="movimento_sessione_semplice_solo_produzione"),
            models.CheckConstraint(condition=Q(quantita__gt=0), name="movimento_quantita_positiva"),
            models.CheckConstraint(condition=Q(ubicazione_origine__isnull=False) | Q(ubicazione_destinazione__isnull=False), name="movimento_almeno_un_estremo"),
            models.CheckConstraint(condition=(
                Q(tipo__in=["CARICO", "PRODUZIONE"], ubicazione_origine__isnull=True, ubicazione_destinazione__isnull=False)
                | Q(tipo__in=["CONSUMO", "VENDITA", "SCARTO"], ubicazione_origine__isnull=False, ubicazione_destinazione__isnull=True)
                | Q(tipo__in=["TRASFERIMENTO", "QUARANTENA", "REINTEGRO"], ubicazione_origine__isnull=False, ubicazione_destinazione__isnull=False)
                | (Q(tipo="RETTIFICA") & (Q(ubicazione_origine__isnull=True, ubicazione_destinazione__isnull=False) | Q(ubicazione_origine__isnull=False, ubicazione_destinazione__isnull=True)))
            ), name="movimento_direzione_coerente"),
            models.CheckConstraint(condition=~Q(tipo="RETTIFICA") | ~Q(note=""), name="movimento_rettifica_motivata"),
            models.CheckConstraint(condition=Q(ubicazione_origine__isnull=False) | Q(scaffale_origine="", piano_origine=""), name="movimento_origine_codici"),
            models.CheckConstraint(condition=Q(ubicazione_destinazione__isnull=False) | Q(scaffale_destinazione="", piano_destinazione=""), name="movimento_destinazione_codici"),
            models.CheckConstraint(condition=~Q(ubicazione_origine=F("ubicazione_destinazione"), scaffale_origine=F("scaffale_destinazione"), piano_origine=F("piano_destinazione")), name="movimento_posizioni_distinte"),
        ]

    def clean(self):
        super().clean()
        for suffix in ("origine", "destinazione"):
            for prefix in ("scaffale", "piano"):
                name = f"{prefix}_{suffix}"
                setattr(self, name, normalizza_codice(getattr(self, name)))
            if not getattr(self, f"ubicazione_{suffix}_id") and (getattr(self, f"scaffale_{suffix}") or getattr(self, f"piano_{suffix}")):
                raise ValidationError("Scaffale/piano richiedono la relativa ubicazione.")
        if self.tipo == self.Tipo.RETTIFICA and not self.note.strip():
            raise ValidationError({"note": "La rettifica richiede una motivazione."})
        if self.input_lavorazione_id and self.output_lavorazione_id:
            raise ValidationError("Un movimento non può riferirsi sia a input sia a output.")
        for name, expected_type in (("input_lavorazione", self.Tipo.CONSUMO), ("output_lavorazione", self.Tipo.PRODUZIONE)):
            if getattr(self, f"{name}_id"):
                record = getattr(self, name)
                if self.tipo != expected_type or self.lotto_id != record.lotto_id:
                    raise ValidationError("Movimento incompatibile con lotto o tipo della registrazione produttiva.")
        if self.sessione_semplificata_id:
            expected = self.sessione_semplificata.lotto_prodotto_id
            if self.tipo != self.Tipo.PRODUZIONE or expected not in {None, self.lotto_id}:
                raise ValidationError("Movimento incompatibile con la sessione semplificata.")
                if record.lavorazione.stato != "IN_CORSO":
                    raise ValidationError("La registrazione produttiva appartiene a una lavorazione non in corso.")

    def save(self, *args, **kwargs):
        if not _writing_stock.get():
            raise ValidationError("Movimenti registrabili soltanto da MovementService.")
        return super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.tipo} {self.quantita} — {self.lotto}"
