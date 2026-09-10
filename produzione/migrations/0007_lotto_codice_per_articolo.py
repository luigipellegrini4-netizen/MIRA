from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("produzione", "0006_controllosessionesemplificata_and_more")]

    operations = [
        migrations.AlterField(
            model_name="sessioneproduzionesemplificata",
            name="lotto_codice",
            field=models.CharField(max_length=100),
        ),
    ]
