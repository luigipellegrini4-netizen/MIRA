"""Dataset DEMO11: namespace riservato, nessun reset o aggiornamento di dati altrui."""
from datetime import date, datetime, timezone as dt_timezone
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import transaction
from accounts.permissions import A, RP, RM, RQ, OP, M
from anagrafiche.models import CategoriaArticolo, Articolo, Fornitore, Ubicazione
from magazzino.models import Lotto
from magazzino.services import Allocation, Position, ReceivingService
from produzione.models import TipoLavorazione, RequisitoOutputTipoLavorazione, Ricetta
from .recipes import RecipeService

TAG = "MIRA DEMO11"


def ensure(model, lookup, values):
    obj = model.objects.filter(**lookup).first()
    if obj is None:
        return model.objects.create(**lookup, **values)
    for key, expected in values.items():
        actual = getattr(obj, key)
        if actual != expected:
            raise ValidationError(f"Collisione o configurazione demo alterata: {model.__name__} {lookup}, campo {key}. Nessun dato sovrascritto.")
    return obj


@transaction.atomic
def seed_demo():
    # Serializza rilanci concorrenti, anche a namespace ancora vuoto.
    ct = ContentType.objects.get_for_model(TipoLavorazione)
    ContentType.objects.select_for_update().get(pk=ct.pk)
    call_command("bootstrap_roles", verbosity=0)
    roles = {"admin": [A], "produzione": [RP], "magazzino": [RM], "qualita": [RQ],
             "operatore": [OP], "magazziniere": [M], "multi": [OP, RM]}
    users = {}
    User = get_user_model()
    for key, groups in roles.items():
        username = f"demo11_{key}"
        user = User.objects.filter(username=username).first()
        if user is None:
            user = User.objects.create_user(username=username, password=None, is_staff=True, last_name=TAG)
            user.groups.set(Group.objects.filter(name__in=groups))
        elif user.last_name != TAG or user.is_superuser or not user.is_active or not user.is_staff or set(user.groups.values_list("name", flat=True)) != set(groups) or user.user_permissions.exists():
            raise ValidationError(f"Utente {username} già presente o modificato: non verrà sovrascritto.")
        users[key] = user
    categories = {}
    for key, name in (("MP", "Materie prime"), ("SL", "SEMILAVORATI"), ("MOCA", "MOCA / packaging"), ("MARM", "Produzione marmellata"), ("PF", "Prodotti finiti commerciali")):
        categories[key] = ensure(CategoriaArticolo, {"codice": f"DEMO11_{key}"}, {"nome": name, "note": TAG, "attiva": True})
    articles = {}
    for key, name, cat, rotation in (("FRAGOLE", "FRAGOLE GELO", "MP", "FEFO"), ("ACIDO", "ACIDO ASCORBICO", "MP", "FIFO"), ("SEMILAVORATO", "SEMILAVORATO FRAGOLA", "SL", "FEFO")):
        articles[key] = ensure(Articolo, {"codice": f"DEMO11_{key}"}, {"descrizione": name, "categoria": categories[cat],
            "unita_misura": "KG", "criterio_rotazione": rotation, "tracciabilita_lotto": True, "attivo": True, "note": TAG})
    supplier = ensure(Fornitore, {"codice": "DEMO11_FORN"}, {"ragione_sociale": "Fornitore collaudo DEMO11", "note": TAG})
    locations = {key: ensure(Ubicazione, {"codice": f"DEMO11_{key}"}, {"nome": f"Collaudo {key}", "note": TAG, "attiva": True})
                 for key in ("MAG", "C", "D", "BUFFER_PRODUZIONE", "QUARANTENA")}
    kind = ensure(TipoLavorazione, {"codice": "PRODUZIONE_SEMILAVORATI"}, {"nome": "Produzione semilavorati", "attivo": True, "genera_lotto": True, "note": TAG})
    if kind.requisiti_input.exists():
        raise ValidationError("Il tipo demo non deve duplicare gli ingredienti nei requisiti input.")
    output = ensure(RequisitoOutputTipoLavorazione, {"tipo_lavorazione": kind, "nome": "Semilavorato prodotto"},
        {"categoria_articolo": categories["SL"], "articolo": None, "obbligatorio": True, "multiplo": False, "tipo_output": "PRINCIPALE", "prefisso_lotto": "SL", "note": TAG})
    recipe = Ricetta.objects.filter(articolo=articles["SEMILAVORATO"], versione="1").first()
    if recipe is None:
        recipe = RecipeService.create(actor=users["produzione"], articolo=articles["SEMILAVORATO"], nome="Semilavorato Fragola", versione="1", note=TAG)
        RecipeService.add_line(actor=users["produzione"], ricetta=recipe, articolo=articles["FRAGOLE"], quantita="10.000")
        RecipeService.add_line(actor=users["produzione"], ricetta=recipe, articolo=articles["ACIDO"], quantita="0.050")
    from decimal import Decimal
    if recipe.note != TAG or recipe.nome != "Semilavorato Fragola" or not recipe.attiva or list(recipe.righe.order_by("pk").values_list("articolo_id", "quantita")) != [(articles["FRAGOLE"].pk, Decimal("10")), (articles["ACIDO"].pk, Decimal("0.05"))]:
        raise ValidationError("Ricetta demo presente ma incompatibile: nessuna modifica automatica.")
    stocks = [
        ("F_A", "FRAGOLE", "MAG", "40", date(2030, 1, 1), 1),
        ("F_B", "FRAGOLE", "MAG", "40", date(2030, 2, 1), 2),
        ("A_A", "ACIDO", "MAG", "1", date(2031, 2, 1), 1),
        ("A_B", "ACIDO", "MAG", "1", date(2031, 1, 1), 2),
        ("FC_A", "FRAGOLE", "C", "6", date(2030, 1, 1), 1),
        ("FC_B", "FRAGOLE", "C", "8", date(2030, 2, 1), 2),
        ("AC", "ACIDO", "C", "1", date(2031, 1, 1), 1),
        ("FD", "FRAGOLE", "D", "10", date(2030, 1, 1), 1),
        ("AD", "ACIDO", "D", "0.010", date(2031, 1, 1), 1),
    ]
    lots = {}
    for code, article, location, amount, expiry, day in stocks:
        code_full = f"DEMO11_{code}"
        existing = Lotto.objects.filter(articolo=articles[article], fornitore=supplier, codice_lotto=code_full).first()
        if existing is None:
            existing = ReceivingService.receive(actor=users["magazziniere"], articolo=articles[article], fornitore=supplier,
                codice_lotto=code_full, quantita_ricevuta=amount, data_scadenza=expiry,
                data_ricevimento=datetime(2026, 1, day, 9, tzinfo=dt_timezone.utc),
                numero_ddt=code_full, note=TAG, destinazioni=[Allocation(Position(locations[location].pk), amount)]).lotto
        elif existing.tipo != "ACQUISTO" or existing.data_scadenza != expiry:
            raise ValidationError(f"Lotto {code_full} non riconosciuto come demo.")
        receipt = existing.ricevimenti.filter(numero_ddt=code_full).first()
        if receipt is None or receipt.note != TAG or receipt.quantita_ricevuta != Decimal(amount) or existing.ricevimenti.count() != 1:
            raise ValidationError(f"Ricevimento demo alterato: {code_full}.")
        lots[code] = existing
    return dict(users=users, categories=categories, articles=articles, supplier=supplier, locations=locations,
                kind=kind, output=output, recipe=recipe, lots=lots)
