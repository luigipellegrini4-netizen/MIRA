from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase
from django.utils import timezone

from magazzino.models import Giacenza, Movimento
from magazzino.selectors import StockProposalService
from magazzino.services import MovementService
from .service_fixtures import ServiceFixtures


class ProposalTests(ServiceFixtures, TestCase):
    def propose(self, amount="10", **kwargs):
        return StockProposalService.propose(actor=self.operator, articolo=self.article, quantita=amount, **kwargs)

    def test_fefo_prefers_earliest_expiry(self):
        later = self.receive(code="LATER", data_scadenza=date(2028, 1, 1))
        earlier = self.receive(code="EARLIER", data_scadenza=date(2027, 1, 1))
        self.assertEqual(self.propose().righe[0].lotto_id, earlier.lotto.pk)

    def test_fefo_missing_expiry_last(self):
        self.receive(code="UNKNOWN")
        dated = self.receive(code="DATED", data_scadenza=date(2028, 1, 1))
        self.assertEqual(self.propose().righe[0].lotto_id, dated.lotto.pk)

    def test_fifo_uses_receipt_time_not_lot_id(self):
        self.article.criterio_rotazione = "FIFO"
        self.article.save()
        self.receive(code="NEWER", data_ricevimento=timezone.now())
        older = self.receive(code="OLDER", data_ricevimento=timezone.now() - timedelta(days=5))
        self.assertEqual(self.propose().righe[0].lotto_id, older.lotto.pk)

    def test_split_multiple_lots_and_shortage(self):
        self.receive(code="FIRST", amount="3")
        self.receive(code="SECOND", amount="4")
        proposal = self.propose()
        self.assertEqual([line.quantita for line in proposal.righe], [Decimal("3"), Decimal("4")])
        self.assertEqual(proposal.mancante, 3)

    def test_last_allocation_is_partial(self):
        self.receive(code="FIRST", amount="3")
        self.receive(code="SECOND", amount="10")
        proposal = self.propose(amount="5")
        self.assertEqual([line.quantita for line in proposal.righe], [Decimal("3"), Decimal("2")])
        self.assertEqual(proposal.mancante, 0)

    def test_no_stock_returns_full_shortage(self):
        self.assertEqual(self.propose().mancante, 10)
        self.assertEqual(self.propose().righe, ())

    def test_proposal_never_changes_stock_or_movements(self):
        self.receive()
        before = (list(Giacenza.objects.values_list("pk", "quantita")), Movimento.objects.count())
        self.propose()
        self.assertEqual(before, (list(Giacenza.objects.values_list("pk", "quantita")), Movimento.objects.count()))

    def test_manual_alternative_remains_valid(self):
        first = self.receive(code="FIRST", data_scadenza=date(2027, 1, 1))
        alternative = self.receive(code="ALT", data_scadenza=date(2028, 1, 1))
        self.assertEqual(self.propose().righe[0].lotto_id, first.lotto.pk)
        MovementService.register(actor=self.operator, lotto=alternative.lotto, tipo="CONSUMO", quantita="3", origine=self.position)
        self.assertEqual(Giacenza.objects.get(lotto=alternative.lotto).quantita, 7)
        self.assertEqual(Giacenza.objects.get(lotto=first.lotto).quantita, 10)

    def test_location_filter_and_empty_filter(self):
        self.load(position=self.destination)
        self.assertEqual(self.propose(ubicazioni=[self.location.pk]).mancante, 10)
        self.assertEqual(self.propose(ubicazioni=[]).mancante, 10)
        self.assertEqual(self.propose(ubicazioni=[self.other.pk]).mancante, 0)

    def test_zero_stock_excluded(self):
        self.load()
        MovementService.register(actor=self.operator, lotto=self.lot, tipo="CONSUMO", quantita="10", origine=self.position)
        self.assertEqual(self.propose().righe, ())

    def test_fifo_falls_back_to_first_inbound_movement(self):
        self.article.criterio_rotazione = "FIFO"
        self.article.save()
        self.load()
        self.assertEqual(self.propose().righe[0].lotto_id, self.lot.pk)

    def test_nessuno_has_stable_order_and_serializable_result(self):
        self.article.criterio_rotazione = "NESSUNO"
        self.article.save()
        self.load()
        result = self.propose(amount="2").as_dict()
        self.assertEqual(result["criterio"], "NESSUNO")
        self.assertEqual(result["righe"][0]["lotto_id"], self.lot.pk)
        self.assertEqual(Decimal(result["righe"][0]["quantita"]), Decimal("2"))
