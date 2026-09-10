"""Contratti dei servizi: ID persistenti e quantità esatte, senza float."""
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.core.validators import DecimalValidator


def quantity(value):
    if isinstance(value, (bool, float)):
        raise ValidationError("Usare Decimal, intero o stringa per la quantità; non float.")
    try:
        result = Decimal(value)
    except (InvalidOperation, ValueError, TypeError):
        raise ValidationError("Quantità non valida.") from None
    if not result.is_finite() or result <= 0:
        raise ValidationError("La quantità deve essere finita e strettamente positiva.")
    DecimalValidator(max_digits=18, decimal_places=6)(result)
    return result


def persisted_id(value, label):
    value = getattr(value, "pk", value)
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ValidationError(f"{label}: ID persistente obbligatorio.")
    return value


def location_code(value):
    if value is None:
        return ""
    if not isinstance(value, str):
        raise ValidationError("Scaffale e piano devono essere codici testuali.")
    value = value.strip().upper()
    if len(value) > 30:
        raise ValidationError("Scaffale e piano possono contenere al massimo 30 caratteri.")
    return value


@dataclass(frozen=True)
class Position:
    ubicazione_id: int
    scaffale: str = ""
    piano: str = ""

    def __post_init__(self):
        object.__setattr__(self, "ubicazione_id", persisted_id(self.ubicazione_id, "Ubicazione"))
        object.__setattr__(self, "scaffale", location_code(self.scaffale))
        object.__setattr__(self, "piano", location_code(self.piano))

    def stock_lookup(self):
        return {"ubicazione_id": self.ubicazione_id, "scaffale": self.scaffale, "piano": self.piano}


@dataclass(frozen=True)
class Allocation:
    posizione: Position
    quantita: Decimal

    def __post_init__(self):
        if not isinstance(self.posizione, Position):
            raise ValidationError("Allocazione senza posizione valida.")
        object.__setattr__(self, "quantita", quantity(self.quantita))
