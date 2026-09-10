from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError, RestrictedError

from anagrafiche.models import Articolo


CODES = ("DEMO11_ACIDO", "DEMO11_FRAGOLE", "DEMO11_SEMILAVORATO", "LAO FRAGOLE")


class Command(BaseCommand):
    help = "Elimina i quattro articoli di prova richiesti, soltanto se non sono utilizzati."

    @transaction.atomic
    def handle(self, *args, **options):
        articles = list(Articolo.objects.select_for_update().filter(codice__in=CODES).order_by("codice"))
        found = {article.codice for article in articles}
        missing = [code for code in CODES if code not in found]
        if missing:
            self.stdout.write("Già assenti: " + ", ".join(missing))
        try:
            for article in articles:
                article.delete()
                self.stdout.write(f"Eliminato: {article.codice}")
        except (ProtectedError, RestrictedError) as exc:
            linked = getattr(exc, "protected_objects", getattr(exc, "restricted_objects", ()))
            raise CommandError(
                "Eliminazione annullata: almeno un articolo è collegato ad altri dati. "
                + ", ".join(sorted({obj._meta.label for obj in linked}))
            ) from None
        if Articolo.objects.filter(codice__in=CODES).exists():
            raise CommandError("Verifica finale fallita: nessuna modifica confermata.")
        self.stdout.write(self.style.SUCCESS(f"Operazione completata: {len(articles)} articoli eliminati."))
