"""Politica aziendale: nessun bypass operativo per AMMINISTRATORE."""
from django.core.exceptions import PermissionDenied

A = "AMMINISTRATORE"
RP = "RESPONSABILE_PRODUZIONE"
RM = "RESPONSABILE_MAGAZZINO"
RQ = "RESPONSABILE_QUALITA"
OP = "OPERATORE_PRODUZIONE"
M = "MAGAZZINIERE"
RV = "RESPONSABILE_VENDITE"
ROLES = (A, RP, RM, RQ, OP, M, RV)
OPERATIVE_ROLES = frozenset((RP, RM, RQ, OP, M))

# Consultazione estesa ai ruoli operativi; gestione limitata per anagrafica.
MODEL_MANAGERS = {
    "categoriaarticolo": {A, RP},
    "articolo": {A, RP, RM},
    "fornitore": {A, RM},
    "ubicazione": {A, RM},
}

# I permessi custom sono ancorati al ContentType auth.Group: non serve un
# modello artificiale, né un CustomUser. La namespace è quindi auth.
CAPABILITIES = {
    "can_manage_backups": ("Gestire backup, azzeramento e correzioni amministrative", {A}),
    "can_manage_process_configuration": ("Gestire configurazione produzione", {A, RP}),
    "can_manage_quality_configuration": ("Gestire parametri qualità", {A, RQ}),
    "can_manage_required_controls": ("Gestire controlli richiesti", {A, RP, RQ}),
    "can_receive_goods": ("Ricevere merce", {RM, M}),
    "can_transfer_stock": ("Trasferire stock", {RM, M}),
    "can_record_production_consumption": ("Registrare prelievi produttivi", {RP, RM, OP, M}),
    "can_count_inventory": ("Registrare conteggi", {RM, M}),
    "can_adjust_inventory": ("Applicare rettifica inventariale", {RM}),
    "can_plan_production": ("Pianificare produzione", {RP}),
    "can_plan_own_batches": ("Scegliere batch e piano di prelievo sulla propria postazione", {RP, OP}),
    "can_cancel_unstarted_work": ("Annullare lavorazione non iniziata", {RP}),
    "can_execute_production": ("Eseguire produzione", {RP, OP}),
    "can_manage_work_units": ("Gestire unità e risorse associate", {RP, OP}),
    "can_record_quality_control": ("Registrare controlli qualità", {RP, RQ, OP}),
    "can_open_nc": ("Aprire non conformità", set(OPERATIVE_ROLES) | {RV}),
    "can_manage_nc": ("Gestire non conformità", {RQ}),
    "can_quarantine_stock": ("Eseguire quarantena da NC", {RQ}),
    "can_reintegrate_stock": ("Eseguire reintegro da NC", {RQ}),
    "can_scrap_nc_stock": ("Eseguire scarto da NC", {RQ}),
    "can_verify_nc": ("Verificare non conformità", {RQ}),
    "can_close_nc": ("Chiudere non conformità", {RQ}),
    "can_view_genealogy": ("Consultare genealogia", set(OPERATIVE_ROLES) | {RV}),
    "can_manage_sales": ("Gestire clienti e vendite", {RV}),
}


def require_permission(actor, codename):
    """I servizi chiamano questo controllo prima di qualunque modifica."""
    if codename not in CAPABILITIES:
        raise ValueError(f"Permesso applicativo sconosciuto: {codename}")
    if not actor or not actor.is_authenticated or not actor.is_active:
        raise PermissionDenied("Utente non attivo o non autenticato.")
    if not actor.has_perm(f"auth.{codename}"):
        raise PermissionDenied(f"Permesso richiesto: {codename}")
