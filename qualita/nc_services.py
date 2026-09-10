from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from accounts.permissions import require_permission
from magazzino.models import Lotto
from magazzino.services import MovementService
from produzione.models import Lavorazione, RisorsaProduttiva
from produzione.services.locking import get_record, lock_work
from .models import NonConformita, AzioneNonConformita, VerificaNonConformita, ControlloQualita
from .nc_protections import _nc_write, _movement_for_nc
from .nc_selectors import quarantine_balances


def required_text(value, label):
    if not isinstance(value, str) or not value.strip():
        raise ValidationError(f"{label} obbligatoria.")
    return value.strip()


def managed_case(value):
    nc = get_record(NonConformita, value, "NC", lock=True)
    if nc.stato != "IN_GESTIONE":
        raise ValidationError("Prendere in gestione una NC aperta prima di operare; una NC chiusa è storica.")
    return nc


class NonConformityService:
    @staticmethod
    @transaction.atomic
    def open(*, actor, descrizione, tipo="INTERNA", lotto=None, lavorazione=None, controllo_qualita=None, risorsa_produttiva=None, note=""):
        require_permission(actor, "can_open_nc")
        description = required_text(descrizione, "Descrizione")
        measurement = get_record(ControlloQualita, controllo_qualita, "Controllo") if controllo_qualita is not None else None
        work = lock_work(lavorazione if lavorazione is not None else measurement.lavorazione_id) if lavorazione is not None or measurement else None
        lot = get_record(Lotto, lotto, "Lotto") if lotto is not None else None
        resource = get_record(RisorsaProduttiva, risorsa_produttiva, "Risorsa") if risorsa_produttiva is not None else None
        # Riga stabile comune: serializza il progressivo anche a tabella vuota.
        ct = ContentType.objects.get_for_model(NonConformita)
        ContentType.objects.select_for_update().get(pk=ct.pk)
        number = (NonConformita.objects.aggregate(last=Max("numero"))["last"] or 0) + 1
        with _nc_write():
            return NonConformita.objects.create(numero=number, tipo=tipo, descrizione=description,
                lotto=lot, lavorazione=work, controllo_qualita=measurement, risorsa_produttiva=resource, aperta_da=actor, note=note)

    @staticmethod
    @transaction.atomic
    def take_charge(*, actor, non_conformita, note=""):
        require_permission(actor, "can_manage_nc")
        nc = get_record(NonConformita, non_conformita, "NC", lock=True)
        if nc.stato != "APERTA":
            raise ValidationError("Solo una NC aperta può essere presa in gestione.")
        if not isinstance(note, str):
            raise ValidationError("Le note devono essere testuali.")
        with _nc_write():
            nc.stato = "IN_GESTIONE"
            nc.note += f"\n{timezone.now().isoformat()} — In gestione da {actor.get_username()}. {note}"
            nc.save()
        return nc

    @staticmethod
    @transaction.atomic
    def action(*, actor, non_conformita, tipo_azione, descrizione, lotto=None, quantita=None,
               origine=None, destinazione=None, lavorazione=None, note=""):
        require_permission(actor, "can_manage_nc")
        description = required_text(descrizione, "Descrizione azione")
        if tipo_azione not in AzioneNonConformita.TipoAzione.values:
            raise ValidationError("Tipo azione NC non valido; RETTIFICA non è uno scarto da NC.")
        nc = managed_case(non_conformita)
        work = get_record(Lavorazione, lavorazione, "Lavorazione correttiva") if lavorazione is not None else None
        physical = tipo_azione in {"QUARANTENA", "REINTEGRO", "SCARTO"}
        movement = None
        if physical:
            chosen_lot = lotto if lotto is not None else nc.lotto_id
            lot = get_record(Lotto, chosen_lot, "Lotto")
            if nc.lotto_id is not None and nc.lotto_id != lot.pk:
                raise ValidationError("Il movimento deve riferirsi al lotto della NC.")
            with _movement_for_nc(nc.pk, tipo_azione):
                movement = MovementService.register(actor=actor, lotto=lot, tipo=tipo_azione, quantita=quantita,
                    origine=origine, destinazione=destinazione, note=f"NC {nc.numero}: {description}")
        elif any(value is not None for value in (lotto, quantita, origine, destinazione)):
            raise ValidationError("Le azioni non fisiche non accettano parametri di magazzino.")
        with _nc_write():
            return AzioneNonConformita.objects.create(non_conformita=nc, tipo_azione=tipo_azione,
                descrizione=description, movimento=movement, lavorazione=work, eseguita_da=actor, note=note)

    @staticmethod
    @transaction.atomic
    def verify(*, actor, non_conformita, esito, descrizione, controllo_qualita=None, note=""):
        require_permission(actor, "can_verify_nc")
        description = required_text(descrizione, "Descrizione verifica")
        nc = managed_case(non_conformita)
        if not nc.azioni.exists():
            raise ValidationError("Registrare almeno un'azione prima della verifica.")
        measurement = get_record(ControlloQualita, controllo_qualita, "Controllo di verifica") if controllo_qualita is not None else None
        if measurement:
            latest_action = nc.azioni.order_by("-data_ora", "-pk").first()
            if esito == "EFFICACE" and measurement.data_ora < latest_action.data_ora:
                raise ValidationError("La misura di verifica deve essere successiva all'ultima azione.")
            if nc.controllo_qualita_id:
                initial = nc.controllo_qualita
                if measurement.controllo_richiesto.parametro_controllo_id != initial.controllo_richiesto.parametro_controllo_id:
                    raise ValidationError("Il controllo di verifica misura un parametro diverso.")
                if measurement.data_ora <= initial.data_ora:
                    raise ValidationError("La verifica richiede una nuova misurazione.")
            allowed_works = set(nc.azioni.exclude(lavorazione_id=None).values_list("lavorazione_id", flat=True)) | {nc.lavorazione_id}
            if measurement.lavorazione_id not in allowed_works:
                raise ValidationError("Il controllo non riguarda la NC o una lavorazione correttiva collegata.")
        with _nc_write():
            return VerificaNonConformita.objects.create(non_conformita=nc, esito=esito, descrizione=description,
                controllo_qualita=measurement, verificata_da=actor, note=note)

    @staticmethod
    @transaction.atomic
    def close(*, actor, non_conformita, note):
        require_permission(actor, "can_close_nc")
        reason = required_text(note, "Motivazione di chiusura")
        nc = managed_case(non_conformita)
        verification = nc.verifiche.order_by("-data_ora", "-pk").first()
        action = nc.azioni.order_by("-data_ora", "-pk").first()
        if not verification or verification.esito != "EFFICACE" or not action or verification.data_ora < action.data_ora:
            raise ValidationError("Serve un'ultima verifica efficace successiva a tutte le azioni.")
        if nc.azioni.filter(tipo_azione="RILAVORAZIONE").exclude(lavorazione__stato="COMPLETATA").exists():
            raise ValidationError("Completare le rilavorazioni collegate prima della chiusura NC.")
        if quarantine_balances(non_conformita=nc):
            raise ValidationError("La NC ha ancora quantità in quarantena: reintegrare o scartare prima della chiusura.")
        with _nc_write():
            nc.stato = "CHIUSA"
            nc.note += f"\n{timezone.now().isoformat()} — Chiusa da {actor.get_username()}: {reason}"
            nc.save()
        return nc
