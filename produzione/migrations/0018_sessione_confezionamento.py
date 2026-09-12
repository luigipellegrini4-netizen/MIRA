from django.db import migrations, models


def mark_labelled_lots(apps, schema_editor):
    Session = apps.get_model("produzione", "SessioneProduzioneSemplificata")
    Lotto = apps.get_model("magazzino", "Lotto")
    ids = Session.objects.filter(tipo="ETICHETTATURA", lotto_prodotto__isnull=False).values_list("lotto_prodotto_id", flat=True)
    Lotto.objects.filter(pk__in=ids).update(stato_confezionamento="DA_CONFEZIONARE")


class Migration(migrations.Migration):
    dependencies = [("produzione", "0017_sessione_etichettatura"), ("magazzino", "0007_lotto_confezionamento")]
    operations = [
        migrations.AlterField(model_name="sessioneproduzionesemplificata", name="tipo", field=models.CharField(choices=[("SEMILAVORATO", "Semilavorato"), ("ROBOQBO", "RoboQbo"), ("INVASETTAMENTO", "Invasettamento"), ("ETICHETTATURA", "Etichettatura"), ("CONFEZIONAMENTO", "Confezionamento")], max_length=20)),
        migrations.RunPython(mark_labelled_lots, migrations.RunPython.noop),
    ]
