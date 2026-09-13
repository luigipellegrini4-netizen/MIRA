from decimal import Decimal

from magazzino.models import Giacenza
from qualita.nc_selectors import quarantine_balances, blocked_quantity


def packaging_availability(lot, total):
    """Disponibilità fisica libera e quota non confezionata libera."""
    balances = quarantine_balances(lotto=lot)
    loose_balances = quarantine_balances(lotto=lot, componente="SFUSO")
    available = Decimal("0")
    remaining = Decimal("0")
    for stock in Giacenza.objects.filter(lotto=lot, ubicazione__attiva=True, quantita__gt=0):
        blocked = blocked_quantity(balances, lotto_id=lot.pk, ubicazione_id=stock.ubicazione_id,
                                   scaffale=stock.scaffale, piano=stock.piano)
        available += max(stock.quantita - blocked, Decimal("0"))
        loose_blocked = blocked_quantity(loose_balances, lotto_id=lot.pk, ubicazione_id=stock.ubicazione_id,
                                         scaffale=stock.scaffale, piano=stock.piano)
        remaining += max(stock.quantita_non_confezionata - loose_blocked, Decimal("0"))
    return available, remaining if lot.confezionamento_verificato else Decimal("0")
