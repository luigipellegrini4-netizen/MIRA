from collections import defaultdict
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.db.models import Sum, Max
from django.utils import timezone
from accounts.permissions import require_permission
from magazzino.models import Giacenza
from magazzino.services import Allocation, Position
from magazzino.selectors import StockProposalService
from qualita.nc_selectors import quarantine_balances, blocked_quantity
from produzione.models import (PostazioneLinea, TurnoOperativo, PianoProduzione, BatchPiano,
    RevisionePrelievo, RigaPianoPrelievo, PrelievoDaPiano, Ricetta, CicloProduzione, Lavorazione)
from produzione.models.azienda import azienda_write
from .locking import get_record
from .materials import InputSelection
from .recipe_inputs import RecipeInputService, RecipeInputProposal
from .azienda_common import business_atomic, active_shift, count, recipe_mass, require_control, principal


class ShiftService:
    @staticmethod
    @business_atomic
    def start(*, actor, postazione):
        require_permission(actor, "can_execute_production")
        station = get_record(PostazioneLinea, postazione, "Postazione")
        if not station.linea.attiva or not station.risorsa.attiva:
            raise ValidationError("Postazione non attiva.")
        if TurnoOperativo.objects.filter(operatore=actor, fine__isnull=True).exists() or station.turni.filter(fine__isnull=True).exists():
            raise ValidationError("Operatore o postazione hanno già un turno aperto.")
        with azienda_write():
            return TurnoOperativo.objects.create(postazione=station, operatore=actor, postazione_attiva=station, operatore_attivo=actor)

    @staticmethod
    @business_atomic
    def confirm_hygiene(*, actor, turno, confermato):
        shift = get_record(TurnoOperativo, turno, "Turno")
        current = active_shift(actor, shift.postazione)
        if current.pk != shift.pk or shift.postazione.ruolo != "INVASETTAMENTO" or confermato is not True:
            raise ValidationError("Confermare esplicitamente l'igienizzazione nel proprio turno di invasettamento.")
        if shift.igienizzazione_confermata_il:
            return shift
        with azienda_write():
            shift.igienizzazione_confermata_il = timezone.now()
            shift.save()
        return shift

    @staticmethod
    @business_atomic
    def end(*, actor, turno):
        shift = get_record(TurnoOperativo, turno, "Turno")
        if active_shift(actor, shift.postazione).pk != shift.pk:
            raise ValidationError("Turno diverso da quello attivo.")
        if shift.sessioni.filter(chiusa_il__isnull=True).exists():
            raise ValidationError("Chiudere la sessione prima di terminare il turno.")
        if Lavorazione.objects.filter(eseguita_da=actor, stato="IN_CORSO", tipo_lavorazione__fase_operativa__in=["ROBOQBO", "SEMILAVORATO", "TANK"]).exists():
            raise ValidationError("Completare o interrompere le lavorazioni in corso prima di terminare il turno.")
        with azienda_write():
            shift.fine = timezone.now()
            shift.postazione_attiva = None
            shift.operatore_attivo = None
            shift.save()
        return shift


