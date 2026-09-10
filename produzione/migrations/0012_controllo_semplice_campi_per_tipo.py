from django.db import migrations, models
from django.db.models import Q


def normalizza_campi_controllo(apps, schema_editor):
    Controllo = apps.get_model("produzione", "ControlloSessioneSemplificata")
    Controllo.objects.filter(tipo="BATCH").update(
        gradi_brix=None, ph=None, esito_pastorizzazione="", esito_shock_vuoto="",
    )
    Controllo.objects.filter(tipo="TANK").update(
        inizio=None, fine=None, esito_tracciato_termico="",
        esito_pastorizzazione="", esito_shock_vuoto="",
    )
    Controllo.objects.filter(tipo="CARRELLO").update(
        inizio=None, fine=None, esito_tracciato_termico="", gradi_brix=None, ph=None,
    )


class Migration(migrations.Migration):
    dependencies = [
        ("produzione", "0011_prelievosessionesemplificata_da_ricetta"),
    ]

    operations = [
        migrations.RunPython(normalizza_campi_controllo, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="controllosessionesemplificata",
            constraint=models.CheckConstraint(
                condition=(
                    Q(tipo="BATCH", gradi_brix__isnull=True, ph__isnull=True,
                      esito_pastorizzazione="", esito_shock_vuoto="")
                    | Q(tipo="TANK", inizio__isnull=True, fine__isnull=True,
                        esito_tracciato_termico="", esito_pastorizzazione="", esito_shock_vuoto="")
                    | Q(tipo="CARRELLO", inizio__isnull=True, fine__isnull=True,
                        esito_tracciato_termico="", gradi_brix__isnull=True, ph__isnull=True)
                ),
                name="controllo_semplice_campi_per_tipo",
            ),
        ),
    ]
