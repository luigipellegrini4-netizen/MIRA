"""Lock condivisi: tipi → ricette → cicli → lavorazioni → lotti → ubicazioni."""
from django.core.exceptions import ValidationError

from magazzino.services.types import persisted_id
from produzione.models import CicloProduzione, Lavorazione, Ricetta, TipoLavorazione


def get_record(model, value, label, *, lock=False):
    queryset = model.objects.select_for_update() if lock else model.objects
    try:
        return queryset.get(pk=persisted_id(value, label))
    except model.DoesNotExist:
        raise ValidationError(f"{label} inesistente.") from None


def lock_work(value, *, extra_types=(), extra_recipes=()):
    snapshot = get_record(Lavorazione, value, "Lavorazione")
    if snapshot.tipo_lavorazione.fase_operativa:
        from .azienda_common import business_mutex
        business_mutex()
    type_ids = {snapshot.tipo_lavorazione_id, *extra_types}
    recipe_ids = {r for r in (snapshot.ricetta_id, *extra_recipes) if r is not None}
    list(TipoLavorazione.objects.select_for_update().filter(pk__in=type_ids).order_by("pk"))
    list(Ricetta.objects.select_for_update().filter(pk__in=recipe_ids).order_by("pk"))
    cycle = get_record(CicloProduzione, snapshot.ciclo_produzione_id, "Ciclo", lock=True)
    work = get_record(Lavorazione, snapshot.pk, "Lavorazione", lock=True)
    if (work.tipo_lavorazione_id, work.ricetta_id, work.ciclo_produzione_id) != (snapshot.tipo_lavorazione_id, snapshot.ricetta_id, snapshot.ciclo_produzione_id):
        raise ValidationError("La pianificazione è cambiata durante l'operazione: riprovare.")
    work.ciclo_produzione = cycle
    return work


def lock_cycle_tree(value):
    cycle_id = persisted_id(value, "Ciclo")
    snapshot = list(Lavorazione.objects.filter(ciclo_produzione_id=cycle_id).values_list("tipo_lavorazione_id", "ricetta_id"))
    type_ids = {t for t, r in snapshot}
    if TipoLavorazione.objects.filter(pk__in=type_ids).exclude(fase_operativa="").exists():
        from .azienda_common import business_mutex
        business_mutex()
    recipe_ids = {r for t, r in snapshot if r is not None}
    list(TipoLavorazione.objects.select_for_update().filter(pk__in=type_ids).order_by("pk"))
    list(Ricetta.objects.select_for_update().filter(pk__in=recipe_ids).order_by("pk"))
    cycle = get_record(CicloProduzione, cycle_id, "Ciclo", lock=True)
    works = list(cycle.lavorazioni.select_for_update().order_by("pk"))
    if any(w.tipo_lavorazione_id not in type_ids or (w.ricetta_id is not None and w.ricetta_id not in recipe_ids) for w in works):
        raise ValidationError("La pianificazione del ciclo è cambiata: riprovare.")
    return cycle, works


def require_running(work):
    if work.stato != Lavorazione.Stato.IN_CORSO:
        raise ValidationError("La lavorazione deve essere IN_CORSO.")
    if work.ciclo_produzione.stato in {CicloProduzione.Stato.COMPLETATO, CicloProduzione.Stato.ANNULLATO}:
        raise ValidationError("Il ciclo è già chiuso.")


def ancestor_work_ids(lot_id):
    from magazzino.models import Lotto
    from produzione.models import InputLavorazione
    origin = get_record(Lotto, lot_id, "Lotto").lavorazione_origine_id
    seen, frontier = set(), {origin} if origin else set()
    while frontier:
        seen.update(frontier)
        origins = set(InputLavorazione.objects.filter(lavorazione_id__in=frontier).values_list("lotto__lavorazione_origine_id", flat=True))
        frontier = origins - seen - {None}
    return seen


def lock_work_for_input(value, lot_id):
    return lock_work_for_inputs(value, [lot_id])


def lock_work_for_inputs(value, lot_ids):
    """Blocca anche gli antenati: impedisce cicli genealogici concorrenti."""
    work_id = persisted_id(value, "Lavorazione")
    ancestors = set().union(*(ancestor_work_ids(lot_id) for lot_id in lot_ids))
    if work_id in ancestors:
        raise ValidationError("Il lotto creerebbe un ciclo nella genealogia produttiva.")
    ids = ancestors | {work_id}
    snapshot = {w.pk: (w.tipo_lavorazione_id, w.ricetta_id, w.ciclo_produzione_id) for w in Lavorazione.objects.filter(pk__in=ids)}
    if set(snapshot) != ids:
        raise ValidationError("Lavorazione inesistente.")
    type_ids = {v[0] for v in snapshot.values()}
    if TipoLavorazione.objects.filter(pk__in=type_ids).exclude(fase_operativa="").exists():
        from .azienda_common import business_mutex
        business_mutex()
    recipe_ids = {v[1] for v in snapshot.values()} - {None}
    cycle_ids = {v[2] for v in snapshot.values()}
    list(TipoLavorazione.objects.select_for_update().filter(pk__in=type_ids).order_by("pk"))
    list(Ricetta.objects.select_for_update().filter(pk__in=recipe_ids).order_by("pk"))
    cycles = {c.pk: c for c in CicloProduzione.objects.select_for_update().filter(pk__in=cycle_ids).order_by("pk")}
    works = {w.pk: w for w in Lavorazione.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if {w.pk: (w.tipo_lavorazione_id, w.ricetta_id, w.ciclo_produzione_id) for w in works.values()} != snapshot:
        raise ValidationError("La pianificazione è cambiata: riprovare.")
    current_ancestors = set().union(*(ancestor_work_ids(lot_id) for lot_id in lot_ids))
    if work_id in current_ancestors:
        raise ValidationError("Il lotto creerebbe un ciclo nella genealogia produttiva.")
    if not current_ancestors.issubset(ancestors):
        raise ValidationError("La genealogia è cambiata durante l'operazione: riprovare.")
    work = works[work_id]
    work.ciclo_produzione = cycles[work.ciclo_produzione_id]
    return work
