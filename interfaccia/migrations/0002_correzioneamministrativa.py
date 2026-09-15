import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models
import django.utils.timezone


class Migration(migrations.Migration):
    dependencies = [
        ("interfaccia", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="CorrezioneAmministrativa",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("modello", models.CharField(max_length=100)),
                ("record_id", models.CharField(max_length=50)),
                ("valori_precedenti", models.JSONField()),
                ("valori_nuovi", models.JSONField()),
                ("motivazione", models.TextField()),
                ("eseguita_il", models.DateTimeField(default=django.utils.timezone.now)),
                ("eseguita_da", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
            ],
            options={"ordering": ["-eseguita_il", "-pk"]},
        ),
    ]
