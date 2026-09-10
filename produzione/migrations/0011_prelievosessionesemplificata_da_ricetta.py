from django.db import migrations, models


def mark_existing_semifinished_picks(apps, schema_editor):
    Pick = apps.get_model("produzione", "PrelievoSessioneSemplificata")
    Pick.objects.filter(sessione__tipo="SEMILAVORATO").update(da_ricetta=True)


class Migration(migrations.Migration):
    dependencies = [("produzione", "0010_remove_sessioneproduzionesemplificata_sessione_semplice_chiusura_coerente_and_more")]

    operations = [
        migrations.AddField(
            model_name="prelievosessionesemplificata",
            name="da_ricetta",
            field=models.BooleanField(default=False),
        ),
        migrations.RunPython(mark_existing_semifinished_picks, migrations.RunPython.noop),
    ]
