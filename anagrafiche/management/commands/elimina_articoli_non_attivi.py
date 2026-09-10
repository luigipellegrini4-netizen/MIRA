from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.db.models.deletion import ProtectedError, RestrictedError

from anagrafiche.models import Articolo


class Command(BaseCommand):
    help = "Elimina tutti gli articoli non attivi, se non sono collegati a dati storici."

    @transaction.atomic
    def handle(self, *args, **options):
        articles = list(Articolo.objects.select_for_update().filter(attivo=False).order_by("codice"))
        if not articles:
            self.stdout.write(self.style.SUCCESS("Nessun articolo non attivo da eliminare."))
            return
        codes = [article.codice for article in articles]
        try:
            for article in articles:
                article.delete()
        except (ProtectedError, RestrictedError) as exc:
            linked = getattr(exc, "protected_objects", getattr(exc, "restricted_objects", ()))
            labels = ", ".join(sorted({obj._meta.label for obj in linked}))
            raise CommandError(
                "Eliminazione annullata: almeno un articolo non attivo è utilizzato"
                + (" da " + labels if labels else "") + "."
            ) from None
        if Articolo.objects.filter(attivo=False).exists():
            raise CommandError("Verifica finale fallita: operazione annullata.")
        self.stdout.write("Eliminati: " + ", ".join(codes))
        self.stdout.write(self.style.SUCCESS(f"Operazione completata: {len(codes)} articoli eliminati."))
