from django.core.exceptions import ValidationError
from django.db import transaction
from accounts.permissions import require_permission
from produzione.services.locking import lock_work, require_running, get_record
from .models import ControlloQualita, ControlloRichiestoTipoLavorazione, _recording
from .rules import typed_value, evaluate


class QualityService:
    @staticmethod
    @transaction.atomic
    def record(*, actor, lavorazione, controllo_richiesto, valore, conforme=None, note=""):
        require_permission(actor, "can_record_quality_control")
        work = lock_work(lavorazione)
        require_running(work)
        req = get_record(ControlloRichiestoTipoLavorazione, controllo_richiesto, "Controllo richiesto")
        if req.tipo_lavorazione_id != work.tipo_lavorazione_id:
            raise ValidationError("Controllo di un altro tipo di lavorazione.")
        field, value = typed_value(req.parametro_controllo.tipo_dato, valore)
        result = ControlloQualita(lavorazione=work, controllo_richiesto=req, eseguito_da=actor,
                                 conforme=evaluate(req, value, conforme), note=note, **{field: value})
        result.esito = value if req.parametro_controllo.tipo_dato == "ESITO" else ("C" if result.conforme else "NC")
        token = _recording.set(True)
        try:
            result.save()
        finally:
            _recording.reset(token)
        if work.tipo_lavorazione.fase_operativa == "TANK":
            from produzione.services.azienda_execution import TankService
            TankService.release_if_ready(actor=actor, lavorazione=work)
        return result

    @staticmethod
    def completion_errors(work):
        measurements = list(work.controlli_qualita.select_related("controllo_richiesto__parametro_controllo"))
        present = {m.controllo_richiesto_id for m in measurements}
        errors = [f"Controllo obbligatorio mancante: {r.parametro_controllo}." for r in work.tipo_lavorazione.controlli_richiesti.select_related("parametro_controllo").filter(obbligatorio=True) if r.pk not in present]
        for measurement in measurements:
            measurement.full_clean()
            from .nc_selectors import measurement_resolved
            if measurement.controllo_richiesto.determina_conformita and not measurement.conforme and not measurement_resolved(measurement):
                errors.append(f"Controllo {measurement.pk} non conforme: necessaria gestione NC prima della chiusura.")
        return errors


from .nc_services import NonConformityService
