from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Sum
from accounts.permissions import require_permission
from magazzino.models import Lotto
from magazzino.services.types import quantity, persisted_id
from produzione.models import (TipoLavorazione, Ricetta, CicloProduzione, Lavorazione,
    RisorsaProduttiva, RisorsaLavorazione, UnitaLavorazione, PartecipazioneUnitaLavorazione)
from produzione.models.unita import _unit_write
from .locking import get_record, lock_work, require_running


def lock_unit_works(unit, target=None):
    """Ordine globale tipi → ricette → cicli → lavori, anche fra cicli diversi."""
    snapshot_unit = get_record(UnitaLavorazione, unit, "Unità")
    ids = {snapshot_unit.lavorazione_origine_id}
    if target is not None:
        ids.add(persisted_id(target, "Lavorazione"))
    snapshot = {w.pk: (w.tipo_lavorazione_id, w.ricetta_id, w.ciclo_produzione_id) for w in Lavorazione.objects.filter(pk__in=ids)}
    if set(snapshot) != ids:
        raise ValidationError("Lavorazione inesistente.")
    if TipoLavorazione.objects.filter(pk__in={v[0] for v in snapshot.values()}).exclude(fase_operativa="").exists():
        from .azienda_common import business_mutex
        business_mutex()
    list(TipoLavorazione.objects.select_for_update().filter(pk__in={v[0] for v in snapshot.values()}).order_by("pk"))
    list(Ricetta.objects.select_for_update().filter(pk__in={v[1] for v in snapshot.values()} - {None}).order_by("pk"))
    cycles = {c.pk: c for c in CicloProduzione.objects.select_for_update().filter(pk__in={v[2] for v in snapshot.values()}).order_by("pk")}
    works = {w.pk: w for w in Lavorazione.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    for work in works.values():
        if (work.tipo_lavorazione_id, work.ricetta_id, work.ciclo_produzione_id) != snapshot[work.pk]:
            raise ValidationError("Pianificazione cambiata: riprovare.")
        work.ciclo_produzione = cycles[work.ciclo_produzione_id]
    return snapshot_unit, works


def route_errors(unit):
    participations = list(unit.partecipazioni.select_related("lavorazione"))
    completed = {p.lavorazione.tipo_lavorazione_id for p in participations if p.lavorazione.stato == "COMPLETATA"}
    errors = [f"Unità {unit.pk}: fase richiesta {r.tipo_fase} non completata." for r in unit.lavorazione_origine.tipo_lavorazione.fasi_unita_richieste.select_related("tipo_fase").filter(obbligatorio=True) if r.tipo_fase_id not in completed]
    if any(p.lavorazione.stato == "IN_CORSO" for p in participations):
        errors.append(f"Unità {unit.pk}: trattamento ancora in corso.")
    from qualita.models import ControlloQualita
    from qualita.nc_selectors import measurement_resolved
    failures = ControlloQualita.objects.filter(lavorazione_id__in=[p.lavorazione_id for p in participations], conforme=False,
                                              controllo_richiesto__determina_conformita=True)
    if any(not measurement_resolved(failure) for failure in failures):
        errors.append(f"Unità {unit.pk}: non conformità storica nei trattamenti, necessaria gestione NC.")
    return errors


class ResourceService:
    @staticmethod
    @transaction.atomic
    def assign(*, actor, lavorazione, risorsa_produttiva, note=""):
        require_permission(actor, "can_execute_production")
        work = lock_work(lavorazione)
        require_running(work)
        resource = get_record(RisorsaProduttiva, risorsa_produttiva, "Risorsa", lock=True)
        with _unit_write():
            return RisorsaLavorazione.objects.create(lavorazione=work, risorsa_produttiva=resource, note=note)


class WorkUnitService:
    @staticmethod
    @transaction.atomic
    def create(*, actor, lavorazione_origine, lotto, risorsa_produttiva=None, codice="", quantita=None, note=""):
        require_permission(actor, "can_manage_work_units")
        amount = quantity(quantita) if quantita is not None else None
        work = lock_work(lavorazione_origine)
        from .azienda_common import managed_guard
        managed_guard(work)
        require_running(work)
        resource = get_record(RisorsaProduttiva, risorsa_produttiva, "Risorsa", lock=True) if risorsa_produttiva is not None else None
        if resource and (not resource.attiva or resource.unita.filter(stato="ATTIVA").exists()):
            raise ValidationError("Risorsa inattiva o già associata a un'unità attiva.")
        lot = get_record(Lotto, lotto, "Lotto", lock=True)
        total = lot.unita_lavorazione.aggregate(total=Sum("quantita"))["total"] or 0
        output = work.outputs.filter(lotto=lot).first()
        if amount is not None and output and total + amount > output.quantita:
            raise ValidationError("Quantità delle unità superiore all'output del lotto.")
        with _unit_write():
            return UnitaLavorazione.objects.create(lavorazione_origine=work, lotto=lot, risorsa_produttiva=resource,
                                                   codice=codice, quantita=amount, note=note)

    @staticmethod
    @transaction.atomic
    def participate(*, actor, unita_lavorazione, lavorazione, note=""):
        require_permission(actor, "can_manage_work_units")
        snapshot, works = lock_unit_works(unita_lavorazione, lavorazione)
        origin = works[snapshot.lavorazione_origine_id]
        target = works[persisted_id(lavorazione, "Lavorazione")]
        from .azienda_common import managed_guard
        managed_guard(origin)
        managed_guard(target)
        require_running(origin)
        require_running(target)
        unit = get_record(UnitaLavorazione, snapshot.pk, "Unità", lock=True)
        if unit.partecipazioni.filter(lavorazione__stato="IN_CORSO").exists():
            raise ValidationError("L'unità partecipa già a un trattamento in corso.")
        route = origin.tipo_lavorazione.fasi_unita_richieste
        requirement = route.filter(tipo_fase_id=target.tipo_lavorazione_id).first()
        if route.exists() and requirement is None:
            raise ValidationError("Trattamento non previsto dal percorso configurato.")
        if requirement:
            completed = unit.partecipazioni.filter(lavorazione__stato="COMPLETATA").values_list("lavorazione__tipo_lavorazione_id", flat=True)
            if route.filter(obbligatorio=True, ordine__lt=requirement.ordine).exclude(tipo_fase_id__in=completed).exists():
                raise ValidationError("Completare prima le fasi obbligatorie precedenti.")
        with _unit_write():
            return PartecipazioneUnitaLavorazione.objects.create(unita_lavorazione=unit, lavorazione=target, note=note)

    @staticmethod
    @transaction.atomic
    def close(*, actor, unita_lavorazione):
        require_permission(actor, "can_manage_work_units")
        snapshot, works = lock_unit_works(unita_lavorazione)
        from .azienda_common import managed_guard
        managed_guard(works[snapshot.lavorazione_origine_id])
        require_running(works[snapshot.lavorazione_origine_id])
        # Il lock risorsa serializza la liberazione con la successiva assegnazione.
        if snapshot.risorsa_produttiva_id:
            get_record(RisorsaProduttiva, snapshot.risorsa_produttiva_id, "Risorsa", lock=True)
        unit = get_record(UnitaLavorazione, snapshot.pk, "Unità", lock=True)
        errors = route_errors(unit)
        if errors:
            raise ValidationError(errors)
        with _unit_write():
            unit.stato = "CHIUSA"
            unit.save()
        return unit

    @staticmethod
    def completion_errors(work):
        units = list(work.unita_generate.select_related("lavorazione_origine__tipo_lavorazione"))
        errors = []
        if work.tipo_lavorazione.fasi_unita_richieste.filter(obbligatorio=True).exists() and not units:
            errors.append("Il processo richiede almeno un'unità operativa.")
        for unit in units:
            errors.extend(route_errors(unit))
            if unit.stato != "CHIUSA":
                errors.append(f"Chiudere l'unità {unit.pk} prima della lavorazione origine.")
        for lot_id in {u.lotto_id for u in units}:
            output = work.outputs.filter(lotto_id=lot_id).first()
            from .azienda_common import zero_good_session
            if output is None and not zero_good_session(work):
                errors.append(f"Il lotto {lot_id} delle unità non ha un output consolidato.")
            elif output is not None and sum(u.quantita or 0 for u in units if u.lotto_id == lot_id) > output.quantita:
                errors.append(f"Le quantità delle unità superano l'output del lotto {lot_id}.")
        if work.tipo_lavorazione.richiesta_per_unita.exists() and not work.partecipazioni_unita.exists():
            errors.append("Una fase configurata per le unità richiede almeno una partecipazione.")
        return errors
