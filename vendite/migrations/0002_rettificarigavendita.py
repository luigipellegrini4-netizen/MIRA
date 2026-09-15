import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("vendite", "0001_initial"),
        ("magazzino", "0008_giacenza_quantita_confezionata_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RettificaRigaVendita",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("differenza", models.DecimalField(decimal_places=6, max_digits=18)),
                ("motivazione", models.TextField()),
                ("eseguita_il", models.DateTimeField(default=django.utils.timezone.now)),
                ("eseguita_da", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("movimento", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="rettifica_riga_vendita", to="magazzino.movimento")),
                ("riga", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="rettifiche", to="vendite.rigavendita")),
            ],
            options={"ordering": ["-eseguita_il", "-pk"]},
        ),
        migrations.AddConstraint(
            model_name="rettificarigavendita",
            constraint=models.CheckConstraint(condition=~models.Q(differenza=0), name="rettifica_vendita_non_zero"),
        ),
    ]
