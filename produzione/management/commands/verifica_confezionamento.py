"""Diagnosi in sola lettura prima di separare le giacenze confezionate."""
from decimal import Decimal

from django.core.management.base import BaseCommand
from django.db.models import Q, Sum

from magazzino.models import Lotto
from produzione.models import SessioneProduzioneSemplificata


class Command(BaseCommand):
    help = "Elenca saldi e ambiguità del confezionamento senza modificare dati."

    def handle(self, *args, **options):
        lots = Lotto.objects.filter(
            Q(stato_prodotto="PRODOTTO_FINITO") | Q(quantita_confezionata__gt=0)
            | Q(stato_confezionamento__in=["DA_CONFEZIONARE", "PARZIALE", "CONFEZIONATO"])
        ).select_related("articolo").prefetch_related("giacenze__ubicazione", "movimenti").order_by("pk")
        count = issues = 0
        self.stdout.write("Verifica in sola lettura; eseguire mentre non si registrano movimenti.")
        for lot in lots:
            count += 1
            stocks = list(lot.giacenze.all())
            movements = list(lot.movimenti.all())
            physical = sum((s.quantita for s in stocks), Decimal("0"))
            packaged = SessioneProduzioneSemplificata.objects.filter(
                tipo="CONFEZIONAMENTO", stato="CHIUSA", lotto_origine__lotto_prodotto=lot
            ).aggregate(total=Sum("quantita_finale_kg"))["total"] or Decimal("0")
            reasons = []
            if packaged != lot.quantita_confezionata:
                reasons.append(f"sessioni confezionamento {packaged:g}, totale sul lotto {lot.quantita_confezionata:g}")
            balances = {}
            for movement in movements:
                for side, sign in (("origine", -1), ("destinazione", 1)):
                    location = getattr(movement, f"ubicazione_{side}_id")
                    if location is not None:
                        key = (location, getattr(movement, f"scaffale_{side}"), getattr(movement, f"piano_{side}"))
                        balances[key] = balances.get(key, Decimal("0")) + sign * movement.quantita
            actual = {(s.ubicazione_id, s.scaffale, s.piano): s.quantita for s in stocks}
            if any(balances.get(key, 0) != actual.get(key, 0) for key in balances.keys() | actual.keys()):
                reasons.append("giacenze non coincidenti con il saldo dei movimenti per posizione")
            if physical > 0 and not lot.confezionamento_verificato:
                reasons.append("ripartizione confezionato/non confezionato da verificare per posizione; il totale storico non è un saldo corrente")
            if reasons:
                issues += 1
            self.stdout.write(
                f"{'DA VERIFICARE' if reasons else 'SALDI COERENTI'} — lotto #{lot.pk} {lot.codice_lotto}"
                f" · {lot.articolo.codice} — {lot.articolo.descrizione}: giacenza {physical:g}"
                f" {lot.articolo.unita_misura}; confezionato storico {lot.quantita_confezionata:g}."
            )
            for reason in reasons:
                self.stdout.write(f"  - {reason}")
            for stock in stocks:
                if stock.quantita:
                    self.stdout.write(f"  {stock.ubicazione.codice} / {stock.scaffale or '-'} / {stock.piano or '-'}: {stock.quantita:g}"
                        + (f"; confezionati {stock.quantita_confezionata:g}; non confezionati {stock.quantita_non_confezionata:g}"
                           if lot.confezionamento_verificato else "; ripartizione da verificare"))
        self.stdout.write(f"Controllati {count} lotti; {issues} da verificare. Nessun dato modificato.")
