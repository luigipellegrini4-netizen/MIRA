"""Campi correggibili senza riscrivere movimenti, quantità o genealogia."""

from django.apps import apps


EDITABLE_FIELDS = {
    "anagrafiche.CategoriaArticolo": ("codice", "nome", "categoria_padre", "attiva", "note"),
    "anagrafiche.Articolo": ("codice", "descrizione", "categoria", "criterio_rotazione", "tracciabilita_lotto", "scorta_minima", "attivo", "note"),
    "anagrafiche.Fornitore": ("codice", "ragione_sociale", "partita_iva", "codice_fiscale", "indirizzo", "cap", "comune", "provincia", "nazione", "telefono", "email", "attivo", "note"),
    "anagrafiche.Ubicazione": ("codice", "nome", "attiva", "note"),
    "vendite.Cliente": ("codice", "ragione_sociale", "partita_iva", "indirizzo", "email", "telefono", "attivo"),
    "produzione.Ricetta": ("nome", "versione", "attiva", "note"),
    "produzione.RigaRicetta": ("categoria_articolo", "articolo", "quantita", "note"),
    "produzione.ConfigurazioneControlloSemplificato": ("nome", "ordine", "obbligatorio", "attivo"),
    "produzione.SessioneProduzioneSemplificata": ("note",),
    "produzione.PrelievoSessioneSemplificata": ("note",),
    "produzione.NonConformitaSessioneSemplificata": ("descrizione", "note"),
    "produzione.AzioneNCSessioneSemplificata": ("descrizione", "note"),
    "produzione.VerificaNCSessioneSemplificata": ("descrizione", "note"),
    "qualita.ParametroControllo": ("codice", "nome", "unita_misura", "attivo", "note"),
    "qualita.ControlloRichiestoTipoLavorazione": ("valore_minimo", "valore_massimo", "minimo_esclusivo", "massimo_esclusivo", "note"),
}

APPS = ("anagrafiche", "magazzino", "produzione", "qualita", "vendite", "interfaccia")
EXCLUDED = {"interfaccia.CorrezioneAmministrativa", "interfaccia.InvioOperativo"}


def correction_models():
    return tuple(sorted(
        (model for model in apps.get_models() if model._meta.app_label in APPS
         and model._meta.label not in EXCLUDED),
        key=lambda model: model._meta.label,
    ))


def correction_model(app_label, model_name):
    if app_label not in APPS:
        return None
    try:
        model = apps.get_model(app_label, model_name)
    except LookupError:
        return None
    return model if model in correction_models() else None
