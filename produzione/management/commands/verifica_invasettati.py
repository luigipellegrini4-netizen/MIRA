import json
from decimal import Decimal

from django.core import serializers
from django.core.management.base import BaseCommand

from interfaccia.backup_validation import stock_differences
from magazzino.models import Movimento, Giacenza
from produzione.models import SessioneProduzioneSemplificata


class Command(BaseCommand):
    help = "Controlla quantità e posizioni dei lotti invasettati PZ senza modificare dati."

    def handle(self, *args, **options):
        sessions = SessioneProduzioneSemplificata.objects.filter(
            tipo="INVASETTAMENTO", stato="CHIUSA", lotto_prodotto__articolo__unita_misura="PZ",
        ).select_related("lotto_prodotto__articolo", "riepilogo_finale")
        checked = issues = 0
        for session in sessions:
            checked += 1
            lot = session.lotto_prodotto
            movements = list(Movimento.objects.filter(lotto=lot))
            stocks = list(Giacenza.objects.filter(lotto=lot))
            records = json.loads(serializers.serialize("json", [*movements, *stocks]))
            differences = stock_differences(records)
            production = sum((m.quantita for m in movements if m.tipo == "PRODUZIONE"), Decimal("0"))
            summary = getattr(session, "riepilogo_finale", None)
            reasons = []
            if summary is None:
                reasons.append("riepilogo mancante")
            elif production != summary.vasetti_buoni:
                reasons.append(f"carico {production:g} PZ, vasetti buoni {summary.vasetti_buoni}")
            for key, expected, actual in differences:
                reasons.append(f"ubicazione #{key[1]} {key[2] or '-'}/{key[3] or '-'}: saldo movimenti {expected:g}, giacenza {actual:g}")
            if reasons:
                issues += 1
                self.stdout.write(f"DA VERIFICARE — lotto #{lot.pk} {lot.codice_lotto} · {lot.articolo.codice}: " + "; ".join(reasons))
            else:
                self.stdout.write(f"COERENTE — lotto #{lot.pk} {lot.codice_lotto} · {lot.articolo.codice}: {production:g} PZ prodotti")
        self.stdout.write(f"Controllati {checked} lotti; {issues} da verificare. Nessun dato modificato.")
