from decimal import Decimal
from collections import defaultdict
from django.core.exceptions import ValidationError
from django.db.models import Sum
from django.utils import timezone
from accounts.permissions import require_permission
from anagrafiche.models import Articolo
from magazzino.models import Lotto
from magazzino.services import Allocation
from magazzino.selectors import StockProposalService
from produzione.models import (BatchPiano, LineaProduttiva, PostazioneLinea, Ricetta, CicloProduzione,
    Lavorazione, TankAziendale, SessioneInvasettamento, CarrelloSessione, TrattamentoCarrello,
    RiepilogoInvasettamento, RequisitoInputTipoLavorazione)
from produzione.models.azienda import azienda_write
from .locking import get_record
from .materials import InputService, OutputService, InputSelection
from .execution import WorkExecutionService
from .units import ResourceService, WorkUnitService
from .azienda_common import (business_atomic, active_shift, open_session, require_control,
    recipe_mass, rounded, principal, totals, NumberingService)


def new_work(actor, kind, article, recipe=None, cycle=None):
    if not kind or not kind.attivo or not article.attivo:
        raise ValidationError("Processo o articolo inattivo.")
    cycle = cycle or CicloProduzione.objects.create(articolo=article, creato_da=actor)
    return Lavorazione.objects.create(ciclo_produzione=cycle, tipo_lavorazione=kind, ricetta=recipe)


def only_inputs(selections):
    selections = tuple(selections)
    if not selections or any(not isinstance(s, InputSelection) for s in selections):
        raise ValidationError("Specificare i prelievi effettivi.")
    return selections


class BatchService:
    @staticmethod
    @business_atomic
    def start(*, actor, batch):
        batch = get_record(BatchPiano, batch, "Batch")
        active_shift(actor, batch.piano.postazione)
        if batch.piano.postazione.risorsa.impieghi.filter(lavorazione__stato="IN_CORSO").exists():
            raise ValidationError("Completare il batch in corso sulla postazione prima di avviarne un altro.")
        with azienda_write(batch.lavorazione_id):
            work = WorkExecutionService.start(actor=actor, lavorazione=batch.lavorazione)
            ResourceService.assign(actor=actor, lavorazione=work, risorsa_produttiva=batch.piano.postazione.risorsa)
        return work

    @staticmethod
    @business_atomic
    def finish(*, actor, batch, destinazioni, quantita=None):
        batch = get_record(BatchPiano, batch, "Batch")
        active_shift(actor, batch.piano.postazione)
        work = batch.lavorazione
        # Il RoboQbo non richiede una pesata: quantità contabile nominale
        # ricavata dalla ricetta. I semilavorati possono avere un output reale.
        if quantita is None:
            quantita = recipe_mass(batch.piano.ricetta)
        with azienda_write(work.pk):
            output = OutputService.register(actor=actor, lavorazione=work, requisito_output=principal(work.tipo_lavorazione),
                quantita=quantita, destinazioni=destinazioni)
            WorkExecutionService.complete(actor=actor, lavorazione=work)
        return output


