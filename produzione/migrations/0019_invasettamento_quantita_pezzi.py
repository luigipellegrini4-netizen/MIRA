from decimal import Decimal

from django.db import migrations
from django.db.models import Sum


def correggi_quantita_invasettate(apps, schema_editor):
    Sessione = apps.get_model("produzione", "SessioneProduzioneSemplificata")
    Riepilogo = apps.get_model("produzione", "RiepilogoSessioneSemplificata")
    Movimento = apps.get_model("magazzino", "Movimento")
    Giacenza = apps.get_model("magazzino", "Giacenza")

    sessions = Sessione.objects.filter(
        tipo="INVASETTAMENTO",
        stato="CHIUSA",
        lotto_prodotto__isnull=False,
        ricetta__articolo__unita_misura="PZ",
    )

    for session in sessions:
        summary = Riepilogo.objects.filter(sessione_id=session.pk).first()
        if summary is None:
            continue
        old_quantity = Decimal(summary.vasetti_buoni) * summary.peso_netto_g / Decimal("1000")
        new_quantity = Decimal(summary.vasetti_buoni)
        production_movements = Movimento.objects.filter(
            sessione_semplificata_id=session.pk,
            lotto_id=session.lotto_prodotto_id,
            tipo="PRODUZIONE",
        )
        if production_movements.count() != 1:
            continue
        movement = production_movements.first()
        if Movimento.objects.filter(lotto_id=session.lotto_prodotto_id).exclude(pk=movement.pk).exists():
            continue
        stocks = Giacenza.objects.filter(lotto_id=session.lotto_prodotto_id).order_by("pk")
        if stocks.count() != 1:
            continue
        first = stocks.first()
        if (first.ubicazione_id, first.scaffale, first.piano) != (
            movement.ubicazione_destinazione_id, movement.scaffale_destinazione, movement.piano_destinazione
        ):
            continue
        stock_total = stocks.aggregate(total=Sum("quantita"))["total"] or Decimal("0")

        # Corregge automaticamente solo lotti non ancora movimentati dopo la produzione.
        if movement.quantita != old_quantity or stock_total != old_quantity:
            continue
        movement.quantita = new_quantity
        movement.save(update_fields=["quantita"])
        if first:
            first.quantita = new_quantity
            first.save(update_fields=["quantita"])
        session.quantita_finale_kg = new_quantity
        session.save(update_fields=["quantita_finale_kg"])


class Migration(migrations.Migration):
    dependencies = [("produzione", "0018_sessione_confezionamento")]

    operations = [migrations.RunPython(correggi_quantita_invasettate, migrations.RunPython.noop)]
