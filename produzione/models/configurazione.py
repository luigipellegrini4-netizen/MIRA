from django.core.exceptions import ValidationError
from django.db import models, transaction
from django.db.models import Q

from anagrafiche.models.base import ValidatedModel
from .protections import ProtectedProductionQuerySet


class TipoLavorazione(ValidatedModel):
    class FaseOperativa(models.TextChoices):
        GENERICA = "", "Generica"
        SEMILAVORATO = "SEMILAVORATO", "Semilavorati"
        ROBOQBO = "ROBOQBO", "Batch RoboQbo"
        TANK = "TANK", "Formazione tank"
        INVASETTAMENTO = "INVASETTAMENTO", "Invasettamento"
        PASTORIZZAZIONE = "PASTORIZZAZIONE", "Seconda pastorizzazione"
        VUOTO = "VUOTO", "Shock termico e vuoto"

    fase_operativa = models.CharField(max_length=20, choices=FaseOperativa.choices, blank=True, default="")
    codice = models.CharField(max_length=60, unique=True)
    nome = models.CharField(max_length=150)
    genera_lotto = models.BooleanField(default=True)
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        ordering = ["codice"]
        verbose_name_plural = "Tipi lavorazione"

    def __str__(self):
        return f"{self.codice} — {self.nome}"

    def ensure_editable(self):
        if self.configurazione_utilizzata:
            raise ValidationError("Tipo già utilizzato: creare una nuova configurazione per cambiare il processo.")

    @property
    def configurazione_utilizzata(self):
        return bool(self.pk and (self.lavorazioni.exists() or self.richiesta_per_unita.exists()))

    def clean(self):
        super().clean()
        if self.fase_operativa:
            expected = self.fase_operativa not in {"PASTORIZZAZIONE", "VUOTO"}
            if self.genera_lotto != expected:
                raise ValidationError("Generazione lotto incompatibile con la fase aziendale.")
        if self.pk and not self.genera_lotto and self.requisiti_output.exists():
            raise ValidationError("Rimuovere i requisiti output prima di impostare genera_lotto=False.")
        if self.pk and self.genera_lotto and self.richiesta_per_unita.exists():
            raise ValidationError("Una fase di trattamento delle unità non può generare nuovi lotti.")
        if self.pk and not self.genera_lotto and self.fasi_unita_richieste.exists():
            raise ValidationError("Un processo origine delle unità deve generare il lotto.")
        if self.configurazione_utilizzata:
            old = type(self).objects.get(pk=self.pk)
            if any(getattr(old, name) != getattr(self, name) for name in ("codice", "nome", "genera_lotto", "note", "fase_operativa")):
                raise ValidationError("Configurazione storica: è consentito soltanto modificare attivo.")

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().filter(pk=self.pk).first()
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            if self.pk:
                type(self).objects.select_for_update().get(pk=self.pk)
            self.ensure_editable()
            return super().delete(*args, **kwargs)


