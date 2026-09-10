from django.core.exceptions import ValidationError
from django.db.models import Sum


class CompletionValidator:
    """Riconciliazione di materiali, controlli qualità e percorso delle unità."""

    @staticmethod
    def validate(work):
        inputs = list(work.inputs.select_related("requisito_input", "riga_ricetta", "lotto__articolo"))
        outputs = list(work.outputs.select_related("requisito_output", "lotto__articolo"))
        input_ids = {r.requisito_input_id for r in inputs}
        output_ids = {r.requisito_output_id for r in outputs}
        errors = []
        from .azienda_common import zero_good_session
        zero_output_allowed = zero_good_session(work)
        from .recipe_inputs import recipe_coverage
        errors.extend(recipe_coverage(work, inputs))
        for req in work.tipo_lavorazione.requisiti_input.filter(obbligatorio=True):
            if req.pk not in input_ids:
                errors.append(f"Input obbligatorio mancante: {req.nome}.")
        if work.tipo_lavorazione.genera_lotto and not zero_output_allowed:
            if not outputs:
                errors.append("Una trasformazione deve avere almeno un output reale per essere completata.")
            for req in work.tipo_lavorazione.requisiti_output.filter(obbligatorio=True):
                if req.pk not in output_ids:
                    errors.append(f"Output obbligatorio mancante: {req.nome}.")
        elif outputs and not work.tipo_lavorazione.genera_lotto:
            errors.append("Un processo senza nuovo lotto non può avere output.")
        for records, kind, label in ((inputs, "CONSUMO", "Input"), (outputs, "PRODUZIONE", "Output")):
            for record in records:
                # full_clean verifica nuovamente requisito, articolo, origine
                # e cardinalità; non salva e non altera la registrazione storica.
                record.full_clean()
                movements = record.movimenti.all()
                if movements.exclude(tipo=kind, lotto_id=record.lotto_id).exists():
                    errors.append(f"{label} {record.pk}: movimenti incompatibili.")
                total = movements.filter(tipo=kind, lotto_id=record.lotto_id).aggregate(total=Sum("quantita"))["total"] or 0
                if total != record.quantita:
                    errors.append(f"{label} {record.pk}: quantità e movimenti non coincidono.")
        from qualita.services import QualityService
        errors.extend(QualityService.completion_errors(work))
        from .units import WorkUnitService
        errors.extend(WorkUnitService.completion_errors(work))
        if errors:
            raise ValidationError(errors)
