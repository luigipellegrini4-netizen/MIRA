from django.core.management.base import BaseCommand, CommandError
from django.core.exceptions import ValidationError
from produzione.services.azienda_configuration import configure_lines


class Command(BaseCommand):
    help = "Configura le due linee AZ_ senza modificare processi esistenti o creare dati produttivi."

    def add_arguments(self, parser):
        parser.add_argument("--categoria-output", "--categoria-confetture", dest="categoria_output", required=True, type=int)
        parser.add_argument("--categoria-semilavorati", type=int)
        parser.add_argument("--vasetti", required=True, type=int)
        parser.add_argument("--capsule", required=True, type=int)

    def handle(self, *args, **options):
        try:
            result = configure_lines(categoria_output=options["categoria_output"], categoria_semilavorati=options["categoria_semilavorati"],
                articolo_vasetti=options["vasetti"], articolo_capsule=options["capsule"])
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS("Linee semilavorati e confetture configurate; nessuna produzione avviata."))
        for name, station in result["postazioni"].items():
            self.stdout.write(f"Postazione {name}: ID {station.pk}")
