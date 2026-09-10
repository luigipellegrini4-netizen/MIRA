"""Riprende solo la 0001 interrotta dal CHECK incompatibile con MySQL.

Non elimina tabelle, righe o database. Non usa migrate --fake: verifica lo
schema, aggiunge i vincoli mancanti e registra la migration solo alla fine.
"""
from importlib import import_module

from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.recorder import MigrationRecorder
from django.db.migrations.state import ProjectState

APP = "anagrafiche"
MIGRATION = "0001_initial"
TABLES = {f"anagrafiche_{name}" for name in ("fornitore", "ubicazione", "categoriaarticolo", "articolo")}


def normalized_type(value):
    value = value.lower().replace("auto_increment", "").replace(" ", "")
    # Django emette NUMERIC(p,s); information_schema restituisce DECIMAL(p,s).
    # Conservare precisione, scala e attributi: sono parte del confronto.
    if value.startswith("numeric("):
        value = "decimal(" + value[len("numeric("):]
    return "tinyint(1)" if value in {"bool", "boolean"} else value


def validate_columns(model, actual, conn):
    """actual: nome -> (tipo MySQL, nullable). Prima di qualsiasi DDL."""
    expected = {f.column: f for f in model._meta.local_fields}
    if set(actual) != set(expected):
        raise CommandError(f"Colonne inattese in {model._meta.db_table}; nessuna riparazione automatica.")
    for name, field in expected.items():
        column_type, nullable = actual[name]
        expected_type = field.db_type(conn)
        if normalized_type(column_type) != normalized_type(expected_type) or nullable != field.null:
            raise CommandError(
                f"Tipo/nullabilità inattesi: {model._meta.db_table}.{name}. "
                f"Atteso: {expected_type}, nullable={field.null}; "
                f"rilevato: {column_type}, nullable={nullable}."
            )


def foreign_key_present(constraints, field):
    expected = (field.target_field.model._meta.db_table, field.target_field.column)
    matches = [c for c in constraints.values() if c.get("foreign_key") and c["columns"] == [field.column]]
    if any(c["foreign_key"] != expected for c in matches):
        raise CommandError(f"Foreign key inattesa sulla colonna {field.column}.")
    return bool(matches)


class Command(BaseCommand):
    help = "Recupera la migration iniziale anagrafiche su MySQL; senza --apply verifica soltanto."

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Completa lo schema verificato senza eliminare dati.")

    def handle(self, *args, **options):
        if connection.vendor != "mysql":
            raise CommandError("Questo recupero è previsto esclusivamente per MySQL.")
        recorder = MigrationRecorder(connection)
        applied = recorder.applied_migrations()
        if (APP, MIGRATION) in applied:
            self.stdout.write("Migration anagrafiche già registrata. Procedere con migrate.")
            return
        if any(app in {APP, "magazzino"} for app, name in applied):
            raise CommandError("Storia migration inattesa: recupero interrotto.")

        migration = import_module("anagrafiche.migrations.0001_initial").Migration(MIGRATION, APP)
        state = migration.mutate_state(ProjectState())
        models = list(state.apps.get_app_config(APP).get_models())
        pending_fks, pending_checks = [], []
        with connection.cursor() as cursor:
            tables = set(connection.introspection.table_names(cursor))
            if not tables.intersection(TABLES):
                self.stdout.write("Nessuna tabella parziale: eseguire normalmente migrate.")
                return
            if not TABLES.issubset(tables) or any(t.startswith("magazzino_") for t in tables):
                raise CommandError("Schema diverso dall'interruzione prevista: nessuna modifica eseguita.")
            for model in models:
                table = model._meta.db_table
                cursor.execute(f"SELECT 1 FROM {connection.ops.quote_name(table)} LIMIT 1")
                if cursor.fetchone():
                    raise CommandError(f"{table} contiene dati: recupero automatico interrotto, dati conservati.")
                cursor.execute(
                    "SELECT COLUMN_NAME, COLUMN_TYPE, IS_NULLABLE FROM information_schema.COLUMNS "
                    "WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s", [table],
                )
                actual = {name: (kind, nullable == "YES") for name, kind, nullable in cursor.fetchall()}
                validate_columns(model, actual, connection)
                constraints = connection.introspection.get_constraints(cursor, table)
                for field in model._meta.local_fields:
                    if field.primary_key and not any(c.get("primary_key") and c["columns"] == [field.column] for c in constraints.values()):
                        raise CommandError(f"Chiave primaria mancante in {table}.")
                    if field.unique and not field.primary_key and not any(c.get("unique") and c["columns"] == [field.column] for c in constraints.values()):
                        raise CommandError(f"Indice univoco mancante su {table}.{field.column}.")
                    if field.remote_field and not foreign_key_present(constraints, field):
                        pending_fks.append((model, field))
                for constraint in model._meta.constraints:
                    if constraint.name not in constraints:
                        pending_checks.append((model, constraint))
                    elif not constraints[constraint.name].get("check"):
                        raise CommandError(f"Vincolo inatteso: {constraint.name}.")

        self.stdout.write(f"Verificate quattro tabelle vuote. Da completare: {len(pending_fks)} FK, {len(pending_checks)} CHECK.")
        if not options["apply"]:
            self.stdout.write("Nessuna modifica. Aggiungere --apply per completare il recupero.")
            return
        # Le FK di CreateModel erano deferred_sql: l'eccezione nel CHECK può
        # aver impedito anche la loro creazione all'uscita dallo schema editor.
        with connection.schema_editor() as editor:
            for model, field in pending_fks:
                editor.execute(editor._create_fk_sql(model, field, "_fk_%(to_table)s_%(to_column)s"))
            for model, constraint in pending_checks:
                editor.add_constraint(model, constraint)

        # Ricontrolla i vincoli realmente presenti prima di registrare lo stato.
        with connection.cursor() as cursor:
            for model in models:
                constraints = connection.introspection.get_constraints(cursor, model._meta.db_table)
                for field in model._meta.local_fields:
                    if field.remote_field and not foreign_key_present(constraints, field):
                        raise CommandError("Foreign key ancora mancante: migration NON registrata.")
                for constraint in model._meta.constraints:
                    if not constraints.get(constraint.name, {}).get("check"):
                        raise CommandError("CHECK ancora mancante: migration NON registrata.")
        recorder.record_applied(APP, MIGRATION)
        self.stdout.write(self.style.SUCCESS("Recupero completato. Eseguire ora manage.py migrate."))
