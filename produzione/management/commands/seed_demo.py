from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from produzione.services.demo_seed import seed_demo


class Command(BaseCommand):
    help = "Crea il dataset DEMO11 di collaudo senza reset, duplicati o password predefinite."

    def handle(self, *args, **options):
        try:
            data = seed_demo()
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS("DEMO11 pronto: 7 utenti, 5 categorie, 3 articoli, 9 lotti, ricetta Fragola v1."))
        self.stdout.write("Nuovi utenti con password inutilizzabile; impostarla con manage.py changepassword demo11_<ruolo>.")
        self.stdout.write("Rilanci successivi conservano password impostate e stock già movimentato.")