class RequisitoBase(ValidatedModel):
    nome = models.CharField(max_length=150)
    categoria_articolo = models.ForeignKey("anagrafiche.CategoriaArticolo", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    articolo = models.ForeignKey("anagrafiche.Articolo", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    obbligatorio = models.BooleanField(default=True)
    multiplo = models.BooleanField(default=False)
    ordine = models.PositiveIntegerField(default=0)
    note = models.TextField(blank=True)
    objects = ProtectedProductionQuerySet.as_manager()

    class Meta:
        abstract = True
        ordering = ["ordine", "pk"]

    def __str__(self):
        return f"{self.tipo_lavorazione.codice}: {self.nome}"

    def clean(self):
        super().clean()
        if self.articolo_id is not None and self.categoria_articolo_id is not None:
            raise ValidationError("Articolo e categoria sono alternativi.")
        if self.tipo_lavorazione_id:
            self.tipo_lavorazione.ensure_editable()
        if self.pk:
            previous = type(self).objects.filter(pk=self.pk).first()
            if previous and previous.tipo_lavorazione_id != self.tipo_lavorazione_id:
                raise ValidationError("Un requisito esistente non può essere spostato a un altro tipo.")

    def accetta_articolo(self, articolo):
        if self.articolo_id is not None:
            return self.articolo_id == articolo.pk
        if self.categoria_articolo_id is not None:
            return articolo.appartiene_a_categoria_o_discendenti(self.categoria_articolo)
        return True

    def save(self, *args, **kwargs):
        with transaction.atomic():
            if self.tipo_lavorazione_id:
                self.tipo_lavorazione = TipoLavorazione.objects.select_for_update().get(pk=self.tipo_lavorazione_id)
            return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        with transaction.atomic():
            kind = TipoLavorazione.objects.select_for_update().get(pk=self.tipo_lavorazione_id)
            kind.ensure_editable()
            return super().delete(*args, **kwargs)


class RequisitoInputTipoLavorazione(RequisitoBase):
    tipo_lavorazione = models.ForeignKey(TipoLavorazione, on_delete=models.CASCADE, related_name="requisiti_input")
    tipo_lavorazione_origine = models.ForeignKey(TipoLavorazione, null=True, blank=True, on_delete=models.PROTECT, related_name="requisiti_derivati")

    class Meta(RequisitoBase.Meta):
        abstract = False
        verbose_name_plural = "Requisiti input per tipo"
        constraints = [
            models.CheckConstraint(condition=Q(articolo__isnull=True) | Q(categoria_articolo__isnull=True), name="req_input_target_alternativi"),
            models.CheckConstraint(condition=Q(articolo__isnull=False) | Q(categoria_articolo__isnull=False) | Q(tipo_lavorazione_origine__isnull=False), name="req_input_almeno_un_filtro"),
        ]

    def clean(self):
        super().clean()
        if self.articolo_id is None and self.categoria_articolo_id is None and self.tipo_lavorazione_origine_id is None:
            raise ValidationError("Un requisito input deve specificare articolo, categoria o tipo di origine.")

    def accetta_lotto(self, lotto):
        if not self.accetta_articolo(lotto.articolo):
            return False
        if self.tipo_lavorazione_origine_id is not None:
            return bool(lotto.lavorazione_origine_id and lotto.lavorazione_origine.tipo_lavorazione_id == self.tipo_lavorazione_origine_id)
        return True


class RequisitoOutputTipoLavorazione(RequisitoBase):
    schema_lotto = models.CharField(max_length=10, default="LEGACY", choices=[
        ("LEGACY", "Convenzione precedente"), ("RBQB", "RbQb + data + progressivo"),
        ("TNK", "TNK + data + progressivo"), ("FINALE", "Data + lettera")])
    class TipoOutput(models.TextChoices):
        PRINCIPALE = "PRINCIPALE", "Principale"
        SECONDARIO = "SECONDARIO", "Secondario"

    tipo_lavorazione = models.ForeignKey(TipoLavorazione, on_delete=models.CASCADE, related_name="requisiti_output")
    tipo_output = models.CharField(max_length=10, choices=TipoOutput.choices, default=TipoOutput.PRINCIPALE)
    prefisso_lotto = models.CharField(max_length=20, blank=True)

    class Meta(RequisitoBase.Meta):
        abstract = False
        verbose_name_plural = "Requisiti output per tipo"
        constraints = [
            models.CheckConstraint(condition=Q(articolo__isnull=False, categoria_articolo__isnull=True) | Q(articolo__isnull=True, categoria_articolo__isnull=False), name="req_output_un_solo_target"),
            models.CheckConstraint(condition=Q(tipo_output__in=["PRINCIPALE", "SECONDARIO"]), name="req_output_tipo_valido"),
        ]

    def clean(self):
        super().clean()
        if self.articolo_id is None and self.categoria_articolo_id is None:
            raise ValidationError("Specificare articolo oppure categoria dell'output.")
        if self.tipo_lavorazione_id and not self.tipo_lavorazione.genera_lotto:
            raise ValidationError("Un processo senza nuovo lotto non prevede output artificiali.")
