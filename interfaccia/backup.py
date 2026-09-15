import json
from pathlib import Path
from uuid import uuid4
from django.apps import apps
from django.conf import settings
from django.core import serializers
from django.core.exceptions import ValidationError
from django.db import connection, transaction, IntegrityError
from django.utils import timezone
from .backup_validation import validate_records

FORMAT = "MIRA_BACKUP_V4"
EXCLUDED = {"migrations.Migration"}


def backup_models():
    return tuple(sorted((m for m in apps.get_models() if m._meta.label not in EXCLUDED), key=lambda m: m._meta.label))


def create_backup():
    records, counts = [], {}
    for model in backup_models():
        fields = [f.name for f in [*model._meta.fields, *model._meta.local_many_to_many]
                  if not getattr(f, "generated", False)]
        data = json.loads(serializers.serialize("json", model.objects.order_by("pk"), fields=fields))
        records.extend(data); counts[model._meta.label] = len(data)
    return {"format": FORMAT, "created_at": timezone.now().isoformat(),
            "models": [m._meta.label for m in backup_models()], "counts": counts, "records": records}


def read_backup(raw):
    try:
        payload = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise ValidationError("Il file non è un JSON MIRA valido.") from None
    expected = [m._meta.label for m in backup_models()]
    if not isinstance(payload, dict) or payload.get("format") not in {FORMAT, "MIRA_BACKUP_V1", "MIRA_BACKUP_V2", "MIRA_BACKUP_V3"}:
        raise ValidationError("Il backup non è compatibile con questa versione di MIRA.")
    # I backup precedenti non contengono gli storici introdotti in V4.
    new_models = {"interfaccia.CorrezioneAmministrativa", "vendite.RettificaRigaVendita"}
    old_models = [label for label in expected if label not in new_models]
    if payload.get("models") == old_models and payload.get("format") != FORMAT:
        if not isinstance(payload.get("counts"), dict):
            raise ValidationError("Struttura del backup incompleta.")
        payload["models"] = expected
        for label in new_models:
            payload["counts"][label] = 0
    if payload.get("models") != expected:
        raise ValidationError("Il backup è stato creato con un insieme diverso di tabelle MIRA.")
    if not isinstance(payload.get("records"), list) or not isinstance(payload.get("counts"), dict):
        raise ValidationError("Struttura del backup incompleta.")
    if payload["format"] == "MIRA_BACKUP_V1":
        upgrade_packaging_backup(payload)
    if payload["format"] == "MIRA_BACKUP_V2":
        upgrade_session_lot_backup(payload)
    if payload["format"] == "MIRA_BACKUP_V3":
        payload["format"] = FORMAT
    allowed = {model._meta.label_lower for model in backup_models()}
    actual = {label: 0 for label in expected}
    for record in payload["records"]:
        label = record.get("model") if isinstance(record, dict) else None
        if label not in allowed or "pk" not in record or not isinstance(record.get("fields"), dict):
            raise ValidationError("Il backup contiene un record o un modello non ammesso.")
        model = apps.get_model(label)
        actual[model._meta.label] += 1
    if actual != payload["counts"]:
        raise ValidationError("Il numero dei record non corrisponde all’indice del backup.")
    try:
        validate_records(payload["records"])
    except (ValueError, TypeError, KeyError) as exc:
        raise ValidationError("Valori o riferimenti non validi nel backup.") from exc
    return payload


def upgrade_packaging_backup(payload):
    """I backup precedenti non contengono una ripartizione per posizione."""
    from decimal import Decimal
    records = payload["records"]
    lots = {str(r["pk"]): r["fields"] for r in records if r["model"] == "magazzino.lotto"}
    sessions = {str(r["pk"]): r["fields"] for r in records if r["model"] == "produzione.sessioneproduzionesemplificata"}
    ambiguous = set()
    try:
        for pk, lot in lots.items():
            if Decimal(str(lot.get("quantita_confezionata", 0))) > 0:
                ambiguous.add(pk)
        for session in sessions.values():
            if session.get("tipo") == "CONFEZIONAMENTO" and session.get("stato") == "CHIUSA" and Decimal(str(session.get("quantita_finale_kg") or 0)) > 0:
                source = sessions.get(str(session.get("lotto_origine")), {})
                ambiguous.add(str(source.get("lotto_prodotto")))
            session.setdefault("confezionamento_giacenza", None)
    except ArithmeticError as exc:
        raise ValidationError("Quantità non valida nel backup precedente.") from exc
    for pk, lot in lots.items():
        lot.setdefault("confezionamento_verificato", pk not in ambiguous)
    for record in records:
        fields = record["fields"]
        if record["model"] == "magazzino.giacenza":
            fields.setdefault("quantita_confezionata", "0")
        elif record["model"] == "magazzino.movimento":
            lot = lots.get(str(fields.get("lotto")), {})
            fields.setdefault("componente", "SFUSO" if lot.get("stato_prodotto") == "PRODOTTO_FINITO" and lot.get("confezionamento_verificato") else "")
    payload["format"] = "MIRA_BACKUP_V2"


