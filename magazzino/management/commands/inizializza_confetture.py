"""Caricamento iniziale esplicito: preserva accessi, anagrafiche, ricette e configurazioni."""
import json
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from uuid import uuid4
from django.apps import apps
from django.conf import settings
from django.contrib.auth import get_user_model
from django.core import serializers
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from django.db import connection, transaction
from django.utils import timezone
from anagrafiche.models import Articolo, CategoriaArticolo, Fornitore, Ubicazione
from magazzino.models import Lotto, Giacenza, Movimento, RicevimentoLotto
from magazzino.services import Allocation, Position, ReceivingService
from produzione.models import Ricetta, TipoLavorazione
from produzione.services import RecipeService

TAG = "AVVIO CONFETTURE — DATI FITTIZI DI PROVA"
FRUITS = (("FRAGOLA", "Fragole"), ("ALBICOCCA", "Albicocche"), ("PESCA", "Pesche"), ("PRUGNA", "Prugne"), ("CILIEGIA", "Ciliegie"))
INVENTORY = (Movimento, Giacenza, RicevimentoLotto, Lotto)


OPERATIONAL_LABELS = (
    "interfaccia.CorrezioneAmministrativa",
    "produzione.CicloProduzione", "produzione.Lavorazione", "produzione.InputLavorazione",
    "produzione.OutputLavorazione", "produzione.RisorsaLavorazione", "produzione.UnitaLavorazione",
    "produzione.PartecipazioneUnitaLavorazione", "produzione.TurnoOperativo", "produzione.PianoProduzione",
    "produzione.BatchPiano", "produzione.RevisionePrelievo", "produzione.RigaPianoPrelievo",
    "produzione.PrelievoDaPiano", "produzione.TankAziendale", "produzione.SessioneInvasettamento",
    "produzione.CarrelloSessione", "produzione.TrattamentoCarrello", "produzione.RiepilogoInvasettamento",
    "produzione.CodiceProduzione", "qualita.ControlloQualita", "qualita.NonConformita",
    "produzione.SessioneProduzioneSemplificata", "produzione.PrelievoSessioneSemplificata",
    "produzione.ControlloSessioneSemplificata", "produzione.RiepilogoSessioneSemplificata",
    "produzione.NonConformitaSessioneSemplificata",
    "qualita.AzioneNonConformita", "qualita.VerificaNonConformita",
)


def reset_models(include_operations=False):
    remaining = set(INVENTORY)
    if include_operations:
        remaining.update(apps.get_model(label) for label in OPERATIONAL_LABELS)
    ordered = []
    while remaining:
        # Una relazione verso lo stesso modello non cambia l'ordine tra le
        # tabelle: tutte le righe vengono eliminate dalla stessa DELETE.
        parents = {field.related_model for model in remaining for field in model._meta.fields
                   if field.is_relation and field.related_model in remaining
                   and field.related_model is not model}
        leaves = sorted(remaining - parents, key=lambda model: model._meta.label)
        if not leaves:
            raise ValidationError("Dipendenze circolari: reset non eseguibile senza violare i vincoli.")
        ordered.extend(leaves)
        remaining.difference_update(leaves)
    return tuple(ordered)


def catalog():
    rows = []
    for code, name in FRUITS:
        rows.extend([
            ("MP_" + code, name + (" surgelate pulite" if code == "FRAGOLA" else " surgelate denocciolate"), "MP", "KG", "100"),
            ("SL_" + code, "Semilavorato di " + name.lower(), "SL", "KG", "50"),
            ("CF_" + code, "Confettura di " + name.lower(), "CF", "KG", "20"),
        ])
    rows.extend([
        ("MP_ZUCCHERO", "Zucchero bianco", "MP", "KG", "150"),
        ("MP_PECTINA", "Pectina per confetture", "MP", "KG", "5"),
        ("MP_ASCORBICO", "Acido ascorbico", "MP", "KG", "2"),
        ("MP_PUREA_MELA", "Purea di mela", "MP", "KG", "60"),
        ("MOCA_VASETTO", "Vasetto vetro 314 ml, imboccatura TO 63", "MOCA", "PZ", "1000"),
        ("MOCA_CAPSULA", "Capsula twist-off TO 63", "MOCA", "PZ", "1000"),
    ])
    return rows


def formulas():
    result = {}
    for code, _ in FRUITS:
        result["SL_" + code] = [("MP_" + code, "10"), ("MP_ASCORBICO", "0.050")]
        result["CF_" + code] = [("SL_" + code, "10"), ("MP_PECTINA", "0.150"),
            ("MP_ASCORBICO", "0.020"), ("MP_PUREA_MELA", "2"), ("MP_ZUCCHERO", "6")]
    return result


def dependencies(models=INVENTORY):
    """Nessuna cascata verso produzione, qualità, configurazioni o accessi."""
    blocked = []
    inventory = set(models)
    for model in apps.get_models():
        if model in inventory:
            continue
        for field in model._meta.fields:
            if field.is_relation and field.related_model in inventory:
                count = model.objects.filter(**{field.name + "__isnull": False}).count()
                if count:
                    blocked.append(f"{model._meta.label}.{field.name}: {count} collegamenti")
    return blocked