class TankService:
    @staticmethod
    @business_atomic
    def form(*, actor, postazione, ricetta, selections, destinazioni, quantita=None):
        station = get_record(PostazioneLinea, postazione, "Postazione")
        active_shift(actor, station)
        recipe = get_record(Ricetta, ricetta, "Ricetta")
        line, kind = station.linea, station.linea.tipo_tank
        if station.ruolo != "BATCH" or not kind:
            raise ValidationError("Postazione non abilitata alla formazione tank.")
        brix = require_control(kind, "BRIX", "DECIMALE")
        ph = require_control(kind, "PH", "DECIMALE")
        if (brix.valore_minimo, brix.valore_massimo, brix.minimo_esclusivo, brix.massimo_esclusivo) != (Decimal(40), Decimal(45), True, True):
            raise ValidationError("Configurare 40 < Brix < 45.")
        if ph.valore_minimo is not None or ph.valore_massimo != Decimal("4.1") or ph.massimo_esclusivo:
            raise ValidationError("Configurare pH <= 4,1.")
        selections = only_inputs(selections)
        if quantita is None:
            quantita = sum(s.quantita for s in selections)
        theoretical = Decimal(0)
        for s in selections:
            lot = get_record(Lotto, s.lotto, "Lotto")
            batch = BatchPiano.objects.filter(lavorazione_id=lot.lavorazione_origine_id).select_related("piano__postazione").first()
            if not batch or batch.piano.ricetta_id != recipe.pk or batch.piano.postazione.linea_id != line.pk or batch.lavorazione.stato != "COMPLETATA":
                raise ValidationError("Usare batch completati della stessa linea e versione di ricetta.")
            output = batch.lavorazione.outputs.get(lotto=lot)
            theoretical += recipe_mass(batch.piano.ricetta) * s.quantita / output.quantita
        work = new_work(actor, kind, recipe.articolo)
        with azienda_write(work.pk):
            WorkExecutionService.start(actor=actor, lavorazione=work)
            InputService.register_many(actor=actor, lavorazione=work, selections=selections)
            output = OutputService.register(actor=actor, lavorazione=work, requisito_output=principal(kind, "TNK"),
                articolo=recipe.articolo, quantita=quantita, destinazioni=destinazioni)
            tank = TankAziendale.objects.create(linea=line, ricetta=recipe, lavorazione=work, lotto=output.lotto, massa_teorica=rounded(theoretical))
        return tank

    @staticmethod
    @business_atomic
    def release_if_ready(*, actor, lavorazione):
        tank = TankAziendale.objects.filter(lavorazione=lavorazione).first()
        if not tank or tank.pronto_il:
            return tank
        from qualita.services import QualityService
        if QualityService.completion_errors(lavorazione):
            return tank
        kind = lavorazione.tipo_lavorazione
        # Entrambe le misure devono esistere e tutte le misure determinanti
        # devono essere conformi: un C successivo non cancella una NC/NA storica.
        for function in ("BRIX", "PH"):
            req = require_control(kind, function, "DECIMALE")
            if not lavorazione.controlli_qualita.filter(controllo_richiesto=req, conforme=True).exists():
                return tank
        with azienda_write(lavorazione.pk):
            from .completion import CompletionValidator
            from produzione.models.protections import _execution_write
            require_permission(actor, "can_record_quality_control")
            CompletionValidator.validate(lavorazione)
            with _execution_write():
                lavorazione.stato = "COMPLETATA"
                lavorazione.data_ora_fine = timezone.now()
                lavorazione.note += f"\nRilascio automatico tank dopo i controlli di {actor.get_username()}."
                lavorazione.save()
            tank.pronto_il = timezone.now()
            tank.save()
        return tank


