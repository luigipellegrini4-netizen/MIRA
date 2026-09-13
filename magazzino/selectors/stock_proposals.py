from dataclasses import dataclass
from decimal import Decimal

from django.core.exceptions import PermissionDenied, ValidationError
from django.db.models import DateTimeField, F, OuterRef, Subquery
from django.db.models.functions import Coalesce

from anagrafiche.models import Articolo
from magazzino.models import Giacenza, Movimento, RicevimentoLotto
from magazzino.services.types import Position, persisted_id, quantity


@dataclass(frozen=True)
class ProposalLine:
    giacenza_id: int
    lotto_id: int
    codice_lotto: str
    posizione: Position
    quantita: Decimal
    data_scadenza: object


@dataclass(frozen=True)
class StockProposal:
    articolo_id: int
    criterio: str
    quantita_richiesta: Decimal
    mancante: Decimal
    righe: tuple

    def as_dict(self):
        return {
            "articolo_id": self.articolo_id, "criterio": self.criterio,
            "quantita_richiesta": str(self.quantita_richiesta), "mancante": str(self.mancante),
            "righe": [{
                "giacenza_id": row.giacenza_id, "lotto_id": row.lotto_id, "codice_lotto": row.codice_lotto,
                "ubicazione_id": row.posizione.ubicazione_id, "scaffale": row.posizione.scaffale,
                "piano": row.posizione.piano, "quantita": str(row.quantita),
                "data_scadenza": row.data_scadenza.isoformat() if row.data_scadenza else None,
            } for row in self.righe],
        }


def order_stocks(stocks, article):
    """Stesso ordine di rotazione per previsione, selezione e consumo."""
    receipts = RicevimentoLotto.objects.filter(lotto_id=OuterRef("lotto_id")).order_by("data_ricevimento", "pk")
    entries = Movimento.objects.filter(lotto_id=OuterRef("lotto_id"), ubicazione_origine__isnull=True).order_by("data_ora", "pk")
    stocks = stocks.annotate(primo_ingresso=Coalesce(
        Subquery(receipts.values("data_ricevimento")[:1]),
        Subquery(entries.values("data_ora")[:1]), output_field=DateTimeField(),
    ))
    stable = [F("primo_ingresso").asc(nulls_last=True), "lotto_id", "pk"]
    if article.criterio_rotazione == Articolo.CriterioRotazione.FEFO:
        return stocks.order_by(F("lotto__data_scadenza").asc(nulls_last=True), *stable)
    if article.criterio_rotazione == Articolo.CriterioRotazione.FIFO:
        return stocks.order_by(*stable)
    return stocks.order_by("lotto_id", "pk")


class StockProposalService:
    @staticmethod
    def propose(*, actor, articolo, quantita, ubicazioni=None):
        if not actor or not actor.is_authenticated or not actor.is_active or not actor.has_perm("magazzino.view_giacenza"):
            raise PermissionDenied("È richiesto il permesso di consultazione delle giacenze.")
        amount = quantity(quantita)
        try:
            article = Articolo.objects.get(pk=persisted_id(articolo, "Articolo"))
        except Articolo.DoesNotExist:
            raise ValidationError("Articolo inesistente.") from None
        # Una proposta non prenota stock, non registra movimenti e non impone
        # alcun lotto al successivo servizio di consumo.
        stocks = Giacenza.objects.filter(lotto__articolo=article, quantita__gt=0, ubicazione__attiva=True).select_related("lotto")
        if ubicazioni is not None:
            ids = [persisted_id(u, "Ubicazione") for u in ubicazioni]
            stocks = stocks.filter(ubicazione_id__in=ids)
        stocks = order_stocks(stocks, article)
        remaining, lines = amount, []
        from qualita.nc_selectors import quarantine_balances, blocked_quantity
        held_by_lot = {}
        for stock in stocks.iterator():
            if stock.lotto_id not in held_by_lot:
                held_by_lot[stock.lotto_id] = quarantine_balances(lotto=stock.lotto_id)
            blocked = blocked_quantity(held_by_lot[stock.lotto_id], lotto_id=stock.lotto_id,
                ubicazione_id=stock.ubicazione_id, scaffale=stock.scaffale, piano=stock.piano)
            selected = min(max(Decimal(0), stock.quantita - blocked), remaining)
            if selected == 0:
                continue
            lines.append(ProposalLine(stock.pk, stock.lotto_id, stock.lotto.codice_lotto,
                                      Position(stock.ubicazione_id, stock.scaffale, stock.piano), selected,
                                      stock.lotto.data_scadenza))
            remaining -= selected
            if remaining == 0:
                break
        return StockProposal(article.pk, article.criterio_rotazione, amount, remaining, tuple(lines))
