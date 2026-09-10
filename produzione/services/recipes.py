from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from accounts.permissions import require_permission
from magazzino.services.types import persisted_id, quantity
from produzione.models import Ricetta, RigaRicetta


@dataclass(frozen=True)
class RecipeRequirement:
    riga_id: int
    articolo_id: int | None
    categoria_articolo_id: int | None
    quantita_per_batch: Decimal
    quantita_totale: Decimal


class RecipeService:
    @staticmethod
    @transaction.atomic
    def create(*, actor, articolo, nome, versione, note=""):
        require_permission(actor, "can_manage_process_configuration")
        return Ricetta.objects.create(articolo_id=persisted_id(articolo, "Articolo"), nome=nome, versione=versione, note=note)

    @staticmethod
    @transaction.atomic
    def add_line(*, actor, ricetta, quantita, articolo=None, categoria_articolo=None, note=""):
        require_permission(actor, "can_manage_process_configuration")
        recipe = Ricetta.objects.select_for_update().get(pk=persisted_id(ricetta, "Ricetta"))
        recipe.ensure_formula_editable()
        return RigaRicetta.objects.create(
            ricetta=recipe, quantita=quantity(quantita), note=note,
            articolo_id=persisted_id(articolo, "Articolo") if articolo is not None else None,
            categoria_articolo_id=persisted_id(categoria_articolo, "Categoria") if categoria_articolo is not None else None,
        )

    @staticmethod
    @transaction.atomic
    def update_line(*, actor, riga, quantita, note=None):
        require_permission(actor, "can_manage_process_configuration")
        line = RigaRicetta.objects.get(pk=persisted_id(riga, "Riga"))
        recipe = Ricetta.objects.select_for_update().get(pk=line.ricetta_id)
        recipe.ensure_formula_editable()
        line = RigaRicetta.objects.select_for_update().get(pk=line.pk)
        line.quantita = quantity(quantita)
        if note is not None:
            line.note = note
        line.save()
        return line

    @staticmethod
    @transaction.atomic
    def remove_line(*, actor, riga):
        require_permission(actor, "can_manage_process_configuration")
        line = RigaRicetta.objects.get(pk=persisted_id(riga, "Riga"))
        line.delete()

    @staticmethod
    @transaction.atomic
    def new_version(*, actor, ricetta, versione):
        require_permission(actor, "can_manage_process_configuration")
        source = Ricetta.objects.select_for_update().get(pk=persisted_id(ricetta, "Ricetta"))
        result = Ricetta.objects.create(articolo=source.articolo, nome=source.nome, versione=versione, note=source.note)
        for line in source.righe.order_by("pk"):
            RigaRicetta.objects.create(ricetta=result, articolo_id=line.articolo_id,
                                      categoria_articolo_id=line.categoria_articolo_id,
                                      quantita=line.quantita, note=line.note)
        return result

    @staticmethod
    def requirements(*, actor, ricetta, numero_batch=1):
        if not actor or not actor.is_authenticated or not actor.is_active or not actor.has_perm("produzione.view_ricetta"):
            raise PermissionDenied("È richiesto il permesso di consultazione ricette.")
        if isinstance(numero_batch, bool) or not isinstance(numero_batch, int) or numero_batch < 1:
            raise ValidationError("Il numero batch deve essere un intero positivo.")
        recipe = Ricetta.objects.get(pk=persisted_id(ricetta, "Ricetta"))
        # Non sommare quantità di righe diverse: possono usare unità differenti
        # oppure requisiti per categoria che si sovrappongono.
        return tuple(RecipeRequirement(line.pk, line.articolo_id, line.categoria_articolo_id,
                                       line.quantita, quantity(line.quantita * numero_batch))
                     for line in recipe.righe.order_by("pk"))