def upgrade_session_lot_backup(payload):
    """Normalizza i backup nei quali il codice era duplicato nella sessione."""
    records = payload["records"]
    session_records = [r for r in records if r["model"] == "produzione.sessioneproduzionesemplificata"]
    sessions = {str(r["pk"]): r["fields"] for r in session_records}
    recipes = {
        str(r["pk"]): r["fields"] for r in records
        if r["model"] == "produzione.ricetta"
    }
    lot_records = [r for r in records if r["model"] == "magazzino.lotto"]
    lots_by_key = {
        (str(r["fields"].get("articolo")), r["fields"].get("codice_lotto"), r["fields"].get("tipo")): r["pk"]
        for r in lot_records
    }
    next_lot_pk = max((int(r["pk"]) for r in lot_records), default=0) + 1

    for record in session_records:
        fields = record["fields"]
        old_lot = fields.pop("lotto_prodotto", None)
        code = fields.pop("lotto_codice", "")
        if old_lot:
            fields["lotto"] = old_lot
            continue
        if fields.get("tipo") == "CONFEZIONAMENTO":
            continue
        recipe = recipes.get(str(fields.get("ricetta")), {})
        article_id = recipe.get("articolo")
        key = (str(article_id), code, "PRODUZIONE")
        lot_pk = lots_by_key.get(key)
        if lot_pk is None:
            product_state = "INVASETTATO" if fields.get("tipo") == "INVASETTAMENTO" else "GENERICO"
            packaging_state = "NON_APPLICABILE"
            if fields.get("tipo") == "ETICHETTATURA":
                product_state = "PRODOTTO_FINITO"
                packaging_state = "DA_CONFEZIONARE"
            lot_pk = next_lot_pk
            next_lot_pk += 1
            new_record = {
                "model": "magazzino.lotto",
                "pk": lot_pk,
                "fields": {
                    "articolo": article_id,
                    "codice_lotto": code,
                    "tipo": "PRODUZIONE",
                    "stato_prodotto": product_state,
                    "stato_confezionamento": packaging_state,
                    "quantita_confezionata": "0",
                    "confezionamento_verificato": True,
                    "fornitore": None,
                    "data_produzione": (fields.get("aperta_il") or "")[:10] or None,
                    "data_scadenza": None,
                    "note": f"Lotto recuperato dal backup per la produzione {code}",
                    "lavorazione_origine": None,
                },
            }
            records.append(new_record)
            lot_records.append(new_record)
            lots_by_key[key] = lot_pk
        fields["lotto"] = lot_pk

    for fields in sessions.values():
        if fields.get("tipo") != "CONFEZIONAMENTO" or fields.get("lotto"):
            continue
        source = sessions.get(str(fields.get("lotto_origine")), {})
        fields["lotto"] = source.get("lotto")

    payload["counts"]["magazzino.Lotto"] = len(lot_records)
    payload["format"] = FORMAT


def restore_backup(payload):
    if connection.vendor not in {"mysql", "sqlite"}:
        raise ValidationError("Ripristino disponibile su MySQL e SQLite.")
    payload = read_backup(json.dumps(payload).encode("utf-8"))
    objects = validate_records(payload["records"])
    models = backup_models()
    tables = []
    for model in models:
        tables.extend(field.remote_field.through._meta.db_table for field in model._meta.local_many_to_many)
        tables.append(model._meta.db_table)
    quote = connection.ops.quote_name
    try:
        with transaction.atomic():
            with connection.cursor() as cursor:
                if connection.vendor == "mysql":
                    cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                else:
                    cursor.execute("PRAGMA defer_foreign_keys=ON")
                for table in dict.fromkeys(tables):
                    cursor.execute("DELETE FROM " + quote(table))
            for item in objects:
                item.save()
            connection.check_constraints(table_names=list(dict.fromkeys(tables)))
            for model in models:
                if model.objects.count() != payload["counts"][model._meta.label]:
                    raise ValidationError("Verifica del ripristino fallita per " + model._meta.label)
    except IntegrityError as exc:
        raise ValidationError("Ripristino annullato: vincoli del database non rispettati.") from exc
    finally:
        if connection.vendor == "mysql":
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")


@transaction.atomic
def reset_trial_data():
    if connection.vendor != "mysql":
        raise ValidationError("L’azzeramento è disponibile soltanto sul database MySQL di MIRA.")
    from anagrafiche.models import Articolo
    from magazzino.management.commands.inizializza_confetture import dependencies, reset_models
    from produzione.models import Ricetta, RigaRicetta
    from produzione.services.azienda_common import business_mutex

    business_mutex()
    models = (*reset_models(True), RigaRicetta, Ricetta)
    blocked = dependencies(models)
    if blocked:
        raise ValidationError(["Alcuni dati esterni impediscono l’azzeramento.", *blocked])
    for model in (*models, Articolo):
        list(model.objects.select_for_update().order_by("pk").values_list("pk", flat=True))

    backup_dir = Path(settings.BASE_DIR) / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / ("prima_azzeramento_" + timezone.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8] + ".json")
    with backup_path.open("x", encoding="utf-8") as handle:
        json.dump(create_backup(), handle, ensure_ascii=False, indent=2)

    quote = connection.ops.quote_name
    with connection.cursor() as cursor:
        for model in models:
            ids = list(model.objects.order_by("pk").values_list("pk", flat=True))
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                cursor.execute("DELETE FROM " + quote(model._meta.db_table) + " WHERE id IN (" + ",".join(["%s"] * len(batch)) + ")", batch)

        protected_articles = set()
        for model in apps.get_models():
            if model in {*models, Articolo}:
                continue
            for field in model._meta.fields:
                if field.is_relation and field.related_model is Articolo:
                    protected_articles.update(model.objects.exclude(**{field.name: None}).values_list(field.name, flat=True))
        removable = list(Articolo.objects.exclude(pk__in=protected_articles).values_list("pk", flat=True))
        for start in range(0, len(removable), 500):
            batch = removable[start:start + 500]
            cursor.execute("DELETE FROM " + quote(Articolo._meta.db_table) + " WHERE id IN (" + ",".join(["%s"] * len(batch)) + ")", batch)

    if any(model.objects.exists() for model in models):
        raise ValidationError("Nuovi dati inseriti durante l’azzeramento: operazione annullata.")
    return backup_path, len(removable), len(protected_articles)
