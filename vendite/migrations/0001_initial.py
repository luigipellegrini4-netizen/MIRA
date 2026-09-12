import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):
    initial = True
    dependencies = [("magazzino", "0007_lotto_confezionamento"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [
        migrations.CreateModel(name="Cliente", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("codice", models.CharField(max_length=40, unique=True)), ("ragione_sociale", models.CharField(max_length=180)),
            ("partita_iva", models.CharField(blank=True, max_length=20)), ("indirizzo", models.CharField(blank=True, max_length=250)),
            ("email", models.EmailField(blank=True, max_length=254)), ("telefono", models.CharField(blank=True, max_length=40)),
            ("attivo", models.BooleanField(default=True)),
        ], options={"ordering": ["ragione_sociale", "codice"]}),
        migrations.CreateModel(name="Vendita", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("numero_documento", models.CharField(max_length=60, unique=True)), ("data_documento", models.DateField(default=django.utils.timezone.localdate)),
            ("note", models.TextField(blank=True)), ("registrata_il", models.DateTimeField(default=django.utils.timezone.now)),
            ("cliente", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="vendite", to="vendite.cliente")),
            ("registrata_da", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, to=settings.AUTH_USER_MODEL)),
        ], options={"ordering": ["-data_documento", "-pk"]}),
        migrations.CreateModel(name="RigaVendita", fields=[
            ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
            ("movimento", models.OneToOneField(on_delete=django.db.models.deletion.PROTECT, related_name="riga_vendita", to="magazzino.movimento")),
            ("vendita", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="righe", to="vendite.vendita")),
        ], options={"ordering": ["pk"]}),
    ]
