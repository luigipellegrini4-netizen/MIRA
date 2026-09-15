from decimal import Decimal
import json

from django.core.exceptions import ValidationError
from django.db import transaction
from django.core.serializers.json import DjangoJSONEncoder

from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.services import MovementService, Position
from magazzino.services.movements import lock_locations
from vendite.models import RettificaRigaVendita, RigaVendita, Vendita

from accounts.permissions import require_permission
from interfaccia.models import CorrezioneAmministrativa
from interfaccia.correction_catalog import EDITABLE_FIELDS
from produzione.models import AssociazioneTankBatch, ControlloSessioneSemplificata, SessioneProduzioneSemplificata


FIELDS_BY_TYPE = {
    "BATCH": ("inizio", "fine", "esito_tracciato_termico", "note"),
    "TANK": ("gradi_brix", "ph", "note"),
    "SEMILAVORATO": ("esito_pastorizzazione", "esito_shock_vuoto", "note"),
    "CARRELLO": ("esito_pastorizzazione", "esito_shock_vuoto", "note"),
}


def _snapshot(control, batch_ids):
    result = {}
    for name in FIELDS_BY_TYPE[control.tipo]:
        value = getattr(control, name)
        result[name] = value.isoformat() if hasattr(value, "isoformat") else str(value) if isinstance(value, Decimal) else value
    result["batch_ids"] = sorted(batch_ids)
    result["esito"] = control.esito
    return result


