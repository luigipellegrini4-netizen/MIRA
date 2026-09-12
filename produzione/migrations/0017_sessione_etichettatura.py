from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("produzione", "0016_azionencsessionesemplificata_movimento_and_more")]

    operations = [
        migrations.AlterField(
            model_name="sessioneproduzionesemplificata",
            name="tipo",
            field=models.CharField(
                choices=[
                    ("SEMILAVORATO", "Semilavorato"),
                    ("ROBOQBO", "RoboQbo"),
                    ("INVASETTAMENTO", "Invasettamento"),
                    ("ETICHETTATURA", "Etichettatura"),
                ],
                max_length=20,
            ),
        ),
    ]
