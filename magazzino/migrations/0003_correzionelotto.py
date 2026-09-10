import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("magazzino", "0002_lotto_lavorazione_origine_and_more"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CorrezioneLotto",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("valori_precedenti", models.JSONField()),
                ("valori_nuovi", models.JSONField()),
                ("motivazione", models.TextField()),
                ("eseguita_il", models.DateTimeField(default=django.utils.timezone.now)),
                ("eseguita_da", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
                ("lotto", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="correzioni", to="magazzino.lotto")),
            ],
            options={"ordering": ["-eseguita_il", "-pk"]},
        ),
    ]
