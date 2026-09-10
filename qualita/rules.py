"""Conversione rigorosa e valutazione indipendente dal database."""
from decimal import Decimal, InvalidOperation
from django.core.exceptions import ValidationError


def typed_value(kind, value):
    if kind == "ESITO":
        if value not in ("C", "NC", "NA"):
            raise ValidationError("Selezionare C, NC oppure NA.")
        return "valore_testo", value
    if kind == "BOOLEANO":
        if type(value) is not bool:
            raise ValidationError("Inserire True o False.")
        return "valore_booleano", value
    if kind == "TESTO":
        if not isinstance(value, str) or not value.strip():
            raise ValidationError("Inserire un testo non vuoto.")
        return "valore_testo", value.strip()
    if isinstance(value, (bool, float)) or not isinstance(value, (str, int, Decimal)):
        raise ValidationError("Usare un numero intero, Decimal o una stringa numerica.")
    try:
        number = Decimal(value)
    except (InvalidOperation, ValueError):
        raise ValidationError("Numero non valido.") from None
    if not number.is_finite():
        raise ValidationError("Il numero deve essere finito.")
    if kind == "INTERO":
        if number != number.to_integral_value() or not -(2**63) <= number < 2**63:
            raise ValidationError("Intero fuori intervallo o frazionario.")
        return "valore_intero", int(number)
    if kind == "DECIMALE":
        from django.core.validators import DecimalValidator
        DecimalValidator(18, 6)(number)
        return "valore_decimale", number
    raise ValidationError("Tipo dato sconosciuto.")


def evaluate(requirement, value, assessment=None):
    kind = requirement.parametro_controllo.tipo_dato
    if kind == "ESITO":
        typed_value(kind, value)
        if assessment is not None:
            raise ValidationError("La conformità dell'esito viene calcolata dal servizio.")
        return value == "C"
    if kind == "TESTO":
        if type(assessment) is not bool:
            raise ValidationError("Per il testo indicare esplicitamente conforme=True/False.")
        return assessment
    if assessment is not None:
        raise ValidationError("La conformità numerica e booleana viene calcolata dal servizio.")
    if kind == "BOOLEANO":
        expected = requirement.valore_booleano_atteso
        return expected is None or value == expected
    lower, upper = requirement.valore_minimo, requirement.valore_massimo
    return ((lower is None or (value > lower if getattr(requirement, "minimo_esclusivo", False) else value >= lower))
            and (upper is None or (value < upper if getattr(requirement, "massimo_esclusivo", False) else value <= upper)))
