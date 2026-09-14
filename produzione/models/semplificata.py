from decimal import Decimal

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from anagrafiche.models.base import ValidatedModel


class SessioneProduzioneSemplificata(ValidatedModel):
    class Tipo(models.TextChoices):
        SEMILAVORATO = "SEMILAVORATO", "Semilavorato"
        ROBOQBO = "ROBOQBO", "RoboQbo"
        INVASETTAMENTO = "INVASETTAMENTO", "Invasettamento"
        ETICHETTATURA = "ETICHETTATURA", "Etichettatura"
        CONFEZIONAMENTO = "CONFEZIONAMENTO", "Confezionamento"

    class Stato(models.TextChoices):
        PIANIFICATA = "PIANIFICATA", "Pianificata"
        APERTA = "APERTA", "Aperta"
        CHIUSA = "CHIUSA", "Chiusa"
        ANNULLATA = "ANNULLATA", "Annullata"

    tipo = models.CharField(max_length=20, choices=Tipo.choices)
    postazione = models.ForeignKey("produzione.PostazioneLinea", null=True, blank=True, on_delete=models.PROTECT, related_name="sessioni_semplificate")
    ricetta = models.ForeignKey("produzione.Ricetta", on_delete=models.PROTECT, related_name="sessioni_semplificate")
    # Il lotto nasce con la pianificazione. Finché non viene chiusa la sessione
    # non ha movimenti né giacenze, ma resta l'unica fonte del codice lotto.
    lotto = models.ForeignKey(
        "magazzino.Lotto", on_delete=models.PROTECT,
        related_name="sessioni_semplificate",
    )
    lotto_origine = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="sessioni_invasettamento")
    stato = models.CharField(max_length=11, choices=Stato.choices, default=Stato.PIANIFICATA)
    numero_batch_previsti = models.PositiveIntegerField(null=True, blank=True)
    quantita_prevista_kg = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    numero_lavorazioni_previste = models.PositiveIntegerField(null=True, blank=True)
    quantita_finale_kg = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    confezionamento_giacenza = models.ForeignKey("magazzino.Giacenza", null=True, blank=True, on_delete=models.PROTECT, related_name="confezionamenti")
    igienizzazione_confermata_il = models.DateTimeField(null=True, blank=True)
    aperta_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sessioni_semplificate_aperte")
    aperta_il = models.DateTimeField(default=timezone.now)
    iniziata_il = models.DateTimeField(null=True, blank=True)
    chiusa_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="sessioni_semplificate_chiuse")
    chiusa_il = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-aperta_il", "-pk"]
        constraints = [
            models.CheckConstraint(
                condition=(Q(stato__in=["PIANIFICATA", "APERTA"], chiusa_il__isnull=True, chiusa_da__isnull=True)
                           | Q(stato__in=["CHIUSA", "ANNULLATA"], chiusa_il__isnull=False, chiusa_da__isnull=False)),
                name="sessione_semplice_chiusura_coerente",
            ),
        ]

    def __str__(self):
        return self.lotto.codice_lotto

    @property
    def articolo(self):
        return self.ricetta.articolo

    @property
    def quantita_iniziale_kg(self):
        return self.prelievi.filter(
            lotto__articolo__unita_misura="KG"
        ).aggregate(t=models.Sum("quantita_kg"))["t"] or Decimal("0")

    @property
    def quantita_iniziale_per_unita(self):
        totals = self.prelievi.values(
            "lotto__articolo__unita_misura"
        ).annotate(totale=models.Sum("quantita_kg")).order_by("lotto__articolo__unita_misura")
        return [
            {"unita": row["lotto__articolo__unita_misura"], "quantita": row["totale"]}
            for row in totals
        ]

    @property
    def batch_previsti(self):
        return self.numero_batch_previsti or self.numero_lavorazioni_previste

    @property
    def prelievo_ricetta_registrato(self):
        return self.prelievi.filter(da_ricetta=True).exists()

    def clean(self):
        super().clean()
        if self.lotto_id and self.ricetta_id and self.lotto.articolo_id != self.ricetta.articolo_id:
            raise ValidationError("Il lotto della sessione deve appartenere all'articolo della ricetta.")
        if self.tipo == self.Tipo.SEMILAVORATO:
            if self.lotto_origine_id or not self.batch_previsti:
                raise ValidationError("Il semilavorato richiede il numero di batch previsti, senza lotto di origine.")
        elif self.tipo == self.Tipo.ROBOQBO:
            if self.lotto_origine_id:
                raise ValidationError("RoboQbo non può avere un lotto produttivo di origine.")
            if not self.numero_batch_previsti:
                raise ValidationError("Indicare il numero di batch previsti.")
        elif self.tipo == self.Tipo.INVASETTAMENTO:
            if not self.lotto_origine_id or self.lotto_origine.tipo != self.Tipo.ROBOQBO:
                raise ValidationError("L'invasettamento deve essere collegato a una sessione RoboQbo.")
            if self.lotto_origine_id == self.pk:
                raise ValidationError("Una sessione non può essere origine di se stessa.")
            if self.ricetta_id != self.lotto_origine.ricetta_id:
                raise ValidationError("RoboQbo e invasettamento devono usare la stessa ricetta.")
            if self.numero_batch_previsti is not None:
                raise ValidationError("Il numero di batch appartiene alla sessione RoboQbo.")
        elif self.tipo == self.Tipo.ETICHETTATURA:
            if not self.lotto_origine_id or self.lotto_origine.tipo != self.Tipo.INVASETTAMENTO:
                raise ValidationError("L'etichettatura deve essere collegata a una sessione di invasettamento.")
            if self.ricetta_id != self.lotto_origine.ricetta_id:
                raise ValidationError("Invasettamento ed etichettatura devono usare lo stesso articolo.")
            if self.numero_batch_previsti is not None:
                raise ValidationError("L'etichettatura non richiede un numero di batch.")
        elif self.tipo == self.Tipo.CONFEZIONAMENTO:
            if not self.lotto_origine_id or self.lotto_origine.tipo != self.Tipo.ETICHETTATURA:
                raise ValidationError("Il confezionamento deve essere collegato a un'etichettatura.")
            if self.ricetta_id != self.lotto_origine.ricetta_id or self.lotto_id != self.lotto_origine.lotto_id:
                raise ValidationError("Il confezionamento deve mantenere articolo e codice del lotto etichettato.")


