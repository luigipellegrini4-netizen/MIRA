from functools import wraps
from decimal import Decimal, ROUND_HALF_UP, InvalidOperation
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from accounts.permissions import require_permission
from anagrafiche.models import Articolo
from magazzino.models import Lotto
from magazzino.services.types import quantity
from produzione.models import (LineaProduttiva, TurnoOperativo, CodiceProduzione,
    SessioneInvasettamento, RiepilogoInvasettamento)
from produzione.models.azienda import azienda_write, in_scope
from .locking import get_record


def business_mutex():
    """Serializza solo le brevi transazioni dei flussi aziendali, non il lavoro fisico.

    Ordine: mutex aziendale → tipi/ricette/cicli/lavori → lotti → ubicazioni.
    Evita ordini opposti tra chiusura turno, rilascio tank e sessioni concorrenti.
    """
    ct = ContentType.objects.get_for_model(LineaProduttiva)
    ContentType.objects.select_for_update().get(pk=ct.pk)


def business_atomic(method):
    @wraps(method)
    @transaction.atomic
    def wrapped(*args, **kwargs):
        business_mutex()
        return method(*args, **kwargs)
    return wrapped


def rounded(value):
    from django.core.validators import DecimalValidator
    try:
        result = value.quantize(Decimal(".000001"), rounding=ROUND_HALF_UP)
    except InvalidOperation:
        raise ValidationError("Risultato fuori dall'intervallo numerico supportato.") from None
    DecimalValidator(18, 6)(result)
    return result


def count(value, label, positive=False):
    if isinstance(value, bool) or not isinstance(value, int) or value < (1 if positive else 0) or value > 2147483647:
        raise ValidationError(f"{label}: specificare un intero {'positivo' if positive else 'non negativo'} valido.")
    return value


def totals(*, buoni, scarti, capsule_difettose, peso_g, teorico):
    count(buoni, "Vasetti buoni")
    count(scarti, "Vasetti da scartare")
    count(capsule_difettose, "Capsule difettose")
    jars = count(buoni + scarti, "Totale vasetti", positive=True)
    caps = count(jars + capsule_difettose, "Totale capsule", positive=True)
    weight, theoretical = quantity(peso_g), quantity(teorico)
    real = rounded(Decimal(jars) * weight / 1000)
    good = rounded(Decimal(buoni) * weight / 1000)
    if real <= 0 or (buoni and good <= 0):
        raise ValidationError("Peso inferiore alla precisione di magazzino.")
    return dict(vasetti=jars, capsule=caps, massa_reale=real, massa_buona=good,
        resa=rounded(real / theoretical * 100), peso_g=weight, teorico=theoretical)


def active_shift(actor, postazione, hygiene=False):
    require_permission(actor, "can_execute_production")
    shift = TurnoOperativo.objects.select_related("postazione__linea", "postazione__risorsa").filter(
        operatore=actor, postazione=postazione, fine__isnull=True).first()
    if not shift:
        raise ValidationError("Iniziare il proprio turno sulla postazione prima di operare.")
    if not shift.postazione.linea.attiva or not shift.postazione.risorsa.attiva:
        raise ValidationError("Linea o postazione disattivata.")
    if hygiene and not shift.igienizzazione_confermata_il:
        raise ValidationError("Confermare vasetti e capsule puliti e igienizzati per questo turno.")
    return shift


def open_session(actor, session):
    session = get_record(SessioneInvasettamento, session, "Sessione", lock=True)
    if session.chiusa_il:
        raise ValidationError("Sessione già chiusa.")
    shift = active_shift(actor, session.turno.postazione, hygiene=True)
    if shift.pk != session.turno_id:
        raise ValidationError("La sessione appartiene a un altro turno.")
    return session


def managed_guard(work):
    if work.tipo_lavorazione.fase_operativa and not in_scope(work.pk):
        raise ValidationError("Usare il servizio aziendale: questa operazione deve rispettare piano, turno e sessione.")


def zero_good_session(work):
    return bool(in_scope(work.pk) and work.tipo_lavorazione.fase_operativa == "INVASETTAMENTO"
        and RiepilogoInvasettamento.objects.filter(sessione__lavorazione=work, vasetti_buoni=0).exists())


def recipe_mass(recipe):
    total = Decimal(0)
    for row in recipe.righe.select_related("articolo"):
        if not row.articolo_id or row.articolo.unita_misura != "KG":
            raise ValidationError("Per la resa aziendale la ricetta deve indicare ingredienti specifici in KG.")
        total += row.quantita
    return quantity(total)


def require_control(kind, function, data_type):
    req = kind.controlli_richiesti.select_related("parametro_controllo").filter(funzione=function).first()
    if not req or not req.obbligatorio or not req.determina_conformita or req.parametro_controllo.tipo_dato != data_type:
        raise ValidationError(f"Configurare il controllo obbligatorio {function} per {kind.nome}.")
    return req


def principal(kind, schema=None):
    requirements = list(kind.requisiti_output.filter(tipo_output="PRINCIPALE"))
    if len(requirements) != 1 or not requirements[0].obbligatorio or requirements[0].multiplo:
        raise ValidationError("Configurare un solo output principale obbligatorio e non multiplo.")
    if schema and requirements[0].schema_lotto != schema:
        raise ValidationError(f"Configurare lo schema lotto {schema}.")
    return requirements[0]


class NumberingService:
    @staticmethod
    @transaction.atomic
    def next(*, articolo, famiglia, giorno=None):
        if famiglia not in {"RBQB", "TNK", "CRL", "FINALE"}:
            raise ValidationError("Famiglia di codice non valida.")
        article = get_record(Articolo, articolo, "Articolo", lock=True)
        day = CodiceProduzione._meta.get_field("giorno").clean(giorno or timezone.localdate(), None)
        number = (CodiceProduzione.objects.filter(articolo=article, famiglia=famiglia, giorno=day).aggregate(last=Max("numero"))["last"] or 0) + 1
        from magazzino.services.lots import LotGenerationService
        from produzione.models import UnitaLavorazione
        while True:
            if famiglia == "FINALE":
                code = f"{day:%y%m%d}" + (LotGenerationService.suffix(number - 1) if number > 1 else "")
            else:
                prefix = {"RBQB": "RbQb", "TNK": "TNK", "CRL": "CRL"}[famiglia]
                code = f"{prefix}{day:%y%m%d}{number:03d}"
            historical_cart = famiglia == "CRL" and UnitaLavorazione.objects.filter(lotto__articolo=article, codice=code).exists()
            if not historical_cart and not CodiceProduzione.objects.filter(articolo=article, codice=code).exists() and not Lotto.objects.filter(articolo=article, tipo="PRODUZIONE", codice_lotto=code).exists():
                break
            number += 1
        with azienda_write():
            CodiceProduzione.objects.create(articolo=article, famiglia=famiglia, giorno=day, numero=number, codice=code)
        return code