class FillingService:
    @staticmethod
    @business_atomic
    def open(*, actor, postazione, ricetta, selections, articolo_vasetti, articolo_capsule, requisito_vasetti, requisito_capsule):
        station = get_record(PostazioneLinea, postazione, "Postazione")
        shift = active_shift(actor, station, hygiene=True)
        if station.ruolo != "INVASETTAMENTO" or shift.sessioni.filter(chiusa_il__isnull=True).exists():
            raise ValidationError("La postazione deve essere di invasettamento e senza sessioni aperte nel turno.")
        line, kind = station.linea, station.linea.tipo_invasettamento
        if not kind or not line.tipo_pastorizzazione_id or not line.tipo_vuoto_id:
            raise ValidationError("Completare la configurazione della linea confetture.")
        for phase, function, order in ((line.tipo_pastorizzazione, "PAST", 1), (line.tipo_vuoto, "VUOTO", 2)):
            require_control(phase, function, "ESITO")
            if not kind.fasi_unita_richieste.filter(tipo_fase=phase, obbligatorio=True, ordine=order).exists():
                raise ValidationError("Configurare il percorso obbligatorio: pastorizzazione, poi shock termico/vuoto.")
        recipe = get_record(Ricetta, ricetta, "Ricetta")
        recipe_mass(recipe)
        if not recipe.attiva or recipe.articolo.unita_misura != "KG":
            raise ValidationError("Selezionare una ricetta attiva con prodotto in KG.")
        jars = get_record(Articolo, articolo_vasetti, "Articolo vasetti")
        caps = get_record(Articolo, articolo_capsule, "Articolo capsule")
        jar_req = get_record(RequisitoInputTipoLavorazione, requisito_vasetti, "Requisito vasetti")
        cap_req = get_record(RequisitoInputTipoLavorazione, requisito_capsule, "Requisito capsule")
        if jars.pk == caps.pk or jars.unita_misura != "PZ" or caps.unita_misura != "PZ" or not jars.attivo or not caps.attivo:
            raise ValidationError("Vasetti e capsule devono essere due articoli attivi distinti, in PZ.")
        for req, article in ((jar_req, jars), (cap_req, caps)):
            if req.tipo_lavorazione_id != kind.pk or not req.accetta_articolo(article) or not req.multiplo or not req.obbligatorio:
                raise ValidationError("Configurare requisiti obbligatori e multipli per vasetti e capsule.")
        if jar_req.pk == cap_req.pk:
            raise ValidationError("Vasetti e capsule richiedono requisiti distinti.")
        selections = only_inputs(selections)
        FillingService._check_tanks(line, recipe, selections)
        work = new_work(actor, kind, recipe.articolo)
        with azienda_write(work.pk):
            WorkExecutionService.start(actor=actor, lavorazione=work)
            lot = OutputService.prepare_lot(actor=actor, lavorazione=work, requisito_output=principal(kind, "FINALE"), articolo=recipe.articolo)
            session = SessioneInvasettamento.objects.create(turno=shift, ricetta=recipe, lavorazione=work, lotto=lot,
                articolo_vasetti=jars, articolo_capsule=caps, requisito_vasetti=jar_req, requisito_capsule=cap_req)
            InputService.register_many(actor=actor, lavorazione=work, selections=selections)
            ResourceService.assign(actor=actor, lavorazione=work, risorsa_produttiva=station.risorsa)
        return session

    @staticmethod
    def _check_tanks(line, recipe, selections):
        for selection in selections:
            tank = TankAziendale.objects.filter(lotto_id=selection.lotto).select_related("lavorazione").first()
            if not tank or not tank.pronto_il or tank.lavorazione.stato != "COMPLETATA":
                raise ValidationError("È necessario un tank pronto: Brix e pH conformi.")
            if tank.linea_id != line.pk or tank.ricetta_id != recipe.pk:
                raise ValidationError("Tutti i tank devono appartenere alla linea e alla stessa versione di ricetta della sessione.")

    @staticmethod
    @business_atomic
    def add_tanks(*, actor, sessione, selections):
        session = open_session(actor, sessione)
        selections = only_inputs(selections)
        FillingService._check_tanks(session.turno.postazione.linea, session.ricetta, selections)
        with azienda_write(session.lavorazione_id):
            return InputService.register_many(actor=actor, lavorazione=session.lavorazione, selections=selections)

    @staticmethod
    @business_atomic
    def add_cart(*, actor, sessione, risorsa_produttiva=None):
        session = open_session(actor, sessione)
        if not session.lavorazione.inputs.filter(lotto__tank_aziendale__isnull=False).exists():
            raise ValidationError("Prelevare almeno un tank pronto prima di formare carrelli.")
        with azienda_write(session.lavorazione_id):
            code = NumberingService.next(articolo=session.ricetta.articolo, famiglia="CRL")
            unit = WorkUnitService.create(actor=actor, lavorazione_origine=session.lavorazione, lotto=session.lotto,
                risorsa_produttiva=risorsa_produttiva, codice=code)
            return CarrelloSessione.objects.create(sessione=session, unita=unit)

    @staticmethod
    @business_atomic
    def treat_cart(*, actor, carrello, fase, esito):
        cart = get_record(CarrelloSessione, carrello, "Carrello")
        session = open_session(actor, cart.sessione)
        line = session.turno.postazione.linea
        if fase not in {"PASTORIZZAZIONE", "VUOTO"} or esito not in {"C", "NC", "NA"}:
            raise ValidationError("Trattamento o esito non valido.")
        if cart.trattamenti.filter(fase=fase).exists():
            raise ValidationError("Trattamento già registrato: non sovrascrivere lo storico.")
        kind = line.tipo_pastorizzazione if fase == "PASTORIZZAZIONE" else line.tipo_vuoto
        req = require_control(kind, "PAST" if fase == "PASTORIZZAZIONE" else "VUOTO", "ESITO")
        work = new_work(actor, kind, session.ricetta.articolo, cycle=session.lavorazione.ciclo_produzione)
        from qualita.services import QualityService
        with azienda_write(work.pk, session.lavorazione_id):
            treatment = TrattamentoCarrello.objects.create(carrello=cart, lavorazione=work, fase=fase)
            WorkExecutionService.start(actor=actor, lavorazione=work)
            WorkUnitService.participate(actor=actor, unita_lavorazione=cart.unita, lavorazione=work)
            QualityService.record(actor=actor, lavorazione=work, controllo_richiesto=req, valore=esito)
            if esito == "C":
                WorkExecutionService.complete(actor=actor, lavorazione=work)
            # NC e NA restano documentati e bloccanti: non si forza completamento
            # né si introduce qui una nuova procedura di gestione NC.
        return treatment

    @staticmethod
    def theoretical_mass(session):
        theoretical = Decimal(0)
        for record in session.lavorazione.inputs.filter(lotto__tank_aziendale__isnull=False).select_related("lotto__tank_aziendale"):
            tank = record.lotto.tank_aziendale
            output = tank.lavorazione.outputs.get(lotto=tank.lotto)
            theoretical += tank.massa_teorica * record.quantita / output.quantita
        return rounded(theoretical)

    @staticmethod
    def packaging_forecast(*, actor, sessione, vasetti_buoni, vasetti_scarti, capsule_difettose, peso_netto_g, ubicazioni=None):
        require_permission(actor, "can_execute_production")
        session = get_record(SessioneInvasettamento, sessione, "Sessione")
        values = totals(buoni=vasetti_buoni, scarti=vasetti_scarti, capsule_difettose=capsule_difettose,
            peso_g=peso_netto_g, teorico=FillingService.theoretical_mass(session))
        selections, missing = [], {}
        for article, req, amount in ((session.articolo_vasetti, session.requisito_vasetti, values["vasetti"]),
                                      (session.articolo_capsule, session.requisito_capsule, values["capsule"])):
            proposal = StockProposalService.propose(actor=actor, articolo=article, quantita=amount, ubicazioni=ubicazioni)
            missing[article.pk] = proposal.mancante
            selections.extend(InputSelection(line.lotto_id, line.quantita, [Allocation(line.posizione, line.quantita)], requisito_input=req)
                              for line in proposal.righe)
        return values, tuple(selections), missing

    @staticmethod
    @business_atomic
    def close(*, actor, sessione, vasetti_buoni, vasetti_scarti, capsule_difettose, peso_netto_g, selections, destinazioni):
        session = open_session(actor, sessione)
        work = session.lavorazione
        values = totals(buoni=vasetti_buoni, scarti=vasetti_scarti, capsule_difettose=capsule_difettose,
            peso_g=peso_netto_g, teorico=FillingService.theoretical_mass(session))
        carts = list(session.carrelli.select_related("unita"))
        if not carts:
            raise ValidationError("La sessione non ha carrelli.")
        for cart in carts:
            completed = set(cart.trattamenti.filter(lavorazione__stato="COMPLETATA").values_list("fase", flat=True))
            if completed != {"PASTORIZZAZIONE", "VUOTO"}:
                raise ValidationError("Completare entrambi i trattamenti conformi per ogni carrello.")
        selections = only_inputs(selections)
        expected = {session.requisito_vasetti_id: (session.articolo_vasetti_id, values["vasetti"]),
                    session.requisito_capsule_id: (session.articolo_capsule_id, values["capsule"])}
        actual = defaultdict(Decimal)
        for s in selections:
            if s.requisito_input not in expected:
                raise ValidationError("Prelievo di confezionamento estraneo alla sessione.")
            lot = get_record(Lotto, s.lotto, "Lotto")
            if lot.articolo_id != expected[s.requisito_input][0] or s.quantita != s.quantita.to_integral_value():
                raise ValidationError("Articolo o numero di pezzi non valido.")
            actual[s.requisito_input] += s.quantita
        if dict(actual) != {req: Decimal(qty) for req, (_, qty) in expected.items()}:
            raise ValidationError("I prelievi devono coincidere con vasetti totali e capsule totali + difettose.")
        with azienda_write(work.pk):
            InputService.register_many(actor=actor, lavorazione=work, selections=selections)
            summary = RiepilogoInvasettamento.objects.create(sessione=session, vasetti_buoni=vasetti_buoni,
                vasetti_scarti=vasetti_scarti, capsule_difettose=capsule_difettose, peso_netto_g=values["peso_g"],
                massa_teorica_kg=values["teorico"], massa_reale_kg=values["massa_reale"], massa_buona_kg=values["massa_buona"],
                resa_percentuale=values["resa"], chiuso_da=actor)
            if vasetti_buoni:
                OutputService.register(actor=actor, lavorazione=work, requisito_output=principal(work.tipo_lavorazione, "FINALE"),
                    lotto=session.lotto, quantita=values["massa_buona"], destinazioni=destinazioni)
            elif tuple(destinazioni):
                raise ValidationError("Nessuna destinazione di prodotto buono quando tutti i vasetti sono scarti.")
            for cart in carts:
                WorkUnitService.close(actor=actor, unita_lavorazione=cart.unita)
            WorkExecutionService.complete(actor=actor, lavorazione=work)
            session.chiusa_il = timezone.now()
            session.save()
        return summary
