from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone
import re
from datetime import datetime
from decimal import Decimal

from accounts.permissions import require_permission
from produzione.models import (
    AssociazioneTankBatch,
    AzioneNCSessioneSemplificata,
    ControlloSessioneSemplificata,
    NonConformitaSessioneSemplificata,
    PrelievoSessioneSemplificata,
    RiepilogoSessioneSemplificata,
    SessioneProduzioneSemplificata,
    VerificaNCSessioneSemplificata,
)
from .azienda_common import business_mutex


def _record(record):
    record.full_clean()
    record.save()
    return record


class ProduzioneSemplificataService:
    @staticmethod
    def _consuma_giacenze(*, actor, sessione, giacenze, quantita, note):
        from anagrafiche.models import CategoriaArticolo
        from magazzino.models import Movimento
        from magazzino.services import MovementService, Position
        selected = list(giacenze)
        if not selected:
            raise ValidationError("Selezionare almeno un lotto MOCA.")
        stock_model = selected[0].__class__
        stocks = list(stock_model.objects.select_for_update().filter(
            pk__in=[stock.pk for stock in selected], quantita__gt=0,
        ).select_related("lotto__articolo", "ubicazione").order_by(
            "lotto__data_scadenza", "lotto__codice_lotto", "ubicazione__codice", "scaffale", "piano", "pk",
        ))
        amount = Decimal(str(quantita))
        if sum((stock.quantita for stock in stocks), Decimal("0")) < amount:
            raise ValidationError("La disponibilità complessiva dei lotti MOCA selezionati è insufficiente.")
        moca_categories = CategoriaArticolo.objects.filter(codice__iexact="MOCA", attiva=True)
        if any(not any(stock.lotto.articolo.appartiene_a_categoria_o_discendenti(category) for category in moca_categories) for stock in stocks):
            raise ValidationError("Il lotto selezionato non appartiene alla categoria MOCA.")
        rows = []
        remaining = amount
        for stock in stocks:
            if remaining <= 0:
                break
            used = min(stock.quantita, remaining)
            movement = MovementService.register(
                actor=actor, lotto=stock.lotto, tipo=Movimento.Tipo.CONSUMO, quantita=used,
                origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano), note=note,
            )
            rows.append(_record(PrelievoSessioneSemplificata(
                sessione=sessione, lotto=stock.lotto, movimento=movement, quantita_kg=used,
                numero_batch=None, da_ricetta=False, registrato_da=actor, note=note,
            )))
            remaining -= used
        return rows

    @staticmethod
    def _code(*, tipo, ricetta, giorno=None):
        from magazzino.models import Lotto

        day = giorno or timezone.localdate()
        if tipo == "SEMILAVORATO":
            stem = f"SLV{day:%y%m%d}"
            # Si considera sia lo storico delle sessioni sia quello dei lotti: anche dopo
            # pulizie parziali del DB il progressivo non può ripartire da 01.
            codes = list(SessioneProduzioneSemplificata.objects.filter(
                tipo=tipo, ricetta__articolo=ricetta.articolo
            ).values_list("lotto_codice", flat=True))
            codes.extend(Lotto.objects.filter(
                articolo=ricetta.articolo, tipo=Lotto.Tipo.PRODUZIONE
            ).values_list("codice_lotto", flat=True))
            pattern = re.compile(rf"^{re.escape(stem)}-(\d+)$")
            temporary_pattern = re.compile(rf"^SL{day:%y%m%d}(\d+)$")
            used = []
            for code in codes:
                match = pattern.fullmatch(code) or temporary_pattern.fullmatch(code)
                if match:
                    used.append(int(match.group(1)))
            return f"{stem}-{max(used, default=0) + 1:02d}"

        if tipo == "ETICHETTATURA":
            stem = f"{day:%y%m%d}"
            used = set(SessioneProduzioneSemplificata.objects.filter(
                tipo=tipo, ricetta__articolo=ricetta.articolo, lotto_codice__startswith=stem,
            ).values_list("lotto_codice", flat=True))
            if stem not in used:
                return stem
            number = 1
            while True:
                value, n = "", number
                while n:
                    n, remainder = divmod(n - 1, 26)
                    value = chr(65 + remainder) + value
                if f"{stem}{value}" not in used:
                    return f"{stem}{value}"
                number += 1

        prefix = {"ROBOQBO": "RBQB", "INVASETTAMENTO": "INV"}[tipo]
        stem = f"{prefix}{day:%y%m%d}"
        number = SessioneProduzioneSemplificata.objects.filter(
            tipo=tipo, ricetta__articolo=ricetta.articolo, lotto_codice__startswith=f"{stem}-"
        ).count() + 1
        return f"{stem}-{number:02d}"

    @classmethod
    @transaction.atomic
    def apri_semilavorato(cls, *, actor, ricetta, numero_batch_previsti, note=""):
        require_permission(actor, "can_execute_production")
        business_mutex()
        from produzione.models import Ricetta
        ricetta = Ricetta.objects.select_for_update().get(pk=ricetta.pk)
        if SessioneProduzioneSemplificata.objects.select_for_update().filter(tipo="SEMILAVORATO", stato__in=["PIANIFICATA", "APERTA"]).exists():
            raise ValidationError("Il modulo Semilavorati ha già una sessione aperta.")
        return _record(SessioneProduzioneSemplificata(
            tipo="SEMILAVORATO", postazione=None, ricetta=ricetta,
            lotto_codice=cls._code(tipo="SEMILAVORATO", ricetta=ricetta),
            quantita_prevista_kg=None, numero_batch_previsti=numero_batch_previsti,
            numero_lavorazioni_previste=numero_batch_previsti,
            aperta_da=actor, note=note,
        ))

    @classmethod
    @transaction.atomic
    def apri_roboqbo(cls, *, actor, ricetta, numero_batch_previsti, note=""):
        require_permission(actor, "can_execute_production")
        business_mutex()
        from produzione.models import Ricetta
        ricetta = Ricetta.objects.select_for_update().get(pk=ricetta.pk)
        if SessioneProduzioneSemplificata.objects.select_for_update().filter(tipo="ROBOQBO", stato__in=["PIANIFICATA", "APERTA"]).exists():
            raise ValidationError("Il modulo RoboQbo ha già una sessione aperta.")
        return _record(SessioneProduzioneSemplificata(
            tipo="ROBOQBO", postazione=None, ricetta=ricetta,
            lotto_codice=cls._code(tipo="ROBOQBO", ricetta=ricetta),
            numero_batch_previsti=numero_batch_previsti, aperta_da=actor, note=note,
        ))

    @classmethod
    @transaction.atomic
    def apri_invasettamento(cls, *, actor, lotto_origine, igienizzazione_confermata, note=""):
        require_permission(actor, "can_execute_production")
        business_mutex()
        source = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=lotto_origine.pk)
        if source.tipo != "ROBOQBO":
            raise ValidationError("Selezionare un lotto RoboQbo.")
        if source.stato not in {"APERTA", "CHIUSA"}:
            raise ValidationError("Il lotto RoboQbo deve essere già stato avviato.")
        if source.sessioni_invasettamento.exists():
            raise ValidationError("Il lotto RoboQbo è già stato scelto per un invasettamento.")
        if not igienizzazione_confermata:
            raise ValidationError("Confermare la pulizia e igienizzazione di vasetti e capsule.")
        if SessioneProduzioneSemplificata.objects.select_for_update().filter(tipo="INVASETTAMENTO", stato__in=["PIANIFICATA", "APERTA"]).exists():
            raise ValidationError("Il modulo Invasettamento ha già una sessione aperta.")
        return _record(SessioneProduzioneSemplificata(
            tipo="INVASETTAMENTO", postazione=None, ricetta=source.ricetta,
            lotto_codice=cls._code(tipo="INVASETTAMENTO", ricetta=source.ricetta),
            lotto_origine=source, igienizzazione_confermata_il=timezone.now(), aperta_da=actor, note=note,
        ))

    @classmethod
    @transaction.atomic
    def apri_etichettatura(cls, *, actor, lotto_origine, note=""):
        require_permission(actor, "can_execute_production")
        business_mutex()
        source = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=lotto_origine.pk)
        if source.tipo != "INVASETTAMENTO" or source.stato != "CHIUSA" or not source.lotto_prodotto_id:
            raise ValidationError("Selezionare un lotto invasettato chiuso e presente in magazzino.")
        if SessioneProduzioneSemplificata.objects.select_for_update().filter(
            tipo="ETICHETTATURA", stato__in=["PIANIFICATA", "APERTA"]
        ).exists():
            raise ValidationError("Il modulo Etichettatura ha già una sessione aperta.")
        return _record(SessioneProduzioneSemplificata(
            tipo="ETICHETTATURA", postazione=None, ricetta=source.ricetta,
            lotto_codice=cls._code(tipo="ETICHETTATURA", ricetta=source.ricetta),
            lotto_origine=source, aperta_da=actor, note=note,
        ))

    @classmethod
    @transaction.atomic
    def apri_confezionamento(cls, *, actor, lotto_origine, note=""):
        from magazzino.models import Lotto
        require_permission(actor, "can_execute_production")
        business_mutex()
        source = SessioneProduzioneSemplificata.objects.select_for_update().select_related("lotto_prodotto").get(pk=lotto_origine.pk)
        if source.tipo != "ETICHETTATURA" or source.stato != "CHIUSA" or not source.lotto_prodotto_id:
            raise ValidationError("Selezionare un lotto etichettato chiuso.")
        if source.lotto_prodotto.stato_confezionamento == Lotto.StatoConfezionamento.CONFEZIONATO:
            raise ValidationError("Il lotto è già interamente confezionato.")
        if SessioneProduzioneSemplificata.objects.select_for_update().filter(tipo="CONFEZIONAMENTO", stato__in=["PIANIFICATA", "APERTA"]).exists():
            raise ValidationError("Il modulo Confezionamento ha già una sessione aperta.")
        return _record(SessioneProduzioneSemplificata(
            tipo="CONFEZIONAMENTO", ricetta=source.ricetta, lotto_codice=source.lotto_codice,
            lotto_origine=source, aperta_da=actor, note=note,
        ))

    @staticmethod
    @transaction.atomic
    def registra_controllo(*, actor, sessione, tipo, numero, batch_associati=(), **values):
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        if current.stato != "APERTA":
            raise ValidationError("La sessione è chiusa.")
        control = _record(ControlloSessioneSemplificata(
            sessione=current, tipo=tipo, numero=numero, registrato_da=actor, **values
        ))
        if tipo == ControlloSessioneSemplificata.Tipo.TANK:
            batch_ids = [batch.pk for batch in batch_associati]
            batches = list(ControlloSessioneSemplificata.objects.select_for_update().filter(
                pk__in=batch_ids, sessione=current, tipo=ControlloSessioneSemplificata.Tipo.BATCH,
                associazione_tank__isnull=True,
            ))
            if len(batches) != len(set(batch_ids)) or not batches:
                raise ValidationError("Selezionare batch liberi appartenenti alla stessa produzione RoboQbo.")
            for batch in batches:
                _record(AssociazioneTankBatch(
                    tank=control, batch=batch, registrato_da=actor,
                ))
        elif batch_associati:
            raise ValidationError("I batch possono essere associati soltanto a un controllo tank.")
        return control

    @staticmethod
    @transaction.atomic
    def registra_tabella_batch(*, actor, sessione, righe):
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        if current.tipo != "ROBOQBO" or current.stato != "APERTA":
            raise ValidationError("La tabella batch è modificabile soltanto durante una produzione RoboQbo aperta.")
        rows = tuple(righe)
        expected = set(range(1, current.numero_batch_previsti + 1))
        if {row["numero"] for row in rows} != expected or len(rows) != len(expected):
            raise ValidationError("La tabella deve contenere esattamente tutti i batch previsti.")
        existing = {
            control.numero: control
            for control in ControlloSessioneSemplificata.objects.select_for_update().filter(
                sessione=current, tipo="BATCH", numero__in=expected
            )
        }
        day = timezone.localdate()
        saved = []
        for row in rows:
            number = row["numero"]
            values = {
                "inizio": timezone.make_aware(datetime.combine(day, row["inizio"])) if row.get("inizio") else None,
                "fine": timezone.make_aware(datetime.combine(day, row["fine"])) if row.get("fine") else None,
                "esito_tracciato_termico": row.get("esito_tracciato_termico", ""),
            }
            control = existing.get(number)
            if control is None:
                if not any(values.values()):
                    continue
                control = ControlloSessioneSemplificata(
                    sessione=current, tipo="BATCH", numero=number, registrato_da=actor
                )
            for field, value in values.items():
                setattr(control, field, value)
            control.registrato_da = actor
            saved.append(_record(control))
        return saved

    @staticmethod
    @transaction.atomic
    def avvia(*, actor, sessione):
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        if current.stato != "PIANIFICATA":
            raise ValidationError("Soltanto una produzione pianificata può essere avviata.")
        current.stato, current.iniziata_il = "APERTA", timezone.now()
        return _record(current)

    @staticmethod
    @transaction.atomic
    def annulla(*, actor, sessione):
        require_permission(actor, "can_cancel_unstarted_work")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        if current.stato != "PIANIFICATA" or current.iniziata_il is not None:
            raise ValidationError("La produzione è già iniziata e non può essere annullata.")
        current.stato, current.chiusa_da, current.chiusa_il = "ANNULLATA", actor, timezone.now()
        return _record(current)

    @staticmethod
    @transaction.atomic
    def segnala_nc(*, actor, sessione, descrizione, controllo=None, quantita_coinvolta_kg=None, vasetti_coinvolti=None, note=""):
        require_permission(actor, "can_open_nc")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        # La NC è solo documentale: non cambia sessione, giacenze o movimenti.
        return _record(NonConformitaSessioneSemplificata(
            sessione=current, controllo=controllo, descrizione=descrizione,
            quantita_coinvolta_kg=quantita_coinvolta_kg, vasetti_coinvolti=vasetti_coinvolti,
            aperta_da=actor, note=note,
        ))

    @staticmethod
    @transaction.atomic
    def prendi_in_carico_nc(*, actor, non_conformita, note=""):
        require_permission(actor, "can_manage_nc")
        nc = NonConformitaSessioneSemplificata.objects.select_for_update().get(pk=non_conformita.pk)
        if nc.stato != nc.Stato.APERTA:
            raise ValidationError("Soltanto una NC aperta può essere presa in carico.")
        nc.stato = nc.Stato.IN_GESTIONE
        nc.presa_in_carico_da = actor
        nc.presa_in_carico_il = timezone.now()
        if note:
            nc.note += f"\nPresa in carico: {note}"
        return _record(nc)

    @staticmethod
    @transaction.atomic
    def registra_azione_nc(*, actor, non_conformita, tipo, descrizione, origine_stock=None,
                           quantita=None, note=""):
        require_permission(actor, "can_manage_nc")
        nc = NonConformitaSessioneSemplificata.objects.select_for_update().get(pk=non_conformita.pk)
        if nc.stato != nc.Stato.IN_GESTIONE:
            raise ValidationError("Prendere prima in carico la NC.")
        movement = None
        if tipo == AzioneNCSessioneSemplificata.Tipo.SCARTO:
            from magazzino.models import Movimento
            from magazzino.services import MovementService, Position
            from qualita.nc_protections import _movement_for_nc
            if not origine_stock or not quantita:
                raise ValidationError("Per lo scarto indicare posizione e quantità.")
            if not nc.sessione.lotto_prodotto_id or origine_stock.lotto_id != nc.sessione.lotto_prodotto_id:
                raise ValidationError("La posizione deve contenere il lotto prodotto collegato alla NC.")
            source = Position(origine_stock.ubicazione_id, origine_stock.scaffale, origine_stock.piano)
            with _movement_for_nc(-nc.pk, Movimento.Tipo.SCARTO):
                movement = MovementService.register(
                    actor=actor, lotto=origine_stock.lotto, tipo=Movimento.Tipo.SCARTO,
                    quantita=quantita, origine=source, note=f"Scarto NC P-{nc.pk}: {descrizione}",
                )
        elif tipo != AzioneNCSessioneSemplificata.Tipo.AZIONE:
            raise ValidationError("Tipo di azione non riconosciuto.")
        return _record(AzioneNCSessioneSemplificata(
            non_conformita=nc, tipo=tipo, descrizione=descrizione, movimento=movement,
            registrata_da=actor, note=note,
        ))

    @staticmethod
    @transaction.atomic
    def verifica_nc(*, actor, non_conformita, esito, descrizione, note=""):
        require_permission(actor, "can_verify_nc")
        nc = NonConformitaSessioneSemplificata.objects.select_for_update().get(pk=non_conformita.pk)
        if nc.stato != nc.Stato.IN_GESTIONE:
            raise ValidationError("Prendere prima in carico la NC.")
        if not nc.azioni.exists():
            raise ValidationError("Registrare almeno un'azione prima della verifica.")
        return _record(VerificaNCSessioneSemplificata(
            non_conformita=nc, esito=esito, descrizione=descrizione,
            verificata_da=actor, note=note,
        ))

    @staticmethod
    @transaction.atomic
    def chiudi_nc(*, actor, non_conformita, note):
        require_permission(actor, "can_close_nc")
        nc = NonConformitaSessioneSemplificata.objects.select_for_update().get(pk=non_conformita.pk)
        if nc.stato != nc.Stato.IN_GESTIONE:
            raise ValidationError("La NC deve essere in gestione.")
        if not note or not note.strip():
            raise ValidationError("Indicare la motivazione di chiusura.")
        action = nc.azioni.order_by("-registrata_il", "-pk").first()
        verification = nc.verifiche.order_by("-verificata_il", "-pk").first()
        if not action or not verification or verification.esito != VerificaNCSessioneSemplificata.Esito.EFFICACE or verification.verificata_il < action.registrata_il:
            raise ValidationError("Serve una verifica efficace successiva all'ultima azione.")
        nc.stato = nc.Stato.CHIUSA
        nc.chiusa_da = actor
        nc.chiusa_il = timezone.now()
        nc.note += f"\nChiusura: {note.strip()}"
        return _record(nc)

    @staticmethod
    @transaction.atomic
    def chiudi_roboqbo(*, actor, sessione):
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        if current.tipo != "ROBOQBO" or current.stato != "APERTA":
            raise ValidationError("La sessione RoboQbo non è aperta.")
        current.stato, current.chiusa_da, current.chiusa_il = "CHIUSA", actor, timezone.now()
        return _record(current)

    @staticmethod
    @transaction.atomic
    def chiudi_semilavorato(*, actor, sessione, quantita_finale_kg, data_scadenza, destinazione,
                            moca_giacenza, moca_quantita):
        from magazzino.models import Lotto, Movimento
        from magazzino.services import MovementService
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        if current.tipo != "SEMILAVORATO" or current.stato != "APERTA":
            raise ValidationError("La sessione Semilavorati non è aperta.")
        ProduzioneSemplificataService._consuma_giacenze(
            actor=actor, sessione=current, giacenze=moca_giacenza, quantita=moca_quantita,
            note=f"MOCA utilizzato nella chiusura {current.lotto_codice}",
        )
        lot = Lotto.objects.create(articolo=current.ricetta.articolo, codice_lotto=current.lotto_codice,
            tipo=Lotto.Tipo.PRODUZIONE, data_produzione=timezone.localdate(),
            data_scadenza=data_scadenza, note=f"Prodotto da {current.lotto_codice}")
        MovementService.register(actor=actor, lotto=lot, tipo=Movimento.Tipo.PRODUZIONE,
            quantita=quantita_finale_kg, destinazione=destinazione, note=f"Chiusura {current.lotto_codice}",
            sessione_semplificata=current)
        current.lotto_prodotto, current.quantita_finale_kg = lot, quantita_finale_kg
        current.stato, current.chiusa_da, current.chiusa_il = "CHIUSA", actor, timezone.now()
        return _record(current)

    @staticmethod
    @transaction.atomic
    def chiudi_invasettamento(*, actor, sessione, vasetti_buoni, vasetti_scartati,
                              vasetti_quarantena, capsule_difettose, peso_netto_g,
                              vasetti_giacenza, capsule_giacenza, destinazione):
        from magazzino.models import Lotto, Movimento
        from magazzino.services import MovementService
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().get(pk=sessione.pk)
        if current.tipo != "INVASETTAMENTO" or current.stato != "APERTA":
            raise ValidationError("La sessione di invasettamento non è aperta.")
        vasetti_totali = vasetti_buoni + vasetti_scartati + vasetti_quarantena
        ProduzioneSemplificataService._consuma_giacenze(
            actor=actor, sessione=current, giacenze=vasetti_giacenza, quantita=vasetti_totali,
            note=f"Vasetti utilizzati nella chiusura {current.lotto_codice}",
        )
        ProduzioneSemplificataService._consuma_giacenze(
            actor=actor, sessione=current, giacenze=capsule_giacenza,
            quantita=vasetti_totali + capsule_difettose,
            note=f"Capsule utilizzate nella chiusura {current.lotto_codice}",
        )
        summary = _record(RiepilogoSessioneSemplificata(
            sessione=current, vasetti_buoni=vasetti_buoni, vasetti_scartati=vasetti_scartati,
            vasetti_quarantena=vasetti_quarantena, capsule_difettose=capsule_difettose,
            peso_netto_g=peso_netto_g, registrato_da=actor,
        ))
        lot = Lotto.objects.create(
            articolo=current.ricetta.articolo, codice_lotto=current.lotto_codice,
            tipo=Lotto.Tipo.PRODUZIONE, stato_prodotto=Lotto.StatoProdotto.INVASETTATO,
            data_produzione=timezone.localdate(), data_scadenza=None,
            note=f"Prodotto dall'invasettamento {current.lotto_codice}",
        )
        quantita_prodotta = (
            Decimal(summary.vasetti_buoni)
            if current.ricetta.articolo.unita_misura == "PZ"
            else summary.quantita_conforme_kg
        )
        if quantita_prodotta > 0:
            MovementService.register(
                actor=actor, lotto=lot, tipo=Movimento.Tipo.PRODUZIONE,
                quantita=quantita_prodotta, destinazione=destinazione,
                note=f"Chiusura invasettamento {current.lotto_codice}", sessione_semplificata=current,
            )
        current.lotto_prodotto = lot
        current.quantita_finale_kg = quantita_prodotta
        current.stato, current.chiusa_da, current.chiusa_il = "CHIUSA", actor, timezone.now()
        _record(current)
        return summary

    @staticmethod
    @transaction.atomic
    def chiudi_etichettatura(*, actor, sessione, quantita_finale_kg,
                             data_scadenza, destinazione):
        from magazzino.models import Giacenza, Lotto, Movimento
        from magazzino.services import MovementService, Position
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().select_related(
            "lotto_origine__lotto_prodotto", "ricetta__articolo"
        ).get(pk=sessione.pk)
        if current.tipo != "ETICHETTATURA" or current.stato != "APERTA":
            raise ValidationError("La sessione di etichettatura non è aperta.")
        source_lot = current.lotto_origine.lotto_prodotto
        stocks = list(Giacenza.objects.select_for_update().filter(
            lotto=source_lot, quantita__gt=0, ubicazione__attiva=True,
        ).select_related("ubicazione").order_by("ubicazione__codice", "scaffale", "piano", "pk"))
        if sum((stock.quantita for stock in stocks), Decimal("0")) < quantita_finale_kg:
            raise ValidationError("La disponibilità complessiva del lotto invasettato è insufficiente.")
        remaining = quantita_finale_kg
        for stock in stocks:
            if remaining <= 0:
                break
            used = min(stock.quantita, remaining)
            movement = MovementService.register(
                actor=actor, lotto=source_lot, tipo=Movimento.Tipo.CONSUMO, quantita=used,
                origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano),
                note=f"Etichettatura nel lotto {current.lotto_codice}",
            )
            _record(PrelievoSessioneSemplificata(
                sessione=current, lotto=source_lot, movimento=movement,
                quantita_kg=used, da_ricetta=False, registrato_da=actor,
                note="Lotto invasettato destinato all'etichettatura",
            ))
            remaining -= used
        lot = Lotto.objects.create(
            articolo=current.ricetta.articolo, codice_lotto=current.lotto_codice,
            tipo=Lotto.Tipo.PRODUZIONE, stato_prodotto=Lotto.StatoProdotto.PRODOTTO_FINITO,
            stato_confezionamento=Lotto.StatoConfezionamento.DA_CONFEZIONARE,
            data_produzione=timezone.localdate(), data_scadenza=data_scadenza,
            note=f"Prodotto dall'etichettatura del lotto {source_lot.codice_lotto}",
        )
        MovementService.register(
            actor=actor, lotto=lot, tipo=Movimento.Tipo.PRODUZIONE,
            quantita=quantita_finale_kg, destinazione=destinazione,
            note=f"Chiusura etichettatura {current.lotto_codice}", sessione_semplificata=current,
        )
        current.lotto_prodotto, current.quantita_finale_kg = lot, quantita_finale_kg
        current.stato, current.chiusa_da, current.chiusa_il = "CHIUSA", actor, timezone.now()
        return _record(current)

    @staticmethod
    @transaction.atomic
    def chiudi_confezionamento(*, actor, sessione, quantita_confezionata):
        from magazzino.models import Lotto
        require_permission(actor, "can_execute_production")
        current = SessioneProduzioneSemplificata.objects.select_for_update().select_related(
            "lotto_origine__lotto_prodotto"
        ).get(pk=sessione.pk)
        if current.tipo != "CONFEZIONAMENTO" or current.stato != "APERTA":
            raise ValidationError("La sessione di confezionamento non è aperta.")
        lot = Lotto.objects.select_for_update().get(pk=current.lotto_origine.lotto_prodotto_id)
        total = current.lotto_origine.quantita_finale_kg or Decimal("0")
        remaining = total - lot.quantita_confezionata
        if quantita_confezionata > remaining:
            raise ValidationError(f"Quantità superiore al residuo da confezionare: {remaining:g}.")
        lot.quantita_confezionata += quantita_confezionata
        lot.stato_confezionamento = (
            Lotto.StatoConfezionamento.CONFEZIONATO if lot.quantita_confezionata >= total
            else Lotto.StatoConfezionamento.PARZIALE
        )
        lot.full_clean(); lot.save(update_fields=["quantita_confezionata", "stato_confezionamento"])
        current.quantita_finale_kg = quantita_confezionata
        current.stato, current.chiusa_da, current.chiusa_il = "CHIUSA", actor, timezone.now()
        return _record(current)