class AdministrativeCorrectionService:
    @staticmethod
    @transaction.atomic
    def correct_catalog_record(*, actor, model, record_id, motivazione, annotazione="", **values):
        require_permission(actor, "can_manage_backups")
        reason = (motivazione or "").strip()
        if not reason:
            raise ValidationError("La motivazione è obbligatoria.")
        allowed = EDITABLE_FIELDS.get(model._meta.label, ())
        if set(values) - set(allowed):
            raise ValidationError("Campi non correggibili da questa scheda.")
        current = model.objects.select_for_update().get(pk=record_id)
        before = {
            name: getattr(current, f"{name}_id") if model._meta.get_field(name).is_relation
            else getattr(current, name)
            for name in allowed
        }
        before = json.loads(json.dumps(before, cls=DjangoJSONEncoder))
        if allowed:
            for name, value in values.items():
                setattr(current, name, value)
            current.full_clean()
            after = {
                name: getattr(current, f"{name}_id") if model._meta.get_field(name).is_relation
                else getattr(current, name)
                for name in allowed
            }
            after = json.loads(json.dumps(after, cls=DjangoJSONEncoder))
            if before == after:
                raise ValidationError("Non è stata indicata alcuna modifica.")
            current.save(update_fields=tuple(values))
        else:
            note = (annotazione or "").strip()
            if not note:
                raise ValidationError("Descrivere la registrazione errata e la correzione richiesta.")
            before = {"record": str(current)}
            after = {"annotazione": note}
        CorrezioneAmministrativa.objects.create(
            modello=model._meta.label, record_id=str(current.pk),
            valori_precedenti=before, valori_nuovi=after,
            motivazione=reason, eseguita_da=actor,
        )
        return current

    @staticmethod
    @transaction.atomic
    def correct_stock(*, actor, giacenza, verso, quantita, motivazione, componente=""):
        require_permission(actor, "can_manage_backups")
        reason = (motivazione or "").strip()
        if not reason:
            raise ValidationError("La motivazione è obbligatoria.")
        if verso not in {"AUMENTO", "DIMINUZIONE"}:
            raise ValidationError("Scegliere aumento o diminuzione.")
        lot_id = Giacenza.objects.only("lotto_id").get(pk=giacenza.pk).lotto_id
        lot = Lotto.objects.select_for_update().get(pk=lot_id)
        source = Giacenza.objects.select_related("ubicazione").get(pk=giacenza.pk)
        position = Position(source.ubicazione_id, source.scaffale, source.piano)
        lock_locations((position,))
        source = Giacenza.objects.select_for_update().get(pk=giacenza.pk)
        before = {
            "lotto_id": source.lotto_id, "ubicazione_id": source.ubicazione_id,
            "scaffale": source.scaffale, "piano": source.piano,
            "quantita": str(source.quantita),
            "quantita_confezionata": str(source.quantita_confezionata),
        }
        movement = MovementService.register(
            actor=actor, lotto=lot, tipo=Movimento.Tipo.RETTIFICA, quantita=quantita,
            origine=position if verso == "DIMINUZIONE" else None,
            destinazione=position if verso == "AUMENTO" else None,
            note=f"Correzione amministrativa: {reason}", componente=componente,
            correzione_amministrativa=True,
        )
        source.refresh_from_db()
        after = {
            **before, "quantita": str(source.quantita),
            "quantita_confezionata": str(source.quantita_confezionata),
            "movimento_rettifica_id": movement.pk,
        }
        CorrezioneAmministrativa.objects.create(
            modello="magazzino.Giacenza", record_id=source.pk,
            valori_precedenti=before, valori_nuovi=after,
            motivazione=reason, eseguita_da=actor,
        )
        return movement

    @staticmethod
    @transaction.atomic
    def correct_sale(*, actor, vendita, motivazione, **values):
        require_permission(actor, "can_manage_backups")
        reason = (motivazione or "").strip()
        if not reason:
            raise ValidationError("La motivazione è obbligatoria.")
        allowed = {"numero_documento", "data_documento", "cliente", "note"}
        if set(values) - allowed:
            raise ValidationError("Si possono correggere soltanto i dati del documento di vendita.")
        current = Vendita.objects.select_for_update().get(pk=vendita.pk)
        before = {
            "numero_documento": current.numero_documento,
            "data_documento": current.data_documento.isoformat(),
            "cliente_id": current.cliente_id, "note": current.note,
        }
        for name, value in values.items():
            setattr(current, name, value)
        current.full_clean()
        after = {
            "numero_documento": current.numero_documento,
            "data_documento": current.data_documento.isoformat(),
            "cliente_id": current.cliente_id, "note": current.note,
        }
        if before == after:
            raise ValidationError("Non è stata indicata alcuna modifica.")
        current.save(update_fields=tuple(values))
        CorrezioneAmministrativa.objects.create(
            modello="vendite.Vendita", record_id=current.pk,
            valori_precedenti=before, valori_nuovi=after,
            motivazione=reason, eseguita_da=actor,
        )
        return current

    @staticmethod
    @transaction.atomic
    def correct_sales_line(*, actor, riga, nuova_quantita, giacenza, motivazione):
        require_permission(actor, "can_manage_backups")
        reason = (motivazione or "").strip()
        if not reason:
            raise ValidationError("La motivazione è obbligatoria.")
        line = RigaVendita.objects.select_for_update().select_related("movimento__lotto", "vendita").get(pk=riga.pk)
        current_quantity = line.quantita_effettiva
        desired = Decimal(str(nuova_quantita))
        difference = desired - current_quantity
        if desired < 0 or difference == 0:
            raise ValidationError("Indicare una nuova quantità diversa e non negativa.")
        stock = Giacenza.objects.select_related("lotto", "ubicazione").get(pk=giacenza.pk)
        if stock.lotto_id != line.movimento.lotto_id:
            raise ValidationError("La posizione selezionata deve appartenere al lotto venduto.")
        position = Position(stock.ubicazione_id, stock.scaffale, stock.piano)
        movement = MovementService.register(
            actor=actor, lotto=stock.lotto,
            tipo=Movimento.Tipo.VENDITA if difference > 0 else Movimento.Tipo.RETTIFICA,
            quantita=abs(difference),
            origine=position if difference > 0 else None,
            destinazione=position if difference < 0 else None,
            componente=line.movimento.componente,
            note=f"Correzione riga vendita {line.vendita.numero_documento} #{line.pk}: {reason}",
            correzione_amministrativa=True,
        )
        RettificaRigaVendita.objects.create(
            riga=line, movimento=movement, differenza=difference,
            motivazione=reason, eseguita_da=actor,
        )
        CorrezioneAmministrativa.objects.create(
            modello="vendite.RigaVendita", record_id=line.pk,
            valori_precedenti={
                "lotto_id": line.movimento.lotto_id, "quantita_effettiva": str(current_quantity),
                "componente": line.movimento.componente,
            },
            valori_nuovi={
                "lotto_id": line.movimento.lotto_id, "quantita_effettiva": str(desired),
                "componente": line.movimento.componente, "movimento_correzione_id": movement.pk,
            },
            motivazione=reason, eseguita_da=actor,
        )
        return line

    @staticmethod
    @transaction.atomic
    def correct_control(*, actor, controllo, motivazione, batch_ids=None, **values):
        require_permission(actor, "can_manage_backups")
        reason = (motivazione or "").strip()
        if not reason:
            raise ValidationError("La motivazione è obbligatoria.")
        session_id = ControlloSessioneSemplificata.objects.only("sessione_id").get(pk=controllo.pk).sessione_id
        SessioneProduzioneSemplificata.objects.select_for_update().get(pk=session_id)
        current = ControlloSessioneSemplificata.objects.select_for_update().get(pk=controllo.pk)
        allowed = FIELDS_BY_TYPE[current.tipo]
        if set(values) - set(allowed):
            raise ValidationError("La correzione contiene campi non previsti per questo controllo.")
        associations = list(AssociazioneTankBatch.objects.select_for_update().filter(
            tank=current,
        ).order_by("pk"))
        previous_ids = {row.batch_id for row in associations}
        if current.tipo == "TANK":
            desired_ids = previous_ids if batch_ids is None else {int(pk) for pk in batch_ids}
            if not desired_ids:
                raise ValidationError("Associare almeno un batch al tank.")
            batches = list(ControlloSessioneSemplificata.objects.select_for_update().filter(
                pk__in=desired_ids, sessione_id=session_id, tipo="BATCH",
            ))
            if len(batches) != len(desired_ids):
                raise ValidationError("I batch associati devono appartenere alla stessa produzione RoboQbo.")
            if AssociazioneTankBatch.objects.filter(batch_id__in=desired_ids).exclude(tank=current).exists():
                raise ValidationError("Un batch selezionato appartiene già a un altro tank.")
        else:
            if batch_ids is not None:
                raise ValidationError("Solo i tank possono associare batch.")
            desired_ids = previous_ids
        before = _snapshot(current, previous_ids)
        for name, value in values.items():
            setattr(current, name, value)
        current.full_clean()
        if current.sessione.stato == "CHIUSA" and not current.completo:
            raise ValidationError("Un controllo di una produzione chiusa deve restare completo.")
        after = _snapshot(current, desired_ids)
        if before == after:
            raise ValidationError("Non è stata indicata alcuna modifica.")
        if values:
            current.save(update_fields=tuple(values))
        for row in associations:
            if row.batch_id not in desired_ids:
                row.delete()
        for batch in (batches if current.tipo == "TANK" else ()):
            if batch.pk not in previous_ids:
                AssociazioneTankBatch.objects.create(tank=current, batch=batch, registrato_da=actor)
        CorrezioneAmministrativa.objects.create(
            modello="produzione.ControlloSessioneSemplificata", record_id=current.pk,
            valori_precedenti=before, valori_nuovi=after, motivazione=reason, eseguita_da=actor,
        )
        return current