def ensure(model, lookup, values):
    obj = model.objects.filter(**lookup).first()
    if obj:
        if any(getattr(obj, k) != v for k, v in values.items()):
            raise ValidationError(f"Configurazione esistente diversa: {model._meta.label} {lookup}. Nessuna sovrascrittura.")
        return obj
    return model.objects.create(**lookup, **values)


def actor_for(permission, username=None):
    users = get_user_model().objects.filter(is_active=True).order_by("pk")
    if username:
        users = users.filter(username=username)
    actor = next((u for u in users if u.has_perm("auth." + permission)), None)
    if actor is None:
        raise ValidationError(f"Manca un utente attivo con permesso {permission}. Specificare un utente esistente.")
    return actor


def existing_configuration():
    categories, packaging = {}, {}
    for key, code in (("SL", "AZ_SEMILAVORATO"), ("CF", "AZ_ROBOQBO")):
        kind = TipoLavorazione.objects.filter(codice=code).first()
        if kind:
            outputs = list(kind.requisiti_output.filter(tipo_output="PRINCIPALE"))
            if len(outputs) != 1 or not outputs[0].categoria_articolo_id:
                raise ValidationError("Il processo esistente deve accettare una categoria per ospitare cinque prodotti: " + code)
            categories[key] = outputs[0].categoria_articolo
    kind = TipoLavorazione.objects.filter(codice="AZ_INVASETTAMENTO").first()
    if kind:
        for key, name in (("MOCA_VASETTO", "vasetti"), ("MOCA_CAPSULA", "capsule")):
            requirements = list(kind.requisiti_input.filter(nome__iexact=name, articolo__attivo=True, articolo__unita_misura="PZ"))
            if len(requirements) != 1:
                raise ValidationError("Impossibile individuare l'articolo MOCA della linea esistente: " + name)
            packaging[key] = requirements[0].articolo
        if packaging["MOCA_VASETTO"].pk == packaging["MOCA_CAPSULA"].pk:
            raise ValidationError("Vasetti e capsule devono essere distinti.")
    return categories, packaging


@transaction.atomic
def initialize(*, recipe_actor, stock_actor, backup_dir, include_operations=False):
    if connection.vendor != "mysql":
        raise ValidationError("Il reset è previsto solo sul MySQL configurato per MIRA.")
    from produzione.services.azienda_common import business_mutex
    business_mutex()
    models = reset_models(include_operations)
    blocked = dependencies(models)
    if blocked:
        raise ValidationError(["Reset fermato: collegamenti a dati fuori dal perimetro selezionato.", *blocked])
    if not recipe_actor.has_perm("auth.can_manage_process_configuration") or not stock_actor.has_perm("auth.can_receive_goods"):
        raise ValidationError("Utenti scelti privi dei permessi richiesti.")
    configured_categories, configured_packaging = existing_configuration()
    records = []
    identifiers = {}
    # Esclude le colonne generate: il backup è un fixture Django con PK originali.
    for model in reversed(models):
        fields = [f.name for f in model._meta.fields if not getattr(f, "generated", False)]
        snapshot = json.loads(serializers.serialize("json", model.objects.select_for_update().order_by("pk"), fields=fields))
        records.extend(snapshot)
        identifiers[model] = [r["pk"] for r in snapshot]
    backup_dir = Path(backup_dir)
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / (("operativi_" if include_operations else "magazzino_") + timezone.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid4().hex[:8] + ".json")
    with backup.open("x", encoding="utf-8") as handle:
        json.dump(records, handle, ensure_ascii=False, indent=2)
    # Manutenzione esplicitamente autorizzata; non disabilita FK né azzera sequenze.
    # Le barriere ORM restano attive per tutte le normali operazioni del gestionale.
    with connection.cursor() as cursor:
        for model in models:
            ids = identifiers[model]
            for start in range(0, len(ids), 500):
                batch = ids[start:start + 500]
                cursor.execute("DELETE FROM " + connection.ops.quote_name(model._meta.db_table) + " WHERE id IN (" + ",".join(["%s"] * len(batch)) + ")", batch)
    if any(model.objects.exists() for model in models):
        raise ValidationError("Nuovi dati inseriti durante il reset: operazione annullata. Fermare tutte le istanze di MIRA.")
    categories = {code: configured_categories[code] if code in configured_categories else ensure(CategoriaArticolo, {"codice": "AVV_" + code}, {"nome": name, "attiva": True, "note": TAG})
        for code, name in (("MP", "Materie prime confetture"), ("SL", "Semilavorati di frutta"), ("CF", "Confetture"), ("MOCA", "Vasetti e capsule"))}
    locations = {code: ensure(Ubicazione, {"codice": "AVV_" + code}, {"nome": name, "attiva": True, "note": TAG})
        for code, name in (("GELO", "Cella frutta surgelata"), ("SECCO", "Magazzino ingredienti"),
            ("MOCA", "Magazzino vasetti e capsule"), ("PRODOTTI", "Giacenze iniziali semilavorati e confetture"))}
    supplier = ensure(Fornitore, {"codice": "AVV_FORNITORE"}, {"ragione_sociale": "Fornitore fittizio per carichi iniziali di prova", "note": TAG, "attivo": True})
    articles = {}
    for code, description, category, unit, _ in catalog():
        if code in configured_packaging:
            articles[code] = configured_packaging[code]
            continue
        articles[code] = ensure(Articolo, {"codice": "AVV_" + code}, {"descrizione": description, "categoria": categories[category],
            "unita_misura": unit, "criterio_rotazione": "FIFO" if unit == "PZ" else "FEFO", "attivo": True,
            "tracciabilita_lotto": True, "note": TAG})
    for code, ingredients in formulas().items():
        recipe = Ricetta.objects.filter(articolo=articles[code], versione="PROVA-1").first()
        if recipe:
            expected = [(articles[c].pk, Decimal(q)) for c, q in ingredients]
            if recipe.note != TAG or not recipe.attiva or list(recipe.righe.order_by("pk").values_list("articolo_id", "quantita")) != expected:
                raise ValidationError("Ricetta di prova già presente ma diversa: " + code)
        else:
            recipe = RecipeService.create(actor=recipe_actor, articolo=articles[code], nome=articles[code].descrizione,
                versione="PROVA-1", note=TAG)
            for ingredient, amount in ingredients:
                RecipeService.add_line(actor=recipe_actor, ricetta=recipe, articolo=articles[ingredient], quantita=amount)
    day = timezone.localdate()
    for code, _, category, unit, amount in catalog():
        location = locations["MOCA" if unit == "PZ" else "PRODOTTI" if category in {"SL", "CF"} else "GELO" if code in {"MP_" + c for c, _ in FRUITS} else "SECCO"]
        for i in range(1, 4):
            ReceivingService.receive(actor=stock_actor, articolo=articles[code], fornitore=supplier,
                codice_lotto=f"AVV-{code}-{day:%y%m%d}-{i:02d}", quantita_ricevuta=amount,
                data_scadenza=None if unit == "PZ" else day + timedelta(days=180 + 60 * i),
                data_ricevimento=timezone.now() - timedelta(days=4-i), numero_ddt=f"AVV-PROVA-{i:02d}",
                note=TAG + ". Giacenza iniziale; nessuna produzione o genealogia produttiva simulata.",
                destinazioni=[Allocation(Position(location.pk, "A", str(i)), amount)])
    return backup


