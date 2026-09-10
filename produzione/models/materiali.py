from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.db.models import Q

from magazzino.models.protections import HistoricalModel
from .esecuzione import Lavorazione


class MaterialeLavorazione(HistoricalModel):
    lotto = models.ForeignKey("magazzino.Lotto", on_delete=models.PROTECT, related_name="%(class)s_records")
    quantita = models.DecimalField(max_digits=18, decimal_places=6, validators=[MinValueValidator(Decimal("0.000001"))])
    note = models.TextField(blank=True)

    class Meta:
        abstract = True
        ordering = ["pk"]

    def clean(self):
        super().clean()
        if self._state.adding and self.lavorazione_id and self.lavorazione.tipo_lavorazione.fase_operativa:
            from .azienda import in_scope
            if not in_scope(self.lavorazione_id):
                raise ValidationError("Registrare i materiali attraverso il flusso aziendale.")
        if self.lavorazione_id and self.lavorazione.stato != Lavorazione.Stato.IN_CORSO:
            raise ValidationError("Input/output si registrano soltanto su lavorazioni in corso.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.lavorazione_id:
                self.lavorazione = Lavorazione.objects.select_for_update().get(pk=self.lavorazione_id)
            return super().save(*args, **kwargs)


class InputLavorazione(MaterialeLavorazione):
    lavorazione = models.ForeignKey(Lavorazione, on_delete=models.CASCADE, related_name="inputs")
    requisito_input = models.ForeignKey("produzione.RequisitoInputTipoLavorazione", null=True, blank=True, on_delete=models.PROTECT, related_name="registrazioni")
    riga_ricetta = models.ForeignKey("produzione.RigaRicetta", null=True, blank=True, on_delete=models.PROTECT, related_name="consumi")

    class Meta(MaterialeLavorazione.Meta):
        abstract = False
        verbose_name_plural = "Input lavorazione"
        constraints = [models.CheckConstraint(condition=Q(quantita__gt=0), name="input_quantita_positiva"),
            models.CheckConstraint(condition=Q(requisito_input__isnull=False, riga_ricetta__isnull=True) | Q(requisito_input__isnull=True, riga_ricetta__isnull=False), name="input_origine_teorica_unica")]

    def clean(self):
        super().clean()
        if (self.requisito_input_id is None) == (self.riga_ricetta_id is None):
            raise ValidationError("Indicare una riga ricetta oppure un requisito strutturale, mai entrambi.")
        if self.riga_ricetta_id:
            if not self.lavorazione_id or self.riga_ricetta.ricetta_id != self.lavorazione.ricetta_id:
                raise ValidationError("La riga non appartiene alla ricetta della lavorazione.")
            if self.lotto_id and not self.riga_ricetta.accetta_articolo(self.lotto.articolo):
                raise ValidationError("Il lotto non soddisfa la riga ricetta.")
        if self.lavorazione_id and self.requisito_input_id:
            if self.requisito_input.tipo_lavorazione_id != self.lavorazione.tipo_lavorazione_id:
                raise ValidationError("Il requisito input appartiene a un altro tipo di lavorazione.")
            if not self.requisito_input.multiplo and type(self).objects.filter(lavorazione_id=self.lavorazione_id, requisito_input_id=self.requisito_input_id).exclude(pk=self.pk).exists():
                raise ValidationError("Questo requisito ammette un solo input.")
        if self.lotto_id and self.requisito_input_id and not self.requisito_input.accetta_lotto(self.lotto):
            raise ValidationError("Il lotto non soddisfa il requisito input.")
        if self.lotto_id and self.lavorazione_id and self.lotto.lavorazione_origine_id == self.lavorazione_id:
            raise ValidationError("Una lavorazione non può consumare il proprio lotto output.")


class OutputLavorazione(MaterialeLavorazione):
    lavorazione = models.ForeignKey(Lavorazione, on_delete=models.CASCADE, related_name="outputs")
    requisito_output = models.ForeignKey("produzione.RequisitoOutputTipoLavorazione", on_delete=models.PROTECT, related_name="registrazioni")

    class Meta(MaterialeLavorazione.Meta):
        abstract = False
        verbose_name_plural = "Output lavorazione"
        constraints = [models.CheckConstraint(condition=Q(quantita__gt=0), name="output_quantita_positiva")]

    def clean(self):
        super().clean()
        if self.lavorazione_id:
            if not self.lavorazione.tipo_lavorazione.genera_lotto:
                raise ValidationError("Questa lavorazione non genera un nuovo lotto: output vietato.")
            if self.requisito_output_id:
                if self.requisito_output.tipo_lavorazione_id != self.lavorazione.tipo_lavorazione_id:
                    raise ValidationError("Il requisito output appartiene a un altro tipo di lavorazione.")
                if not self.requisito_output.multiplo and type(self).objects.filter(lavorazione_id=self.lavorazione_id, requisito_output_id=self.requisito_output_id).exclude(pk=self.pk).exists():
                    raise ValidationError("Questo requisito ammette un solo output.")
        if self.lotto_id:
            if self.lotto.tipo != "PRODUZIONE" or self.lotto.lavorazione_origine_id != self.lavorazione_id:
                raise ValidationError("Il lotto output deve provenire da questa lavorazione.")
            if self.requisito_output_id and not self.requisito_output.accetta_articolo(self.lotto.articolo):
                raise ValidationError("L'articolo del lotto non soddisfa il requisito output.")
            if self.requisito_output_id and self.requisito_output.tipo_output == "PRINCIPALE" and self.lavorazione.ricetta_id and self.lotto.articolo_id != self.lavorazione.ricetta.articolo_id:
                raise ValidationError("L'output principale deve essere l'articolo della ricetta.")