class PickingPlanService:
    @staticmethod
    @business_atomic
    def create(*, actor, postazione, ricetta, numero_batch):
        require_permission(actor, "can_plan_own_batches")
        number = count(numero_batch, "Numero batch", positive=True)
        if number > 1000:
            raise ValidationError("Pianificare al massimo 1000 batch per piano.")
        station = get_record(PostazioneLinea, postazione, "Postazione")
        active_shift(actor, station)
        kind = station.linea.tipo_batch
        from produzione.models import TipoLavorazione
        kind = get_record(TipoLavorazione, kind, "Processo", lock=True)
        recipe = get_record(Ricetta, ricetta, "Ricetta", lock=True)
        if station.ruolo != "BATCH" or not kind.attivo or not recipe.attiva or not recipe.articolo.attivo:
            raise ValidationError("Postazione, ricetta o processo non validi per i batch.")
        recipe_mass(recipe)
        if recipe.articolo.unita_misura != "KG":
            raise ValidationError("Il prodotto della ricetta aziendale deve essere gestito in KG.")
        if kind.fase_operativa == "ROBOQBO":
            require_control(kind, "BATCH", "ESITO")
            principal(kind, "RBQB")
        elif kind.fase_operativa != "SEMILAVORATO":
            raise ValidationError("Fase batch non configurata.")
        if not principal(kind).accetta_articolo(recipe.articolo):
            raise ValidationError("Articolo della ricetta incompatibile con l'output del processo.")
        with azienda_write():
            cycle = CicloProduzione.objects.create(articolo=recipe.articolo, creato_da=actor)
            plan = PianoProduzione.objects.create(postazione=station, ricetta=recipe, ciclo=cycle, numero_batch=number, creato_da=actor)
            for i in range(number):
                work = Lavorazione.objects.create(ciclo_produzione=cycle, tipo_lavorazione=kind, ricetta=recipe)
                BatchPiano.objects.create(piano=plan, lavorazione=work, numero=i + 1)
        return plan

    @staticmethod
    def remaining_batches(plan):
        return plan.batch.exclude(lavorazione__stato__in=["ANNULLATA", "INTERROTTA"]).filter(lavorazione__inputs__isnull=True).count()

    @staticmethod
    def forecast(*, actor, piano, ubicazioni=None):
        require_permission(actor, "can_plan_own_batches")
        plan = get_record(PianoProduzione, piano, "Piano")
        remaining = PickingPlanService.remaining_batches(plan)
        if not remaining:
            raise ValidationError("Nessun batch ancora da prelevare.")
        rows, selections, groups = [], [], defaultdict(list)
        for row in plan.ricetta.righe.select_related("articolo"):
            groups[row.articolo_id].append(row)
        for article, recipe_rows in groups.items():
            total = sum(row.quantita for row in recipe_rows) * remaining
            proposal = StockProposalService.propose(actor=actor, articolo=article, quantita=total, ubicazioni=ubicazioni)
            pool = [[line, line.quantita] for line in proposal.righe]
            for row in recipe_rows:
                needed = row.quantita * remaining
                missing = needed
                for entry in pool:
                    line, available = entry
                    chosen = min(available, missing)
                    if chosen:
                        selections.append(InputSelection(line.lotto_id, chosen, [Allocation(line.posizione, chosen)], riga_ricetta=row.pk))
                        entry[1] -= chosen
                        missing -= chosen
                rows.append({"riga_id": row.pk, "teorica": needed, "mancante": missing})
        return RecipeInputProposal(tuple(selections), tuple(rows))

    @staticmethod
    @business_atomic
    def confirm(*, actor, piano, selections, motivo):
        require_permission(actor, "can_plan_own_batches")
        plan = get_record(PianoProduzione, piano, "Piano", lock=True)
        active_shift(actor, plan.postazione)
        if not isinstance(motivo, str) or not motivo.strip():
            raise ValidationError("Specificare il motivo della conferma o revisione del piano.")
        selections = tuple(selections)
        remaining = PickingPlanService.remaining_batches(plan)
        if not remaining or not selections or any(not isinstance(s, InputSelection) or s.riga_ricetta is None for s in selections):
            raise ValidationError("Piano di prelievo non valido.")
        rows = {r.pk: r for r in plan.ricetta.righe.all()}
        totals, physical = defaultdict(Decimal), defaultdict(Decimal)
        from magazzino.models import Lotto
        for s in selections:
            lot = get_record(Lotto, s.lotto, "Lotto")
            if s.riga_ricetta not in rows or not rows[s.riga_ricetta].accetta_articolo(lot.articolo):
                raise ValidationError("Lotto o riga estranei alla ricetta.")
            totals[s.riga_ricetta] += s.quantita
            for allocation in s.origini:
                key = (lot.pk, allocation.posizione)
                physical[key] += allocation.quantita
        if dict(totals) != {pk: row.quantita * remaining for pk, row in rows.items()}:
            raise ValidationError("La revisione deve coprire esattamente il fabbisogno dei batch ancora da prelevare.")
        for (lot_id, pos), total in physical.items():
            stock = Giacenza.objects.filter(lotto_id=lot_id, **pos.stock_lookup()).first()
            blocked = blocked_quantity(quarantine_balances(lotto=lot_id), lotto_id=lot_id, **pos.stock_lookup())
            if not stock or not stock.ubicazione.attiva or stock.quantita - blocked < total:
                raise ValidationError("Disponibilità insufficiente per confermare il piano; nessuna prenotazione effettuata.")
        number = (plan.revisioni.aggregate(last=Max("numero"))["last"] or 0) + 1
        with azienda_write():
            revision = RevisionePrelievo.objects.create(piano=plan, numero=number, motivo=motivo.strip(), confermata_da=actor)
            for s in selections:
                for allocation in s.origini:
                    pos = allocation.posizione
                    RigaPianoPrelievo.objects.create(revisione=revision, riga_ricetta_id=s.riga_ricetta, lotto_id=s.lotto,
                        ubicazione_id=pos.ubicazione_id, scaffale=pos.scaffale, piano=pos.piano, quantita=allocation.quantita)
        return revision

    @staticmethod
    def batch_proposal(*, actor, batch):
        require_permission(actor, "can_record_production_consumption")
        batch = get_record(BatchPiano, batch, "Batch")
        if batch.lavorazione.inputs.exists():
            raise ValidationError("Il batch ha già consumi registrati.")
        revision = batch.piano.revisioni.order_by("-numero").first()
        if not revision:
            raise ValidationError("Confermare il piano complessivo prima dei prelievi.")
        needs = {r.pk: r.quantita for r in batch.piano.ricetta.righe.all()}
        chosen = []
        for row in revision.righe.order_by("pk"):
            consumed = row.prelievi.aggregate(total=Sum("input__quantita"))["total"] or Decimal(0)
            amount = min(row.quantita - consumed, needs[row.riga_ricetta_id])
            if amount > 0:
                chosen.append((row, InputSelection(row.lotto_id, amount,
                    [Allocation(Position(row.ubicazione_id, row.scaffale, row.piano), amount)], riga_ricetta=row.riga_ricetta_id)))
                needs[row.riga_ricetta_id] -= amount
        if any(needs.values()):
            raise ValidationError("Piano residuo insufficiente: effettuare una revisione esplicita.")
        return revision, tuple(chosen)

    @staticmethod
    @business_atomic
    def consume_batch(*, actor, batch, revisione):
        batch = get_record(BatchPiano, batch, "Batch")
        active_shift(actor, batch.piano.postazione)
        revision, chosen = PickingPlanService.batch_proposal(actor=actor, batch=batch)
        from magazzino.services.types import persisted_id
        if revision.pk != persisted_id(revisione, "Revisione"):
            raise ValidationError("Il piano è stato revisionato: rileggere e confermare la proposta aggiornata.")
        with azienda_write(batch.lavorazione_id):
            results = RecipeInputService.confirm(actor=actor, lavorazione=batch.lavorazione, selections=[s for _, s in chosen])
            for (row, _), result in zip(chosen, results):
                PrelievoDaPiano.objects.create(riga_piano=row, input=result.registrazione)
        return results
