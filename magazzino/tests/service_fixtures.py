from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.core.management import call_command

from accounts.permissions import A, M, OP, RM, RP, RQ
from anagrafiche.models import Articolo, CategoriaArticolo, Fornitore, Ubicazione
from magazzino.models import Lotto
from magazzino.services import Allocation, MovementService, Position, ReceivingService


def setup_inventory(case):
    call_command("bootstrap_roles", verbosity=0)
    for attr, role in (("warehouse", M), ("manager", RM), ("operator", OP), ("quality", RQ), ("administrator", A), ("production", RP)):
        user = get_user_model().objects.create_user(username=attr)
        user.groups.add(Group.objects.get(name=role))
        setattr(case, attr, user)
    case.category = CategoriaArticolo.objects.create(codice="MP", nome="Materie prime")
    case.article = Articolo.objects.create(codice="MELE", descrizione="Mele", categoria=case.category, unita_misura="KG")
    case.supplier = Fornitore.objects.create(codice="F1", ragione_sociale="Fornitore")
    case.location = Ubicazione.objects.create(codice="MAG", nome="Magazzino")
    case.other = Ubicazione.objects.create(codice="BUF", nome="Buffer produzione")
    case.position = Position(case.location.pk, " A ", " 1 ")
    case.destination = Position(case.other.pk)
    case.lot = Lotto.objects.create(articolo=case.article, fornitore=case.supplier, tipo="ACQUISTO", codice_lotto="L1")


class ServiceFixtures:
    @classmethod
    def setUpTestData(cls):
        setup_inventory(cls)

    def load(self, amount="10", lot=None, position=None):
        return MovementService.register(actor=self.warehouse, lotto=lot or self.lot, tipo="CARICO", quantita=amount, destinazione=position or self.position)

    def receive(self, code="NEW", amount="10", **kwargs):
        return ReceivingService.receive(actor=self.warehouse, articolo=self.article, fornitore=self.supplier,
                                        codice_lotto=code, quantita_ricevuta=amount,
                                        destinazioni=[Allocation(self.position, amount)], **kwargs)