class PrelievoSessioneSemplificata(ValidatedModel):
    sessione = models.ForeignKey(SessioneProduzioneSemplificata, on_delete=models.PROTECT, related_name="prelievi")
    lotto = models.ForeignKey("magazzino.Lotto", on_delete=models.PROTECT, related_name="prelievi_sessioni_semplificate")
    quantita_kg = models.DecimalField(max_digits=18, decimal_places=6)
    numero_batch = models.PositiveIntegerField(null=True, blank=True)
    da_ricetta = models.BooleanField(default=False)
    movimento = models.OneToOneField("magazzino.Movimento", null=True, blank=True, on_delete=models.PROTECT, related_name="prelievo_sessione_semplificata")
    registrato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrato_il = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["registrato_il", "pk"]
        constraints = [models.CheckConstraint(condition=Q(quantita_kg__gt=0), name="prelievo_semplice_quantita_positiva")]

    def clean(self):
        super().clean()
        if self.sessione_id and self.sessione.tipo not in SessioneProduzioneSemplificata.Tipo.values:
            raise ValidationError("Il prelievo deve appartenere a una sessione produttiva valida.")


class ConfigurazioneControlloSemplificato(ValidatedModel):
    class Ambito(models.TextChoices):
        SEMILAVORATO = "SEMILAVORATO", "Semilavorati"
        ROBOQBO_BATCH = "ROBOQBO_BATCH", "RoboQbo · Batch"
        ROBOQBO_TANK = "ROBOQBO_TANK", "RoboQbo · Tank"
        INVASETTAMENTO_CARRELLO = "INVASETTAMENTO_CARRELLO", "Invasettamento · Carrello"

    class Codice(models.TextChoices):
        INIZIO = "INIZIO", "Ora di inizio"
        FINE = "FINE", "Ora di fine"
        TRACCIATO = "TRACCIATO", "Tracciato 82 °C × 60 s"
        BRIX = "BRIX", "°Brix"
        PH = "PH", "pH"
        PASTORIZZAZIONE = "PASTORIZZAZIONE", "Pastorizzazione"
        SHOCK_VUOTO = "SHOCK_VUOTO", "Shock termico e vuoto"

    ambito = models.CharField(max_length=30, choices=Ambito.choices)
    codice = models.CharField(max_length=20, choices=Codice.choices)
    nome = models.CharField(max_length=100)
    ordine = models.PositiveSmallIntegerField(default=10)
    obbligatorio = models.BooleanField(default=True)
    attivo = models.BooleanField(default=True)

    class Meta:
        ordering = ["ambito", "ordine", "pk"]
        constraints = [models.UniqueConstraint(fields=["ambito", "codice"], name="config_controllo_semplice_unica")]

    def __str__(self):
        return f"{self.get_ambito_display()} · {self.nome}"


