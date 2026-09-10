from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Q

from .base import ValidatedModel


class CategoriaArticolo(ValidatedModel):
    codice = models.CharField(max_length=40, unique=True)
    nome = models.CharField(max_length=150)
    categoria_padre = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="figli")
    attiva = models.BooleanField(default=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["codice"]
        verbose_name_plural = "Categorie articolo"
        # MySQL vieta CHECK su colonne AUTO_INCREMENT. I cicli diretti e
        # indiretti sono validati in clean(), chiamato anche da save().

    def __str__(self):
        return f"{self.codice} — {self.nome}"

    def clean(self):
        super().clean()
        seen = {self.pk} if self.pk is not None else set()
        parent = self.categoria_padre if self.categoria_padre_id else None
        while parent is not None:
            if parent.pk in seen:
                raise ValidationError({"categoria_padre": "La gerarchia non può contenere cicli."})
            seen.add(parent.pk)
            parent = parent.categoria_padre

    def antenati(self):
        result, seen = [], {self.pk}
        parent = self.categoria_padre
        while parent is not None:
            if parent.pk in seen:
                raise ValidationError("Ciclo nella gerarchia categorie.")
            seen.add(parent.pk)
            result.append(parent)
            parent = parent.categoria_padre
        return list(reversed(result))

    @property
    def percorso_completo(self):
        return " / ".join(c.nome for c in [*self.antenati(), self])

    def discendenti(self):
        if self.pk is None:
            return type(self).objects.none()
        seen, frontier, ids = {self.pk}, [self.pk], []
        while frontier:
            children = list(type(self).objects.filter(categoria_padre_id__in=frontier).values_list("pk", flat=True))
            if seen.intersection(children):
                raise ValidationError("Ciclo nella gerarchia categorie.")
            seen.update(children)
            ids.extend(children)
            frontier = children
        return type(self).objects.filter(pk__in=ids)

    def appartiene_a_categoria_o_discendenti(self, categoria):
        """True se self è categoria oppure una sua discendente."""
        if self.pk is None or categoria.pk is None:
            return False
        return self.pk == categoria.pk or any(c.pk == categoria.pk for c in self.antenati())


class Articolo(ValidatedModel):
    class UnitaMisura(models.TextChoices):
        KG = "KG", "KG"
        LT = "LT", "LT"
        PZ = "PZ", "PZ"

    class CriterioRotazione(models.TextChoices):
        FIFO = "FIFO", "FIFO"
        FEFO = "FEFO", "FEFO"
        NESSUNO = "NESSUNO", "Nessuno"

    codice = models.CharField(max_length=60, unique=True)
    descrizione = models.CharField(max_length=250)
    categoria = models.ForeignKey(CategoriaArticolo, on_delete=models.PROTECT, related_name="articoli")
    unita_misura = models.CharField(max_length=2, choices=UnitaMisura.choices)
    criterio_rotazione = models.CharField(max_length=7, choices=CriterioRotazione.choices, default=CriterioRotazione.FEFO)
    tracciabilita_lotto = models.BooleanField(default=True)
    scorta_minima = models.DecimalField(max_digits=18, decimal_places=6, default=0, validators=[MinValueValidator(Decimal("0"))])
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["codice"]
        verbose_name_plural = "Articoli"
        constraints = [
            models.CheckConstraint(condition=Q(scorta_minima__gte=0), name="articolo_scorta_non_negativa"),
            models.CheckConstraint(condition=Q(unita_misura__in=["KG", "LT", "PZ"]), name="articolo_unita_valida"),
            models.CheckConstraint(condition=Q(criterio_rotazione__in=["FIFO", "FEFO", "NESSUNO"]), name="articolo_rotazione_valida"),
        ]

    def __str__(self):
        return f"{self.codice} — {self.descrizione}"

    def appartiene_a_categoria_o_discendenti(self, categoria):
        return self.categoria.appartiene_a_categoria_o_discendenti(categoria)


class Fornitore(ValidatedModel):
    codice = models.CharField(max_length=40, unique=True)
    ragione_sociale = models.CharField(max_length=250)
    partita_iva = models.CharField(max_length=30, blank=True)
    codice_fiscale = models.CharField(max_length=30, blank=True)
    indirizzo = models.CharField(max_length=250, blank=True)
    cap = models.CharField(max_length=20, blank=True)
    comune = models.CharField(max_length=100, blank=True)
    provincia = models.CharField(max_length=100, blank=True)
    nazione = models.CharField(max_length=100, blank=True)
    telefono = models.CharField(max_length=40, blank=True)
    email = models.EmailField(blank=True)
    attivo = models.BooleanField(default=True)
    note = models.TextField(blank=True)

    class Meta:
        ordering = ["codice"]
        verbose_name_plural = "Fornitori"

    def __str__(self):
        return f"{self.codice} — {self.ragione_sociale}"
