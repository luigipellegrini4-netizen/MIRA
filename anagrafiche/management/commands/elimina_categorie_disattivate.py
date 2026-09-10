from django.core.management.base import BaseCommand, CommandError
from django.db import transaction

from anagrafiche.models import CategoriaArticolo


CODES = ("MARM", "MP CONF")


class Command(BaseCommand):
    help = "Elimina le categorie disattivate MARM e MP CONF se non sono utilizzate."

    @transaction.atomic
    def handle(self, *args, **options):
        rows = list(CategoriaArticolo.objects.select_for_update().filter(codice__in=CODES))
        found = {row.codice for row in rows}
        missing = [code for code in CODES if code not in found]
        if missing:
            raise CommandError("Categorie non trovate: " + ", ".join(missing))

        errors = []
        for row in rows:
            if row.attiva:
                errors.append(f"{row.codice} è ancora attiva")
            if row.articoli.exists():
                errors.append(f"{row.codice} contiene {row.articoli.count()} articoli")
            if row.figli.exists():
                errors.append(f"{row.codice} contiene {row.figli.count()} sottocategorie")
        if errors:
            raise CommandError("Eliminazione annullata: " + "; ".join(errors))

        for row in rows:
            code = row.codice
            row.delete()
            self.stdout.write(f"Eliminata: {code}")
        self.stdout.write(self.style.SUCCESS("Categorie MARM e MP CONF eliminate."))