class ControlloSessioneSemplificata(ValidatedModel):
    class Tipo(models.TextChoices):
        SEMILAVORATO = "SEMILAVORATO", "Semilavorato"
        BATCH = "BATCH", "Batch"
        TANK = "TANK", "Tank"
        CARRELLO = "CARRELLO", "Carrello"

    class Esito(models.TextChoices):
        C = "C", "Conforme"
        NC = "NC", "Non conforme"
        NA = "NA", "Non applicabile"

    sessione = models.ForeignKey(SessioneProduzioneSemplificata, on_delete=models.PROTECT, related_name="controlli")
    tipo = models.CharField(max_length=15, choices=Tipo.choices)
    numero = models.PositiveIntegerField()
    inizio = models.DateTimeField(null=True, blank=True)
    fine = models.DateTimeField(null=True, blank=True)
    esito_tracciato_termico = models.CharField(max_length=2, choices=Esito.choices, blank=True)
    gradi_brix = models.DecimalField(max_digits=6, decimal_places=3, null=True, blank=True)
    ph = models.DecimalField(max_digits=5, decimal_places=3, null=True, blank=True)
    esito_pastorizzazione = models.CharField(max_length=2, choices=Esito.choices, blank=True)
    esito_shock_vuoto = models.CharField(max_length=2, choices=Esito.choices, blank=True)
    registrato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrato_il = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["tipo", "numero"]
        constraints = [
            models.UniqueConstraint(fields=["sessione", "tipo", "numero"], name="controllo_semplice_numero_unico"),
            models.CheckConstraint(
                condition=(
                    Q(tipo="BATCH", gradi_brix__isnull=True, ph__isnull=True,
                      esito_pastorizzazione="", esito_shock_vuoto="")
                    | Q(tipo="SEMILAVORATO", inizio__isnull=True, fine__isnull=True,
                        esito_tracciato_termico="", gradi_brix__isnull=True, ph__isnull=True)
                    | Q(tipo="TANK", inizio__isnull=True, fine__isnull=True,
                        esito_tracciato_termico="", esito_pastorizzazione="", esito_shock_vuoto="")
                    | Q(tipo="CARRELLO", inizio__isnull=True, fine__isnull=True,
                        esito_tracciato_termico="", gradi_brix__isnull=True, ph__isnull=True)
                ),
                name="controllo_semplice_campi_per_tipo",
            ),
        ]

    @property
    def completo(self):
        required = {
            self.Tipo.BATCH: ("inizio", "fine", "esito_tracciato_termico"),
            self.Tipo.TANK: ("gradi_brix", "ph"),
            self.Tipo.SEMILAVORATO: ("esito_pastorizzazione", "esito_shock_vuoto"),
            self.Tipo.CARRELLO: ("esito_pastorizzazione", "esito_shock_vuoto"),
        }
        fields = required.get(self.tipo, ())
        return bool(fields) and all(getattr(self, field) not in (None, "") for field in fields)

    @property
    def esito(self):
        outcomes = (
            self.esito_tracciato_termico,
            self.esito_pastorizzazione,
            self.esito_shock_vuoto,
        )
        if any(value in {self.Esito.NC, self.Esito.NA} for value in outcomes):
            return "NC"
        if self.tipo == self.Tipo.TANK:
            if self.gradi_brix is not None and not Decimal("40") < self.gradi_brix < Decimal("45"):
                return "NC"
            if self.ph is not None and self.ph > Decimal("4.1"):
                return "NC"
        return "C" if self.completo else "Incompleto"

    @property
    def conforme(self):
        return self.esito == "C"

    def clean(self):
        super().clean()
        if self.inizio and self.fine and self.fine < self.inizio:
            raise ValidationError("La fine del controllo precede l'inizio.")
        if self.tipo in {self.Tipo.BATCH, self.Tipo.TANK} and self.sessione_id and self.sessione.tipo != SessioneProduzioneSemplificata.Tipo.ROBOQBO:
            raise ValidationError("Batch e tank appartengono alla sessione RoboQbo.")
        if self.tipo == self.Tipo.CARRELLO and self.sessione_id and self.sessione.tipo != SessioneProduzioneSemplificata.Tipo.INVASETTAMENTO:
            raise ValidationError("I carrelli appartengono alla sessione di invasettamento.")
        if self.tipo == self.Tipo.SEMILAVORATO and self.sessione_id and self.sessione.tipo != SessioneProduzioneSemplificata.Tipo.SEMILAVORATO:
            raise ValidationError("Il controllo appartiene alla sessione Semilavorati.")
        fields_for_type = {
            self.Tipo.BATCH: ("gradi_brix", "ph", "esito_pastorizzazione", "esito_shock_vuoto"),
            self.Tipo.TANK: ("inizio", "fine", "esito_tracciato_termico", "esito_pastorizzazione", "esito_shock_vuoto"),
            self.Tipo.CARRELLO: ("inizio", "fine", "esito_tracciato_termico", "gradi_brix", "ph"),
            self.Tipo.SEMILAVORATO: ("inizio", "fine", "esito_tracciato_termico", "gradi_brix", "ph"),
        }
        if any(getattr(self, field) not in (None, "") for field in fields_for_type.get(self.tipo, ())):
            raise ValidationError("Il controllo contiene valori non previsti per il tipo selezionato.")


