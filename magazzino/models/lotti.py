from decimal import Decimal

from django.core.exceptions import ValidationError
from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Case, F, Q, Value, When
from django.utils import timezone

from .protections import HistoricalModel


class Lotto(HistoricalModel):
    class Tipo(models.TextChoices):
        ACQUISTO = "ACQUISTO", "Acquisto"
        PRODUZIONE = "PRODUZIONE", "Produzione"

    class StatoProdotto(models.TextChoices):
        GENERICO = "GENERICO", "Generico"
        INVASETTATO = "INVASETTATO", "Invasettato"
        PRODOTTO_FINITO = "PRODOTTO_FINITO", "Prodotto finito"

    class StatoConfezionamento(models.TextChoices):
        NON_APPLICABILE = "NON_APPLICABILE", "Non applicabile"
        DA_CONFEZIONARE = "DA_CONFEZIONARE", "Da confezionare"
        PARZIALE = "PARZIALE", "Parzialmente confezionato"
        CONFEZIONATO = "CONFEZIONATO", "Confezionato"

    articolo = models.ForeignKey("anagrafiche.Articolo", on_delete=models.PROTECT, related_name="lotti")
    codice_lotto = models.CharField(max_length=100)
    tipo = models.CharField(max_length=10, choices=Tipo.choices)
    stato_prodotto = models.CharField(max_length=20, choices=StatoProdotto.choices, default=StatoProdotto.GENERICO)
    stato_confezionamento = models.CharField(max_length=20, choices=StatoConfezionamento.choices, default=StatoConfezionamento.NON_APPLICABILE)
    quantita_confezionata = models.DecimalField(max_digits=18, decimal_places=6, default=0)
    confezionamento_verificato = models.BooleanField(default=True)
    fornitore = models.ForeignKey("anagrafiche.Fornitore", null=True, blank=True, on_delete=models.PROTECT, related_name="lotti")
    data_produzione = models.DateField(null=True, blank=True)
    data_scadenza = models.DateField(null=True, blank=True)
    note = models.TextField(blank=True)
    # MySQL non supporta UniqueConstraint(condition=...). Colonna tecnica
    # calcolata dal DB: NULL per acquisti, codice per produzione.
    codice_univoco_produzione = models.GeneratedField(
        expression=Case(When(tipo="PRODUZIONE", then=F("codice_lotto")), default=Value(None)),
        output_field=models.CharField(max_length=100), db_persist=True,
    )
    lavorazione_origine = models.ForeignKey("produzione.Lavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="lotti_generati")

    class Meta:
        ordering = ["-pk"]
        verbose_name_plural = "Lotti"
        constraints = [
            models.CheckConstraint(condition=Q(tipo="PRODUZIONE") | Q(lavorazione_origine__isnull=True), name="lotto_acquisto_senza_lavoro"),
            models.UniqueConstraint(fields=["articolo", "fornitore", "codice_lotto"], name="lotto_acquisto_univoco"),
            models.UniqueConstraint(fields=["articolo", "codice_univoco_produzione"], name="lotto_produzione_univoco"),
            models.CheckConstraint(condition=(Q(tipo="ACQUISTO", fornitore__isnull=False) | Q(tipo="PRODUZIONE", fornitore__isnull=True)), name="lotto_tipo_fornitore_coerente"),
            models.CheckConstraint(condition=~Q(codice_lotto=""), name="lotto_codice_non_vuoto"),
            models.CheckConstraint(condition=Q(data_produzione__isnull=True) | Q(data_scadenza__isnull=True) | Q(data_scadenza__gte=F("data_produzione")), name="lotto_date_coerenti"),
        ]

    def __str__(self):
        return f"{self.articolo.codice} / {self.codice_lotto}"

    def clean(self):
        super().clean()
        if not self.codice_lotto.strip():
            raise ValidationError({"codice_lotto": "Codice lotto obbligatorio, anche per lotti tecnici."})
        if self.tipo == self.Tipo.ACQUISTO and not self.fornitore_id:
            raise ValidationError({"fornitore": "Un lotto acquistato richiede il fornitore."})
        if self.tipo == self.Tipo.PRODUZIONE and self.fornitore_id:
            raise ValidationError({"fornitore": "Un lotto prodotto non ha fornitore."})
        if self.lavorazione_origine_id:
            if self.tipo != self.Tipo.PRODUZIONE or not self.lavorazione_origine.tipo_lavorazione.genera_lotto:
                raise ValidationError("Origine lotto incompatibile con il tipo di lavorazione.")


class RicevimentoLotto(HistoricalModel):
    lotto = models.ForeignKey(Lotto, on_delete=models.PROTECT, related_name="ricevimenti")
    data_ricevimento = models.DateTimeField(default=timezone.now)
    quantita_ricevuta = models.DecimalField(max_digits=18, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    numero_ddt = models.CharField(max_length=80, blank=True)
    data_ddt = models.DateField(null=True, blank=True)
    numero_fattura = models.CharField(max_length=80, blank=True)
    data_fattura = models.DateField(null=True, blank=True)
    numero_colli = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    numero_unita_per_collo = models.PositiveIntegerField(null=True, blank=True, validators=[MinValueValidator(1)])
    quantita_per_unita = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True, validators=[MinValueValidator(Decimal("0.000001"))])
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-data_ricevimento", "-pk"]
        verbose_name_plural = "Ricevimenti lotto"
        constraints = [
            models.CheckConstraint(condition=Q(quantita_ricevuta__gt=0), name="ricevimento_quantita_positiva"),
            models.CheckConstraint(condition=Q(numero_colli__isnull=True) | Q(numero_colli__gt=0), name="ricevimento_colli_positivi"),
            models.CheckConstraint(condition=Q(numero_unita_per_collo__isnull=True) | Q(numero_unita_per_collo__gt=0), name="ricevimento_unita_positive"),
            models.CheckConstraint(condition=Q(quantita_per_unita__isnull=True) | Q(quantita_per_unita__gt=0), name="ricevimento_per_unita_positiva"),
        ]

    def clean(self):
        super().clean()
        if self.lotto_id and self.lotto.tipo != Lotto.Tipo.ACQUISTO:
            raise ValidationError({"lotto": "Si può ricevere soltanto un lotto di acquisto."})

    def __str__(self):
        return f"Ricevimento {self.pk} — {self.lotto}"


class CorrezioneLotto(HistoricalModel):
    lotto = models.ForeignKey(Lotto, on_delete=models.PROTECT, related_name="correzioni")
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
            raise ValidationError({"motivazione": "La motivazione è obbligatoria."})
