from django.core.exceptions import ValidationError
from django.db import transaction

from accounts.permissions import require_permission
from anagrafiche.models import Ubicazione
from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.models.protections import _stock_write

from .types import Position, persisted_id, quantity


class InsufficientStock(ValidationError):
    pass


def lock_locations(positions):
    """Acquisisce tutte le ubicazioni in ordine stabile prima delle giacenze."""
    ids = {p.ubicazione_id for p in positions if p is not None}
    locations = {u.pk: u for u in Ubicazione.objects.select_for_update().filter(pk__in=ids).order_by("pk")}
    if set(locations) != ids:
        raise ValidationError("Una delle ubicazioni non esiste.")
    if any(not u.attiva for u in locations.values()):
        raise ValidationError("Non si può movimentare un'ubicazione disattivata.")
    return locations


class MovementService:
    """Unico scrittore applicativo di stock; ogni chiamata è atomica.

    Il lock sul lotto serializza anche la creazione di giacenze assenti.
    Ubicazioni in ordine di PK, poi giacenze. Operazioni multi-lotto future
    dovranno acquisire prima tutti i lotti in ordine di PK.
    """
    PERMISSIONS = {
        Movimento.Tipo.CARICO: "can_receive_goods",
        Movimento.Tipo.TRASFERIMENTO: "can_transfer_stock",
        Movimento.Tipo.CONSUMO: "can_record_production_consumption",
        Movimento.Tipo.RETTIFICA: "can_adjust_inventory",
        Movimento.Tipo.SCARICO: "can_adjust_inventory",
        Movimento.Tipo.PRODUZIONE: "can_execute_production",
        Movimento.Tipo.QUARANTENA: "can_quarantine_stock",
        Movimento.Tipo.REINTEGRO: "can_reintegrate_stock",
        Movimento.Tipo.SCARTO: "can_scrap_nc_stock",
        Movimento.Tipo.VENDITA: "can_manage_sales",
    }

    @classmethod
    @transaction.atomic
    def register(cls, *, actor, lotto, tipo, quantita, origine=None, destinazione=None, note="", input_lavorazione=None, output_lavorazione=None, sessione_semplificata=None):
        from qualita.nc_protections import _nc_movement
        nc_context = _nc_movement.get()
        quality_movement = tipo in {Movimento.Tipo.QUARANTENA, Movimento.Tipo.REINTEGRO, Movimento.Tipo.SCARTO}
        if quality_movement and (nc_context is None or nc_context[1] != tipo):
            raise ValidationError("Le movimentazioni qualità richiedono un'azione di NonConformityService.")
        if quality_movement and (input_lavorazione is not None or output_lavorazione is not None):
            raise ValidationError("Le azioni NC non sono input/output produttivi.")
        if input_lavorazione is not None and output_lavorazione is not None:
            raise ValidationError("Input e output sono mutuamente esclusivi.")
        if tipo == Movimento.Tipo.PRODUZIONE and output_lavorazione is None and sessione_semplificata is None:
            raise ValidationError("PRODUZIONE richiede un output o una sessione semplificata.")
        permission = cls.PERMISSIONS.get(tipo)
        if permission is None:
            raise ValidationError("Tipo non disponibile nel servizio di magazzino.")
        require_permission(actor, permission)
        if tipo == Movimento.Tipo.CONSUMO:
            source = Lotto.objects.select_related("lavorazione_origine__tipo_lavorazione").filter(pk=persisted_id(lotto, "Lotto")).first()
            if source and source.lavorazione_origine_id and source.lavorazione_origine.tipo_lavorazione.fase_operativa in {"ROBOQBO", "TANK"}:
                from produzione.services.azienda_common import business_mutex
                from produzione.models.azienda import in_scope
                from produzione.models import InputLavorazione, TankAziendale
                business_mutex()
                linked = InputLavorazione.objects.filter(pk=persisted_id(input_lavorazione, "Input") if input_lavorazione is not None else None).first()
                if not linked or not in_scope(linked.lavorazione_id):
                    raise ValidationError("Batch e tank aziendali si consumano soltanto attraverso il flusso aziendale.")
                source.lavorazione_origine.refresh_from_db()
                if source.lavorazione_origine.stato != "COMPLETATA":
                    raise ValidationError("Il lotto di origine non è ancora pronto.")
                if source.lavorazione_origine.tipo_lavorazione.fase_operativa == "TANK" and not TankAziendale.objects.filter(lotto=source, pronto_il__isnull=False).exists():
                    raise ValidationError("Il tank non ha superato Brix e pH.")
        amount = quantity(quantita)
        for position in (origine, destinazione):
            if position is not None and not isinstance(position, Position):
                raise ValidationError("Usare Position per origine e destinazione.")
        if not isinstance(note, str):
            raise ValidationError("La motivazione deve essere testuale.")
        if tipo == Movimento.Tipo.RETTIFICA and not note.strip():
            raise ValidationError("La rettifica richiede una motivazione.")
        if tipo == Movimento.Tipo.SCARICO and not note.strip():
            raise ValidationError("Lo scarico materiale richiede una motivazione.")
        incoming = tipo in {Movimento.Tipo.CARICO, Movimento.Tipo.PRODUZIONE} and origine is None and destinazione is not None
        outgoing = tipo in {Movimento.Tipo.CONSUMO, Movimento.Tipo.VENDITA, Movimento.Tipo.SCARTO, Movimento.Tipo.SCARICO} and origine is not None and destinazione is None
        transfer = tipo in {Movimento.Tipo.TRASFERIMENTO, Movimento.Tipo.QUARANTENA, Movimento.Tipo.REINTEGRO} and origine is not None and destinazione is not None and origine != destinazione
        adjustment = tipo == Movimento.Tipo.RETTIFICA and ((origine is None) != (destinazione is None))
        if not any((incoming, outgoing, transfer, adjustment)):
            raise ValidationError("Origine e destinazione non sono coerenti con il tipo di movimento.")

        input_record = None
        output_record = None
        if input_lavorazione is not None:
            from produzione.models import InputLavorazione, Lavorazione
            from django.db.models import Sum
            if tipo != Movimento.Tipo.CONSUMO:
                raise ValidationError("Un input produttivo può essere collegato soltanto a CONSUMO.")
            try:
                input_record = InputLavorazione.objects.get(pk=persisted_id(input_lavorazione, "Input"))
                work = Lavorazione.objects.select_for_update().get(pk=input_record.lavorazione_id)
                input_record = InputLavorazione.objects.select_for_update().get(pk=input_record.pk)
            except (InputLavorazione.DoesNotExist, Lavorazione.DoesNotExist):
                raise ValidationError("Registrazione input inesistente.") from None
            if work.stato != Lavorazione.Stato.IN_CORSO:
                raise ValidationError("La lavorazione input non è in corso.")
            consumed = input_record.movimenti.aggregate(total=Sum("quantita"))["total"] or 0
            if consumed + amount > input_record.quantita:
                raise ValidationError("I movimenti supererebbero la quantità dichiarata nell'input.")

        if output_lavorazione is not None:
            from produzione.models import OutputLavorazione, Lavorazione
            from django.db.models import Sum
            if tipo != Movimento.Tipo.PRODUZIONE:
                raise ValidationError("Un output può essere collegato soltanto a PRODUZIONE.")
            try:
                output_record = OutputLavorazione.objects.get(pk=persisted_id(output_lavorazione, "Output"))
                work = Lavorazione.objects.select_for_update().get(pk=output_record.lavorazione_id)
                output_record = OutputLavorazione.objects.select_for_update().get(pk=output_record.pk)
            except (OutputLavorazione.DoesNotExist, Lavorazione.DoesNotExist):
                raise ValidationError("Registrazione output inesistente.") from None
            if work.stato != Lavorazione.Stato.IN_CORSO:
                raise ValidationError("La lavorazione output non è in corso.")
            produced = output_record.movimenti.aggregate(total=Sum("quantita"))["total"] or 0
            if produced + amount > output_record.quantita:
                raise ValidationError("I movimenti supererebbero la quantità dichiarata nell'output.")

        try:
            lot = Lotto.objects.select_for_update().get(pk=persisted_id(lotto, "Lotto"))
        except Lotto.DoesNotExist:
            raise ValidationError("Il lotto non esiste.") from None
        if tipo == Movimento.Tipo.CARICO and lot.tipo != Lotto.Tipo.ACQUISTO:
            raise ValidationError("CARICO ammesso soltanto per lotti di acquisto.")
        locations = lock_locations((origine, destinazione))
        source = None
        if origine is not None:
            source = Giacenza.objects.select_for_update().filter(lotto=lot, **origine.stock_lookup()).first()
            if source is None or source.quantita < amount:
                raise InsufficientStock("Stock insufficiente nella posizione di origine.")
            from qualita.nc_selectors import quarantine_balances, blocked_quantity
            balances = quarantine_balances(lotto=lot)
            position_key = dict(lotto_id=lot.pk, ubicazione_id=origine.ubicazione_id, scaffale=origine.scaffale, piano=origine.piano)
            blocked = blocked_quantity(balances, **position_key)
            owned = blocked_quantity(balances, **position_key, nc_id=nc_context[0]) if quality_movement else 0
            available = source.quantita - blocked
            if tipo == Movimento.Tipo.REINTEGRO:
                available = owned
            elif tipo == Movimento.Tipo.SCARTO:
                available += owned
            if amount > available:
                raise InsufficientStock("Quantità non disponibile: stock vincolato in quarantena o saldo insufficiente per questa NC.")
        target = None
        if destinazione is not None:
            target = Giacenza.objects.select_for_update().filter(lotto=lot, **destinazione.stock_lookup()).first()
            if target is None:
                target = Giacenza(lotto=lot, **destinazione.stock_lookup(), quantita=0)

        movement = Movimento(tipo=tipo, lotto=lot, quantita=amount, eseguito_da=actor, note=note, input_lavorazione=input_record, output_lavorazione=output_record, sessione_semplificata=sessione_semplificata)
        for suffix, position in (("origine", origine), ("destinazione", destinazione)):
            if position is not None:
                setattr(movement, f"ubicazione_{suffix}", locations[position.ubicazione_id])
                setattr(movement, f"scaffale_{suffix}", position.scaffale)
                setattr(movement, f"piano_{suffix}", position.piano)

        # Validare ogni valore finale prima di salvare il primo record.
        movement.full_clean()
        if source is not None:
            source.quantita -= amount
            source.full_clean()
        if target is not None:
            target.quantita += amount
            target.full_clean()
        with _stock_write():
            movement.save()
            if source is not None:
                source.save()
            if target is not None:
                target.save()
        return movement
