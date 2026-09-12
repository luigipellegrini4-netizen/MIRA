from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("magazzino", "0006_lotto_stato_prodotto")]
    operations = [
        migrations.AddField(model_name="lotto", name="quantita_confezionata", field=models.DecimalField(decimal_places=6, default=0, max_digits=18)),
        migrations.AddField(model_name="lotto", name="stato_confezionamento", field=models.CharField(choices=[("NON_APPLICABILE", "Non applicabile"), ("DA_CONFEZIONARE", "Da confezionare"), ("PARZIALE", "Parzialmente confezionato"), ("CONFEZIONATO", "Confezionato")], default="NON_APPLICABILE", max_length=20)),
    ]