class AssociazioneTankBatch(ValidatedModel):
    tank = models.ForeignKey(
        ControlloSessioneSemplificata, on_delete=models.PROTECT,
        related_name="associazioni_batch",
    )
    batch = models.OneToOneField(
        ControlloSessioneSemplificata, on_delete=models.PROTECT,
        related_name="associazione_tank",
    )
    registrato_da = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT,
        related_name="associazioni_tank_batch_registrate",
    )
    registrato_il = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["tank__numero", "batch__numero", "pk"]
        constraints = [
            models.CheckConstraint(condition=~Q(tank=models.F("batch")), name="tank_batch_distinti"),
        ]

    def __str__(self):
        return f"Tank {self.tank.numero} ← Batch {self.batch.numero}"

    def clean(self):
        super().clean()
        if not self.tank_id or not self.batch_id:
            return
        if self.tank.tipo != ControlloSessioneSemplificata.Tipo.TANK:
            raise ValidationError("Il controllo di destinazione deve essere un tank.")
        if self.batch.tipo != ControlloSessioneSemplificata.Tipo.BATCH:
            raise ValidationError("Il controllo associato deve essere un batch.")
        if self.tank.sessione_id != self.batch.sessione_id:
            raise ValidationError("Tank e batch devono appartenere alla stessa produzione RoboQbo.")


class RiepilogoSessioneSemplificata(ValidatedModel):
    sessione = models.OneToOneField(SessioneProduzioneSemplificata, on_delete=models.PROTECT, related_name="riepilogo_finale")
    vasetti_buoni = models.PositiveIntegerField(default=0)
    vasetti_scartati = models.PositiveIntegerField(default=0)
    vasetti_quarantena = models.PositiveIntegerField(default=0)
    capsule_difettose = models.PositiveIntegerField(default=0)
    peso_netto_g = models.DecimalField(max_digits=18, decimal_places=6)
    registrato_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)
    registrato_il = models.DateTimeField(default=timezone.now)

    def clean(self):
        super().clean()
        if self.sessione_id and self.sessione.tipo != SessioneProduzioneSemplificata.Tipo.INVASETTAMENTO:
            raise ValidationError("Il riepilogo finale appartiene all'invasettamento.")
        if self.peso_netto_g <= 0:
            raise ValidationError("Il peso netto deve essere positivo.")

    @property
    def vasetti_totali(self):
        return self.vasetti_buoni + self.vasetti_scartati + self.vasetti_quarantena

    @property
    def capsule_prelevate(self):
        return self.vasetti_totali + self.capsule_difettose

    @property
    def quantita_finale_kg(self):
        return Decimal(self.vasetti_totali) * self.peso_netto_g / Decimal("1000")

    @property
    def quantita_conforme_kg(self):
        return Decimal(self.vasetti_buoni) * self.peso_netto_g / Decimal("1000")

    @property
    def resa_percentuale(self):
        iniziale = self.sessione.lotto_origine.quantita_iniziale_kg
        return self.quantita_finale_kg * Decimal("100") / iniziale if iniziale else None


