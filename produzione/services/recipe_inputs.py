from dataclasses import dataclass
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db import transaction
from accounts.permissions import require_permission
from anagrafiche.models import Articolo
from magazzino.services import Allocation
from magazzino.selectors import StockProposalService
from produzione.models import Lavorazione
from .locking import get_record
from .materials import InputService, InputSelection


@dataclass(frozen=True)
class RecipeInputProposal:
    selections: tuple
    righe: tuple

    @property
    def completa(self):
        return all(row["mancante"] == Decimal(0) for row in self.righe)


class RecipeInputService:
    @staticmethod
    def confirm_proposal(*, actor, lavorazione, proposal):
        require_permission(actor, "can_record_production_consumption")
        if not isinstance(proposal, RecipeInputProposal) or not proposal.completa:
            raise ValidationError("Proposta incompleta: disponibilità insufficiente, nessun consumo registrato.")
        return RecipeInputService.confirm(actor=actor, lavorazione=lavorazione, selections=proposal.selections)

    @staticmethod
    def propose(*, actor, lavorazione, articoli_per_riga=None, ubicazioni=None):
        require_permission(actor, "can_record_production_consumption")
        work = get_record(Lavorazione, lavorazione, "Lavorazione")
        if not work.ricetta_id:
            raise ValidationError("La lavorazione non ha una ricetta.")
        selections, rows, resolved, totals = [], [], [], {}
        ubicazioni = tuple(ubicazioni) if ubicazioni is not None else None
        for row in work.ricetta.righe.order_by("pk"):
            article_id = row.articolo_id or (articoli_per_riga or {}).get(row.pk)
            if article_id is None:
                raise ValidationError("Per una riga a categoria scegliere esplicitamente l'articolo.")
            article = get_record(Articolo, article_id, "Articolo")
            if not row.accetta_articolo(article):
                raise ValidationError("Articolo incompatibile con la riga ricetta.")
            resolved.append((row, article.pk))
            totals[article.pk] = totals.get(article.pk, Decimal(0)) + row.quantita
        if not resolved:
            raise ValidationError("La ricetta è priva di ingredienti.")
        # Un solo fabbisogno aggregato per articolo: righe diverse non possono
        # proporre due volte la stessa disponibilità (anche con categorie).
        pools = {}
        for article_id, total in totals.items():
            proposal = StockProposalService.propose(actor=actor, articolo=article_id, quantita=total, ubicazioni=ubicazioni)
            pools[article_id] = [[line, line.quantita] for line in proposal.righe]
        for row, article_id in resolved:
            remaining = row.quantita
            for entry in pools[article_id]:
                line, available = entry
                chosen = min(remaining, available)
                if chosen:
                    selections.append(InputSelection(lotto=line.lotto_id, quantita=chosen,
                        origini=[Allocation(line.posizione, chosen)], riga_ricetta=row.pk))
                    entry[1] -= chosen
                    remaining -= chosen
                if not remaining:
                    break
            rows.append({"riga_id": row.pk, "articolo_id": article_id, "teorica": row.quantita, "mancante": remaining})
        return RecipeInputProposal(tuple(selections), tuple(rows))

    @staticmethod
    @transaction.atomic
    def confirm(*, actor, lavorazione, selections):
        require_permission(actor, "can_record_production_consumption")
        selections = tuple(selections)
        if not selections or any(not isinstance(s, InputSelection) or s.riga_ricetta is None for s in selections):
            raise ValidationError("La conferma ricetta richiede selezioni collegate alle righe ricetta.")
        results = InputService.register_many(actor=actor, lavorazione=lavorazione, selections=selections)
        work = results[0].registrazione.lavorazione
        if set(work.ricetta.righe.values_list("pk", flat=True)) != {s.riga_ricetta for s in selections}:
            raise ValidationError("Confermare tutte le righe della ricetta nello stesso tentativo.")
        ids = [result.registrazione.pk for result in results]
        if work.inputs.filter(riga_ricetta__isnull=False).exclude(pk__in=ids).exists():
            raise ValidationError("Gli ingredienti di questa lavorazione sono già stati registrati.")
        return results


def recipe_coverage(work, inputs):
    """Copertura esplicita; compatibilità con gli input strutturali preesistenti.

    Il fallback non scrive associazioni retroattive. Un input strutturale può
    coprire una sola riga non ambigua, solo quando non esistono input da ricetta.
    Quantità teoriche e reali restano distinte: non si inventano tolleranze.
    """
    if not work.ricetta_id:
        return []
    rows = list(work.ricetta.righe.all())
    covered = {record.riga_ricetta_id for record in inputs if record.riga_ricetta_id}
    if not covered:
        for record in inputs:
            matches = [row.pk for row in rows if row.accetta_articolo(record.lotto.articolo)]
            if len(matches) == 1:
                covered.add(matches[0])
    return [f"Ingrediente della ricetta non registrato: riga {row.pk}." for row in rows if row.pk not in covered]