class Command(BaseCommand):
    help = "Reset magazzino, opzionalmente produzione e qualità operative; carica 21 articoli, 10 ricette e 63 lotti. Conserva accessi e configurazioni."

    def add_arguments(self, parser):
        parser.add_argument("--includi-produzione-qualita", action="store_true", help="Elimina anche registrazioni operative, turni e codici produttivi; conserva ricette e configurazioni.")
        parser.add_argument("--apply", action="store_true", help="Esegue reset e caricamento; senza questa opzione mostra solo l'anteprima.")
        parser.add_argument("--database-atteso", help="Obbligatorio con --apply; deve coincidere con il database configurato.")
        parser.add_argument("--utente-ricette")
        parser.add_argument("--utente-carichi")

    def handle(self, *args, **options):
        name = str(connection.settings_dict["NAME"])
        self.stdout.write("Database configurato: " + name)
        models = reset_models(options["includi_produzione_qualita"])
        for model in models:
            self.stdout.write(f"{model._meta.label}: {model.objects.count()} record da eliminare")
        blocked = dependencies(models)
        self.stdout.write("Saranno caricati 21 articoli, 5 ricette semilavorati, 5 ricette confetture e 63 lotti (3 per articolo).")
        self.stdout.write("Utenti, password, ruoli, anagrafiche, ricette e configurazioni delle linee e dei controlli saranno conservati.")
        try:
            recipe_actor = actor_for("can_manage_process_configuration", options["utente_ricette"])
            stock_actor = actor_for("can_receive_goods", options["utente_carichi"])
            _, packaging = existing_configuration()
            for key, article in packaging.items():
                self.stdout.write(f"Riutilizzo MOCA già configurato, {key}: {article}")
            self.stdout.write(f"Utenze di registrazione: ricette={recipe_actor.username}, carichi={stock_actor.username}")
            if blocked:
                raise ValidationError(["Collegamenti esterni al perimetro selezionato: reset non eseguibile.", *blocked])
            if not options["apply"]:
                self.stdout.write("Solo anteprima: nessun dato modificato. Chiudere MIRA prima dell'esecuzione effettiva.")
                return
            if options["database_atteso"] != name:
                raise ValidationError("Specificare --database-atteso con il nome mostrato nell'anteprima.")
            backup = initialize(recipe_actor=recipe_actor, stock_actor=stock_actor, backup_dir=settings.BASE_DIR / "backups", include_operations=options["includi_produzione_qualita"])
        except ValidationError as exc:
            raise CommandError("\n".join(exc.messages)) from exc
        self.stdout.write(self.style.SUCCESS("Reset e caricamento completati. Backup dei dati precedenti: " + str(backup)))
