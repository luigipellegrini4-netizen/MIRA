from django.core.management.base import BaseCommand
from django.db import transaction

from produzione.models import TipoLavorazione

DEFAULT_TYPES = {
    "PREPARAZIONE_SEMILAVORATO": ("Preparazione semilavorato", True),
    "ROBOQBO": ("Roboqbo", True),
    "FORMAZIONE_TANK": ("Formazione tank", True),
    "INVASETTAMENTO": ("Invasettamento", True),
    "PASTORIZZAZIONE": ("Pastorizzazione", False),
    "ABBATTIMENTO_VUOTO": ("Abbattimento e verifica vuoto", False),
    "ETICHETTATURA": ("Etichettatura", True),
    "INSCATOLAMENTO": ("Inscatolamento", False),
}


class Command(BaseCommand):
    help = "Crea i tipi produttivi iniziali senza sovrascrivere configurazioni esistenti."

    @transaction.atomic
    def handle(self, *args, **options):
        count = 0
        for code, (name, generates) in DEFAULT_TYPES.items():
            _, created = TipoLavorazione.objects.get_or_create(codice=code, defaults={"nome": name, "genera_lotto": generates})
            count += created
        self.stdout.write(self.style.SUCCESS(f"Tipi iniziali: {count} creati; configurazioni esistenti conservate."))
