from decimal import Decimal
from django.core.exceptions import ValidationError
from anagrafiche.models import Articolo, CategoriaArticolo
from produzione.models import (TipoLavorazione, RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione,
    RequisitoFaseUnitaTipoLavorazione, RisorsaProduttiva, LineaProduttiva, PostazioneLinea)
from qualita.models import ParametroControllo, ControlloRichiestoTipoLavorazione
from .locking import get_record
from .azienda_common import business_atomic


def ensure(model, lookup, values):
    existing = model.objects.filter(**lookup).first()
    if existing:
        for key, value in values.items():
            if getattr(existing, key) != value:
                raise ValidationError(f"Configurazione {model.__name__} già presente ma diversa, campo {key}: nessuna sovrascrittura.")
        return existing
    return model.objects.create(**lookup, **values)


@business_atomic
def configure_lines(*, categoria_output, articolo_vasetti, articolo_capsule, categoria_semilavorati=None):
    """Configurazione esplicita da management command, mai durante le migrazioni."""
    category = get_record(CategoriaArticolo, categoria_output, "Categoria output")
    semi_category = get_record(CategoriaArticolo, categoria_semilavorati, "Categoria semilavorati") if categoria_semilavorati is not None else category
    jars = get_record(Articolo, articolo_vasetti, "Vasetti")
    caps = get_record(Articolo, articolo_capsule, "Capsule")
    if jars.pk == caps.pk or any(a.unita_misura != "PZ" or not a.attivo for a in (jars, caps)):
        raise ValidationError("Indicare due articoli attivi distinti in PZ per vasetti e capsule.")
    kinds = {}
    for phase, name, generates in (("SEMILAVORATO", "Produzione semilavorati", True), ("ROBOQBO", "RoboQbo batch", True),
            ("TANK", "Formazione tank", True), ("INVASETTAMENTO", "Invasettamento", True),
            ("PASTORIZZAZIONE", "Seconda pastorizzazione", False), ("VUOTO", "Shock termico e vuoto", False)):
        kinds[phase] = ensure(TipoLavorazione, {"codice": "AZ_" + phase},
            {"nome": name, "fase_operativa": phase, "genera_lotto": generates, "attivo": True})
    outputs = {}
    for phase, schema, prefix in (("SEMILAVORATO", "LEGACY", "SL"), ("ROBOQBO", "RBQB", ""), ("TANK", "TNK", ""), ("INVASETTAMENTO", "FINALE", "")):
        outputs[phase] = ensure(RequisitoOutputTipoLavorazione, {"tipo_lavorazione": kinds[phase], "nome": "Prodotto"},
            {"categoria_articolo": semi_category if phase == "SEMILAVORATO" else category, "articolo": None, "tipo_output": "PRINCIPALE", "obbligatorio": True,
             "multiplo": False, "schema_lotto": schema, "prefisso_lotto": prefix})
    inputs = {}
    for key, target, origin, article in (("batch", "TANK", "ROBOQBO", None), ("tank", "INVASETTAMENTO", "TANK", None),
                                        ("vasetti", "INVASETTAMENTO", None, jars), ("capsule", "INVASETTAMENTO", None, caps)):
        inputs[key] = ensure(RequisitoInputTipoLavorazione, {"tipo_lavorazione": kinds[target], "nome": key.capitalize()},
            {"tipo_lavorazione_origine": kinds.get(origin), "articolo": article, "obbligatorio": True, "multiplo": True})
    controls = {}
    for phase, function, name, kind, bounds in (
        ("ROBOQBO", "BATCH", "Tracciato 82 °C × 60 secondi", "ESITO", {}),
        ("TANK", "BRIX", "°Brix", "DECIMALE", {"valore_minimo": Decimal(40), "valore_massimo": Decimal(45), "minimo_esclusivo": True, "massimo_esclusivo": True}),
        ("TANK", "PH", "pH", "DECIMALE", {"valore_massimo": Decimal("4.1")}),
        ("PASTORIZZAZIONE", "PAST", "71 °C × 4 minuti", "ESITO", {}),
        ("VUOTO", "VUOTO", "Shock termico e presenza vuoto", "ESITO", {}),
    ):
        parameter = ensure(ParametroControllo, {"codice": "AZ_" + function}, {"nome": name, "tipo_dato": kind, "attivo": True})
        values = {"parametro_controllo": parameter, "obbligatorio": True, "determina_conformita": True,
            "valore_minimo": None, "valore_massimo": None, "minimo_esclusivo": False, "massimo_esclusivo": False, **bounds}
        controls[function] = ensure(ControlloRichiestoTipoLavorazione, {"tipo_lavorazione": kinds[phase], "funzione": function}, values)
    for order, phase in ((1, "PASTORIZZAZIONE"), (2, "VUOTO")):
        ensure(RequisitoFaseUnitaTipoLavorazione, {"tipo_lavorazione": kinds["INVASETTAMENTO"], "tipo_fase": kinds[phase]},
            {"ordine": order, "obbligatorio": True})
    semi = ensure(LineaProduttiva, {"codice": "AZ_SEMILAVORATI"}, {"nome": "Semilavorati", "tipo_batch": kinds["SEMILAVORATO"], "attiva": True})
    jam = ensure(LineaProduttiva, {"codice": "AZ_CONFETTURE"}, {"nome": "Confetture", "tipo_batch": kinds["ROBOQBO"],
        "tipo_tank": kinds["TANK"], "tipo_invasettamento": kinds["INVASETTAMENTO"],
        "tipo_pastorizzazione": kinds["PASTORIZZAZIONE"], "tipo_vuoto": kinds["VUOTO"], "attiva": True})
    stations = {}
    for key, line, role, name in (("semilavorati", semi, "BATCH", "Semilavorati"), ("roboqbo", jam, "BATCH", "RoboQbo"), ("invasettamento", jam, "INVASETTAMENTO", "Invasettamento")):
        resource = ensure(RisorsaProduttiva, {"codice": "AZ_POST_" + key.upper()}, {"nome": name, "tipo": "MACCHINA", "attiva": True})
        stations[key] = ensure(PostazioneLinea, {"risorsa": resource}, {"linea": line, "ruolo": role})
    return dict(linee=[semi, jam], postazioni=stations, tipi=kinds, input=inputs, output=outputs, controlli=controls)
