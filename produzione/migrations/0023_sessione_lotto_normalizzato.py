from django.db import migrations, models
import django.db.models.deletion


def collega_lotti_alle_sessioni(apps, schema_editor):
    Sessione = apps.get_model("produzione", "SessioneProduzioneSemplificata")
    Lotto = apps.get_model("magazzino", "Lotto")
    alias = schema_editor.connection.alias
    sessions = Sessione.objects.using(alias).select_related("ricetta", "lotto_origine").order_by("pk")

    for session in sessions:
        if session.lotto_id:
            continue
        if session.tipo == "CONFEZIONAMENTO" and session.lotto_origine_id:
            source = Sessione.objects.using(alias).get(pk=session.lotto_origine_id)
            if source.lotto_id:
                session.lotto_id = source.lotto_id
                session.save(update_fields=["lotto"])
                continue

        state = "GENERICO"
        packaging_state = "NON_APPLICABILE"
        if session.tipo == "INVASETTAMENTO":
            state = "INVASETTATO"
        elif session.tipo == "ETICHETTATURA":
            state = "PRODOTTO_FINITO"
            packaging_state = "DA_CONFEZIONARE"

        lot = Lotto.objects.using(alias).filter(
            articolo_id=session.ricetta.articolo_id,
            tipo="PRODUZIONE",
            codice_lotto=session.lotto_codice,
        ).first()
        if lot is None:
            lot = Lotto.objects.using(alias).create(
                articolo_id=session.ricetta.articolo_id,
                codice_lotto=session.lotto_codice,
                tipo="PRODUZIONE",
                stato_prodotto=state,
                stato_confezionamento=packaging_state,
                quantita_confezionata=0,
                confezionamento_verificato=True,
                data_produzione=session.aperta_il.date() if session.aperta_il else None,
                note=f"Lotto collegato alla produzione storica {session.lotto_codice}",
            )
        session.lotto_id = lot.pk
        session.save(update_fields=["lotto"])


class Migration(migrations.Migration):
    dependencies = [
        ("magazzino", "0008_giacenza_quantita_confezionata_and_more"),
        ("produzione", "0022_rinomina_abbattimento_e_vuoto"),
    ]

    operations = [
        migrations.RenameField(
            model_name="sessioneproduzionesemplificata",
            old_name="lotto_prodotto",
            new_name="lotto",
        ),
        migrations.AlterField(
            model_name="sessioneproduzionesemplificata",
            name="lotto",
            field=models.ForeignKey(
                blank=True,
                null=True,
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sessioni_semplificate",
                to="magazzino.lotto",
            ),
        ),
        migrations.RunPython(collega_lotti_alle_sessioni, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="sessioneproduzionesemplificata",
            name="lotto_codice",
        ),
        migrations.AlterField(
            model_name="sessioneproduzionesemplificata",
            name="lotto",
            field=models.ForeignKey(
                on_delete=django.db.models.deletion.PROTECT,
                related_name="sessioni_semplificate",
                to="magazzino.lotto",
            ),
        ),
    ]