class NonConformitaSessioneSemplificata(ValidatedModel):
    class Stato(models.TextChoices):
        APERTA = "APERTA", "Aperta"
        IN_GESTIONE = "IN_GESTIONE", "In gestione"
        CHIUSA = "CHIUSA", "Chiusa"

    sessione = models.ForeignKey(SessioneProduzioneSemplificata, on_delete=models.PROTECT, related_name="non_conformita_semplificate")
    controllo = models.ForeignKey(ControlloSessioneSemplificata, null=True, blank=True, on_delete=models.PROTECT, related_name="non_conformita")
    descrizione = models.TextField()
    quantita_coinvolta_kg = models.DecimalField(max_digits=18, decimal_places=6, null=True, blank=True)
    vasetti_coinvolti = models.PositiveIntegerField(null=True, blank=True)
    stato = models.CharField(max_length=12, choices=Stato.choices, default=Stato.APERTA)
    aperta_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="nc_semplificate_aperte")
    aperta_il = models.DateTimeField(default=timezone.now)
    presa_in_carico_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="nc_semplificate_gestite")
    presa_in_carico_il = models.DateTimeField(null=True, blank=True)
    chiusa_da = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="nc_semplificate_chiuse")
    chiusa_il = models.DateTimeField(null=True, blank=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["-aperta_il", "-pk"]

    def clean(self):
        super().clean()
        if self.controllo_id and self.controllo.sessione_id != self.sessione_id:
            raise ValidationError("Il controllo appartiene a un'altra sessione.")
        if self.quantita_coinvolta_kg is not None and self.quantita_coinvolta_kg <= 0:
            raise ValidationError("La quantità coinvolta deve essere positiva.")
        if self.stato == self.Stato.APERTA and any((self.presa_in_carico_da_id, self.presa_in_carico_il, self.chiusa_da_id, self.chiusa_il)):
            raise ValidationError("Una NC aperta non può avere dati di presa in carico o chiusura.")
        if self.stato in {self.Stato.IN_GESTIONE, self.Stato.CHIUSA} and (not self.presa_in_carico_da_id or not self.presa_in_carico_il):
            raise ValidationError("La NC deve essere presa in carico prima della chiusura.")
        if self.stato == self.Stato.CHIUSA and (not self.chiusa_da_id or not self.chiusa_il):
            raise ValidationError("Indicare autore e data di chiusura della NC.")


class AzioneNCSessioneSemplificata(ValidatedModel):
    class Tipo(models.TextChoices):
        AZIONE = "AZIONE", "Azione documentale"
        SCARTO = "SCARTO", "Scarto dal magazzino"

    non_conformita = models.ForeignKey(NonConformitaSessioneSemplificata, on_delete=models.PROTECT, related_name="azioni")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.AZIONE)
    descrizione = models.TextField()
    movimento = models.OneToOneField("magazzino.Movimento", null=True, blank=True, on_delete=models.PROTECT, related_name="azione_nc_sessione_semplificata")
    registrata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="azioni_nc_semplificate")
    registrata_il = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["registrata_il", "pk"]
        constraints = [models.CheckConstraint(
            condition=(Q(tipo="SCARTO", movimento__isnull=False) | Q(tipo="AZIONE", movimento__isnull=True)),
            name="azione_nc_semplice_movimento_coerente",
        )]

    def clean(self):
        super().clean()
        if not self.descrizione.strip():
            raise ValidationError("Descrivere l'azione eseguita.")
        if self.non_conformita_id and self.non_conformita.stato != NonConformitaSessioneSemplificata.Stato.IN_GESTIONE:
            raise ValidationError("La NC deve essere in gestione.")
        if (self.tipo == self.Tipo.SCARTO) != bool(self.movimento_id):
            raise ValidationError("Lo scarto deve essere collegato al relativo movimento di magazzino.")


class VerificaNCSessioneSemplificata(ValidatedModel):
    class Esito(models.TextChoices):
        EFFICACE = "EFFICACE", "Efficace"
        NON_EFFICACE = "NON_EFFICACE", "Non efficace"

    non_conformita = models.ForeignKey(NonConformitaSessioneSemplificata, on_delete=models.PROTECT, related_name="verifiche")
    esito = models.CharField(max_length=12, choices=Esito.choices)
    descrizione = models.TextField()
    verificata_da = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="verifiche_nc_semplificate")
    verificata_il = models.DateTimeField(default=timezone.now)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["verificata_il", "pk"]

    def clean(self):
        super().clean()
        if not self.descrizione.strip():
            raise ValidationError("Descrivere la verifica eseguita.")
        if self.non_conformita_id and self.non_conformita.stato != NonConformitaSessioneSemplificata.Stato.IN_GESTIONE:
            raise ValidationError("La NC deve essere in gestione.")
