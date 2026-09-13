from decimal import Decimal

from magazzino.models import Giacenza
from qualita.nc_selectors import quarantine_balances, blocked_quantity


def packaging_availability(lot, total):
    """Limite fisico corrente e limite storico; non prenota giacenze."""
    balances = quarantine_balances(lotto=lot)
    available = Decimal("0")
    for stock in Giacenza.objects.filter(lotto=lot, ubicazione__attiva=True, quantita__gt=0):
        blocked = blocked_quantity(balances, lotto_id=lot.pk, ubicazione_id=stock.ubicazione_id,
                                   scaffale=stock.scaffale, piano=stock.piano)
        available += max(stock.quantita - blocked, Decimal("0"))
    historical = max((total or Decimal("0")) - lot.quantita_confezionata, Decimal("0"))
    return available, min(historical, available)
