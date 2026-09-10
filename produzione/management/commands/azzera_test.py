import json
from pathlib import Path
from uuid import uuid4

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.utils import timezone

from interfaccia.backup import create_backup


class Command(BaseCommand):
    help = "Svuota i dati di prova conservando utenti, ruoli, articoli e categorie articolo."

    def add_arguments(self, parser):
        parser.add_argument("--confirm", required=True)

    def handle(self, *args, **options):
        if options["confirm"] != "AZZERA_TEST":
            raise CommandError("Conferma non valida. Usare --confirm AZZERA_TEST")
        if connection.vendor != "mysql":
            raise CommandError("Il comando è disponibile soltanto sul database MySQL di MIRA.")

        backup_dir = Path(settings.BASE_DIR) / "backups"
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup_path = backup_dir / (
            "prima_azzera_test_" + timezone.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8] + ".json"
        )
        with backup_path.open("x", encoding="utf-8") as handle:
            json.dump(create_backup(), handle, ensure_ascii=False, indent=2)

        # Queste tabelle formano il catalogo e il sistema di accesso da conservare.
        preserved = {
            "django_migrations",
            "django_content_type",
            "auth_permission",
            "auth_group",
            "auth_group_permissions",
            "auth_user",
            "auth_user_groups",
            "auth_user_user_permissions",
            "anagrafiche_categoriaarticolo",
            "anagrafiche_articolo",
        }
        tables = set(connection.introspection.table_names())
        targets = sorted(tables - preserved)
        quote = connection.ops.quote_name
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS=0")
                for table in targets:
                    cursor.execute("DELETE FROM " + quote(table))
                    cursor.execute("ALTER TABLE " + quote(table) + " AUTO_INCREMENT = 1")
        finally:
            with connection.cursor() as cursor:
                cursor.execute("SET FOREIGN_KEY_CHECKS=1")

        non_empty = []
        with connection.cursor() as cursor:
            for table in targets:
                cursor.execute("SELECT COUNT(*) FROM " + quote(table))
                if cursor.fetchone()[0]:
                    non_empty.append(table)
        if non_empty:
            raise CommandError("Azzeramento incompleto: " + ", ".join(non_empty))

        self.stdout.write(self.style.SUCCESS(
            f"Database di prova azzerato: {len(targets)} tabelle svuotate. "
            f"Conservati utenti, ruoli, articoli e categorie. Backup: {backup_path}"
        ))
