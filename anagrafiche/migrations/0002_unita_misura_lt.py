from django.db import migrations, models
from django.db.models import Q


def litri_a_lt(apps, schema_editor):
    apps.get_model("anagrafiche", "Articolo").objects.filter(unita_misura="L").update(unita_misura="LT")


class Migration(migrations.Migration):
    dependencies = [("anagrafiche", "0001_initial")]

    operations = [
        migrations.RemoveConstraint(model_name="articolo", name="articolo_unita_valida"),
        migrations.AlterField(
            model_name="articolo",
            name="unita_misura",
            field=models.CharField(choices=[("KG", "Chilogrammi"), ("LT", "Litri"), ("PZ", "Pezzi")], max_length=2),
        ),
        migrations.RunPython(litri_a_lt, migrations.RunPython.noop),
        migrations.AddConstraint(
            model_name="articolo",
            constraint=models.CheckConstraint(condition=Q(unita_misura__in=["KG", "LT", "PZ"]), name="articolo_unita_valida"),
        ),
    ]
