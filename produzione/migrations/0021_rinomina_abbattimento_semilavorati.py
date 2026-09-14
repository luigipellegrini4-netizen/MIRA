from django.db import migrations


def rinomina_abbattimento(apps, schema_editor):
    configurazione = apps.get_model("produzione", "ConfigurazioneControlloSemplificato")
    configurazione.objects.filter(
        ambito="SEMILAVORATO", codice="SHOCK_VUOTO",
    ).update(nome="Abbattimento")


def ripristina_nome(apps, schema_editor):
    configurazione = apps.get_model("produzione", "ConfigurazioneControlloSemplificato")
    configurazione.objects.filter(
        ambito="SEMILAVORATO", codice="SHOCK_VUOTO",
    ).update(nome="Shock termico e vuoto")


class Migration(migrations.Migration):
    dependencies = [
        ("produzione", "0020_sessioneproduzionesemplificata_confezionamento_giacenza"),
    ]

    operations = [
        migrations.RunPython(rinomina_abbattimento, ripristina_nome),
    ]
