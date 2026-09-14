from django.db import migrations


def rinomina_abbattimento_e_vuoto(apps, schema_editor):
    configurazione = apps.get_model("produzione", "ConfigurazioneControlloSemplificato")
    configurazione.objects.filter(
        ambito="SEMILAVORATO", codice="SHOCK_VUOTO",
    ).update(nome="Abbattimento e vuoto")


def ripristina_nome(apps, schema_editor):
    configurazione = apps.get_model("produzione", "ConfigurazioneControlloSemplificato")
    configurazione.objects.filter(
        ambito="SEMILAVORATO", codice="SHOCK_VUOTO",
    ).update(nome="Abbattimento")


class Migration(migrations.Migration):
    dependencies = [
        ("produzione", "0021_rinomina_abbattimento_semilavorati"),
    ]

    operations = [
        migrations.RunPython(rinomina_abbattimento_e_vuoto, ripristina_nome),
    ]
