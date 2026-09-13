"""Controlli sul contenuto del file, indipendenti dal database di destinazione."""
from collections import defaultdict
from decimal import Decimal, InvalidOperation

from django.apps import apps
from django.core import serializers
from django.core.exceptions import ValidationError


def stock_differences(records):
    expected, actual = defaultdict(Decimal), defaultdict(Decimal)
    for record in records:
        fields = record["fields"]
        if record["model"] == "magazzino.movimento":
            quantity = Decimal(str(fields["quantita"]))
            for side, sign in (("origine", -1), ("destinazione", 1)):
                if fields.get("ubicazione_" + side) is not None:
                    key = (fields["lotto"], fields["ubicazione_" + side],
                           fields.get("scaffale_" + side, ""), fields.get("piano_" + side, ""))
                    expected[key] += quantity * sign
        elif record["model"] == "magazzino.giacenza":
            key = (fields["lotto"], fields["ubicazione"], fields.get("scaffale", ""), fields.get("piano", ""))
            actual[key] += Decimal(str(fields["quantita"]))
    return [(key, expected[key], actual[key]) for key in expected.keys() | actual.keys()
            if expected[key] != actual[key]]


def validate_records(records):
    indexes = defaultdict(dict)
    for record in records:
        model = apps.get_model(record["model"])
        pk = model._meta.pk.to_python(record["pk"])
        if pk is None or pk in indexes[model._meta.label_lower]:
            raise ValidationError(f"Identificativo mancante o duplicato: {model._meta.label} #{pk}.")
        indexes[model._meta.label_lower][pk] = record
        required = {f.name for f in [*model._meta.fields, *model._meta.local_many_to_many]
                    if not f.primary_key and not getattr(f, "generated", False)}
        if set(record["fields"]) != required:
            raise ValidationError(f"Campi mancanti o sconosciuti: {model._meta.label} #{pk}.")

    for record in records:
        model = apps.get_model(record["model"])
        for field in [*model._meta.fields, *model._meta.local_many_to_many]:
            if not field.is_relation or field.name not in record["fields"]:
                continue
            value = record["fields"][field.name]
            if value is None:
                if not field.null:
                    raise ValidationError(f"Riferimento obbligatorio: {record['model']}.{field.name}.")
                continue
            values = value if field.many_to_many else [value]
            if not isinstance(values, list):
                raise ValidationError(f"Relazione non valida: {record['model']}.{field.name}.")
            target = field.related_model
            target_field = target._meta.pk if field.many_to_many else field.target_field
            for value in values:
                key = target_field.to_python(value)
                if target_field.primary_key:
                    found = key in indexes[target._meta.label_lower]
                else:
                    found = any(target_field.to_python(r["fields"][target_field.name]) == key
                                for r in indexes[target._meta.label_lower].values())
                if not found:
                    raise ValidationError(f"Riferimento inesistente: {record['model']} #{record['pk']}, {field.name}={value}.")

    try:
        objects = list(serializers.deserialize("python", records))
        for item in objects:
            if item.object._meta.label_lower == "magazzino.giacenza":
                stock = item.object
                if not 0 <= stock.quantita_confezionata <= stock.quantita:
                    raise ValidationError(f"Ripartizione confezionamento non valida nella giacenza #{stock.pk}.")
            for field in item.object._meta.fields:
                if field.is_relation or field.primary_key or getattr(field, "generated", False):
                    continue
                value = getattr(item.object, field.attname)
                field.clean(value, item.object)
        differences = stock_differences(records)
        validate_packaging_balances(records)
    except (ValueError, TypeError, InvalidOperation, serializers.base.DeserializationError) as exc:
        raise ValidationError("Valore non valido nel backup: " + str(exc)) from exc
    if differences:
        raise ValidationError([
            f"Saldo incoerente: lotto {key[0]}, ubicazione {key[1]}, scaffale {key[2] or '-'}, "
            f"piano {key[3] or '-'}: movimenti {expected}, giacenza {actual}."
            for key, expected, actual in differences[:20]
        ])
    return objects


def validate_packaging_balances(records):
    lots = {str(r["pk"]): r["fields"] for r in records if r["model"] == "magazzino.lotto"}
    stocks = {str(r["pk"]): r["fields"] for r in records if r["model"] == "magazzino.giacenza"}
    expected, actual = defaultdict(Decimal), defaultdict(Decimal)

    def position(fields, suffix=""):
        return (str(fields["lotto"]), str(fields["ubicazione" + suffix]),
                fields["scaffale" + suffix], fields["piano" + suffix])

    for stock in stocks.values():
        actual[position(stock)] += Decimal(str(stock["quantita_confezionata"]))
    for record in records:
        fields = record["fields"]
        if record["model"] == "magazzino.movimento" and fields["componente"] == "CONFEZIONATO":
            for suffix, sign in (("_origine", -1), ("_destinazione", 1)):
                if fields["ubicazione" + suffix] is not None:
                    expected[position(fields, suffix)] += sign * Decimal(str(fields["quantita"]))
        elif record["model"] == "produzione.sessioneproduzionesemplificata" and fields["tipo"] == "CONFEZIONAMENTO" and fields["stato"] == "CHIUSA" and fields["confezionamento_giacenza"] is not None:
            stock = stocks[str(fields["confezionamento_giacenza"])]
            expected[position(stock)] += Decimal(str(fields["quantita_finale_kg"] or 0))
    for key in actual.keys() | expected.keys():
        if lots[key[0]]["confezionamento_verificato"] and actual[key] != expected[key]:
            raise ValidationError(f"Saldo confezionato incoerente: lotto {key[0]}, ubicazione {key[1]}, scaffale {key[2]}, piano {key[3]}.")
