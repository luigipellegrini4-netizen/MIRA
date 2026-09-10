"""Collaudo su MySQL: nessun dato viene creato nel database operativo."""
from datetime import date
from decimal import Decimal
from django.core.exceptions import ValidationError, PermissionDenied
from django.test import TestCase
from anagrafiche.models import Articolo
from magazzino.models import Giacenza, Movimento
from magazzino.services import Allocation, Position, ReceivingService, MovementService
from produzione.models import Lavorazione, CodiceProduzione, RiepilogoInvasettamento
from produzione.services import WorkExecutionService
from produzione.services.demo_seed import seed_demo
from produzione.services.azienda_configuration import configure_lines
from produzione.services.azienda_planning import ShiftService, PickingPlanService
from produzione.services.azienda_execution import BatchService, TankService, FillingService
from produzione.services.azienda_common import NumberingService
from produzione.services.materials import InputSelection
from qualita.services import QualityService


class AziendaFixture:
    @classmethod
    def setUpTestData(cls):
        cls.d = seed_demo()
        cls.jars = Articolo.objects.create(codice="AZ_TEST_VASI", descrizione="Vasetti", categoria=cls.d["categories"]["MOCA"], unita_misura="PZ")
        cls.caps = Articolo.objects.create(codice="AZ_TEST_CAPS", descrizione="Capsule", categoria=cls.d["categories"]["MOCA"], unita_misura="PZ")
        cls.c = configure_lines(categoria_output=cls.d["categories"]["SL"], articolo_vasetti=cls.jars, articolo_capsule=cls.caps)
        cls.pack_lots = {}
        for key, article in (("vasetti", cls.jars), ("capsule", cls.caps)):
            cls.pack_lots[key] = ReceivingService.receive(actor=cls.d["users"]["magazziniere"], articolo=article,
                fornitore=cls.d["supplier"], codice_lotto="AZ_TEST_" + key, quantita_ricevuta="1000",
                destinazioni=[Allocation(Position(cls.d["locations"]["MAG"].pk), "1000")]).lotto

    def setUp(self):
        self.op = self.d["users"]["operatore"]
        self.filler = self.d["users"]["multi"]
        self.recipe = self.d["recipe"]
        self.mag = Position(self.d["locations"]["MAG"].pk)
        self.buffer = Position(self.d["locations"]["BUFFER_PRODUZIONE"].pk)
        self.shift = ShiftService.start(actor=self.op, postazione=self.c["postazioni"]["roboqbo"])
        self.fill_shift = ShiftService.start(actor=self.filler, postazione=self.c["postazioni"]["invasettamento"])

    def plan(self, n=1):
        plan = PickingPlanService.create(actor=self.op, postazione=self.shift.postazione, ricetta=self.recipe, numero_batch=n)
        proposal = PickingPlanService.forecast(actor=self.op, piano=plan, ubicazioni=[self.mag.ubicazione_id])
        revision = PickingPlanService.confirm(actor=self.op, piano=plan, selections=proposal.selections, motivo="Conferma operatore")
        return plan, revision

    def finish_batch(self, batch, revision):
        BatchService.start(actor=self.op, batch=batch)
        PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=revision)
        QualityService.record(actor=self.op, lavorazione=batch.lavorazione, controllo_richiesto=self.c["controlli"]["BATCH"], valore="C")
        return BatchService.finish(actor=self.op, batch=batch, quantita="10", destinazioni=[Allocation(self.buffer, "10")])

    def make_tank(self, ready=True):
        plan, revision = self.plan()
        output = self.finish_batch(plan.batch.get(), revision)
        tank = TankService.form(actor=self.op, postazione=self.shift.postazione, ricetta=self.recipe,
            selections=[InputSelection(output.lotto, "10", [Allocation(self.buffer, "10")], requisito_input=self.c["input"]["batch"])],
            quantita="10", destinazioni=[Allocation(self.buffer, "10")])
        if ready:
            self.measure(tank, "BRIX", "42")
            self.measure(tank, "PH", "4.1")
            tank.refresh_from_db()
        return tank

    def measure(self, tank, function, value):
        return QualityService.record(actor=self.d["users"]["qualita"], lavorazione=tank.lavorazione,
            controllo_richiesto=self.c["controlli"][function], valore=value)

    def open_filling(self, tank, qty="10", hygiene=True):
        if hygiene:
            ShiftService.confirm_hygiene(actor=self.filler, turno=self.fill_shift, confermato=True)
        return FillingService.open(actor=self.filler, postazione=self.fill_shift.postazione, ricetta=self.recipe,
            selections=[InputSelection(tank.lotto, qty, [Allocation(self.buffer, qty)], requisito_input=self.c["input"]["tank"])],
            articolo_vasetti=self.jars, articolo_capsule=self.caps,
            requisito_vasetti=self.c["input"]["vasetti"], requisito_capsule=self.c["input"]["capsule"])

    def treated_cart(self, session):
        cart = FillingService.add_cart(actor=self.filler, sessione=session)
        for phase in ("PASTORIZZAZIONE", "VUOTO"):
            FillingService.treat_cart(actor=self.filler, carrello=cart, fase=phase, esito="C")
        return cart

    def close(self, session, good=90, rejected=5, bad_caps=2):
        args = dict(actor=self.filler, sessione=session, vasetti_buoni=good, vasetti_scarti=rejected,
                    capsule_difettose=bad_caps, peso_netto_g="100")
        _, selections, _ = FillingService.packaging_forecast(**args, ubicazioni=[self.mag.ubicazione_id])
        destinations = [Allocation(self.mag, Decimal(good) / 10)] if good else []
        return FillingService.close(**args, selections=selections, destinazioni=destinations)


class AziendaFlowTests(AziendaFixture, TestCase):
    def test_forecast_and_confirmation_do_not_move_or_reserve(self):
        before = Movimento.objects.count()
        stocks = list(Giacenza.objects.order_by("pk").values_list("pk", "quantita"))
        plan, revision = self.plan(3)
        self.assertEqual(Movimento.objects.count(), before)
        self.assertEqual(list(Giacenza.objects.order_by("pk").values_list("pk", "quantita")), stocks)
        self.assertEqual(plan.batch.count(), 3)
        self.assertEqual(sum(revision.righe.values_list("quantita", flat=True)), Decimal("30.15"))

    def test_confirmed_lot_order_is_preserved_across_batches(self):
        plan = PickingPlanService.create(actor=self.op, postazione=self.shift.postazione, ricetta=self.recipe, numero_batch=3)
        fruit = self.recipe.righe.get(articolo=self.d["articles"]["FRAGOLE"])
        acid = self.recipe.righe.get(articolo=self.d["articles"]["ACIDO"])
        selections = [InputSelection(self.d["lots"][lot], qty, [Allocation(self.mag, qty)], riga_ricetta=row)
            for lot, qty, row in (("F_A", "15", fruit), ("F_B", "15", fruit), ("A_A", ".15", acid))]
        revision = PickingPlanService.confirm(actor=self.op, piano=plan, selections=selections, motivo="Percorso concordato")
        actual = []
        for batch in plan.batch.order_by("numero"):
            self.finish_batch(batch, revision)
            actual.append(list(batch.lavorazione.inputs.filter(riga_ricetta=fruit).values_list("lotto_id", "quantita")))
        a, b = self.d["lots"]["F_A"].pk, self.d["lots"]["F_B"].pk
        self.assertEqual(actual, [[(a, Decimal(10))], [(a, Decimal(5)), (b, Decimal(5))], [(b, Decimal(10))]])

    def test_stale_revision_is_rejected_without_consumption(self):
        plan, old = self.plan()
        proposal = PickingPlanService.forecast(actor=self.op, piano=plan, ubicazioni=[self.mag.ubicazione_id])
        new = PickingPlanService.confirm(actor=self.op, piano=plan, selections=proposal.selections, motivo="Revisione esplicita")
        batch = plan.batch.get()
        BatchService.start(actor=self.op, batch=batch)
        with self.assertRaises(ValidationError):
            PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=old)
        self.assertFalse(batch.lavorazione.inputs.exists())
        PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=new)
        with self.assertRaises(ValidationError):
            PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=new)

    def test_generic_execution_and_rescheduling_cannot_bypass_plan(self):
        plan, _ = self.plan()
        work = plan.batch.get().lavorazione
        with self.assertRaises(ValidationError):
            WorkExecutionService.start(actor=self.op, lavorazione=work)
        with self.assertRaises(ValidationError):
            WorkExecutionService.reschedule(actor=self.d["users"]["produzione"], lavorazione=work, ricetta=self.recipe)
        self.assertTrue(self.op.has_perm("auth.can_plan_own_batches"))
        self.assertFalse(self.op.has_perm("auth.can_plan_production"))

    def test_batch_missing_control_rolls_back_output(self):
        plan, revision = self.plan()
        batch = plan.batch.get()
        BatchService.start(actor=self.op, batch=batch)
        PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=revision)
        before = CodiceProduzione.objects.count()
        with self.assertRaises(ValidationError):
            BatchService.finish(actor=self.op, batch=batch, quantita="10", destinazioni=[Allocation(self.buffer, "10")])
        self.assertFalse(batch.lavorazione.outputs.exists())
        self.assertEqual(CodiceProduzione.objects.count(), before)

    def test_station_cannot_run_two_batches_at_the_same_time(self):
        plan, revision = self.plan(2)
        first, second = plan.batch.order_by("numero")
        BatchService.start(actor=self.op, batch=first)
        with self.assertRaises(ValidationError):
            BatchService.start(actor=self.op, batch=second)
        second.lavorazione.refresh_from_db()
        self.assertEqual(second.lavorazione.stato, "PIANIFICATA")

    def test_roboqbo_without_weighing_uses_recipe_nominal_quantity(self):
        plan, revision = self.plan()
        batch = plan.batch.get()
        BatchService.start(actor=self.op, batch=batch)
        PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=revision)
        QualityService.record(actor=self.op, lavorazione=batch.lavorazione, controllo_richiesto=self.c["controlli"]["BATCH"], valore="C")
        output = BatchService.finish(actor=self.op, batch=batch, destinazioni=[Allocation(self.buffer, "10.05")])
        self.assertEqual(output.registrazione.quantita, Decimal("10.05"))

    def test_semilavorato_real_output_can_differ_from_ingredients(self):
        ShiftService.end(actor=self.op, turno=self.shift)
        self.shift = ShiftService.start(actor=self.op, postazione=self.c["postazioni"]["semilavorati"])
        plan, revision = self.plan()
        batch = plan.batch.get()
        BatchService.start(actor=self.op, batch=batch)
        PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=revision)
        output = BatchService.finish(actor=self.op, batch=batch, quantita="10", destinazioni=[Allocation(self.buffer, "10")])
        self.assertEqual(output.registrazione.quantita, Decimal("10"))
        batch.lavorazione.refresh_from_db()
        self.assertEqual(batch.lavorazione.stato, "COMPLETATA")

    def test_tank_is_released_automatically_after_both_measurements_by_quality_role(self):
        tank = self.make_tank(False)
        self.measure(tank, "BRIX", "42")
        tank.refresh_from_db()
        self.assertIsNone(tank.pronto_il)
        self.measure(tank, "PH", "4.1")
        tank.refresh_from_db()
        self.assertIsNotNone(tank.pronto_il)
        self.assertEqual(tank.lavorazione.stato, "COMPLETATA")

    def test_brix_boundary_blocks_tank_even_after_later_good_reading(self):
        tank = self.make_tank(False)
        self.measure(tank, "BRIX", "40")
        self.measure(tank, "PH", "4.1")
        self.measure(tank, "BRIX", "42")
        tank.refresh_from_db()
        self.assertIsNone(tank.pronto_il)
        with self.assertRaises(ValidationError):
            self.open_filling(tank)

    def test_hygiene_is_required_and_is_not_inherited_by_next_shift(self):
        tank = self.make_tank()
        with self.assertRaises(ValidationError):
            self.open_filling(tank, hygiene=False)
        ShiftService.confirm_hygiene(actor=self.filler, turno=self.fill_shift, confermato=True)
        ShiftService.end(actor=self.filler, turno=self.fill_shift)
        self.fill_shift = ShiftService.start(actor=self.filler, postazione=self.fill_shift.postazione)
        with self.assertRaises(ValidationError):
            self.open_filling(tank, hygiene=False)

    def test_cart_identity_final_lot_and_closure_totals(self):
        session = self.open_filling(self.make_tank())
        carts = [self.treated_cart(session), self.treated_cart(session)]
        self.assertNotEqual(carts[0].unita.codice, carts[1].unita.codice)
        self.assertTrue(all(c.unita.codice.startswith("CRL") and c.unita.lotto_id == session.lotto_id for c in carts))
        summary = self.close(session)
        self.assertEqual(summary.massa_teorica_kg, Decimal("10.05"))
        self.assertEqual(summary.massa_reale_kg, Decimal("9.5"))
        self.assertEqual(summary.massa_buona_kg, Decimal("9"))
        self.assertEqual(summary.resa_percentuale, Decimal("94.527363"))
        self.assertEqual(session.lavorazione.outputs.get().quantita, Decimal("9"))
        self.assertEqual(session.lavorazione.outputs.get().lotto.articolo_id, self.recipe.articolo_id)
        for key, amount in (("vasetti", 95), ("capsule", 97)):
            self.assertEqual(session.lavorazione.inputs.get(requisito_input=self.c["input"][key]).quantita, amount)
        with self.assertRaises(ValidationError):
            self.close(session)

    def test_treatments_are_ordered_and_na_blocks_closure(self):
        session = self.open_filling(self.make_tank())
        cart = FillingService.add_cart(actor=self.filler, sessione=session)
        with self.assertRaises(ValidationError):
            FillingService.treat_cart(actor=self.filler, carrello=cart, fase="VUOTO", esito="C")
        self.assertFalse(cart.trattamenti.exists())
        treatment = FillingService.treat_cart(actor=self.filler, carrello=cart, fase="PASTORIZZAZIONE", esito="NA")
        self.assertEqual(treatment.lavorazione.controlli_qualita.get().esito, "NA")
        self.assertFalse(treatment.lavorazione.controlli_qualita.get().conforme)
        with self.assertRaises(ValidationError):
            self.close(session)
        self.assertFalse(RiepilogoInvasettamento.objects.exists())

    def test_partial_tank_sessions_do_not_double_theoretical_mass(self):
        tank = self.make_tank()
        first = self.open_filling(tank, "5")
        self.treated_cart(first)
        one = self.close(first, good=45, rejected=0, bad_caps=0)
        second = self.open_filling(tank, "5")
        self.treated_cart(second)
        two = self.close(second, good=45, rejected=0, bad_caps=0)
        self.assertEqual(one.massa_teorica_kg + two.massa_teorica_kg, Decimal("10.05"))
        self.assertEqual(second.lotto.codice_lotto, first.lotto.codice_lotto + "A")

    def test_all_rejected_closes_without_usable_output(self):
        session = self.open_filling(self.make_tank())
        cart = self.treated_cart(session)
        summary = self.close(session, good=0, rejected=95, bad_caps=0)
        self.assertEqual(summary.massa_reale_kg, Decimal("9.5"))
        self.assertFalse(session.lavorazione.outputs.exists())
        cart.unita.refresh_from_db()
        self.assertEqual(cart.unita.stato, "CHIUSA")
        session.refresh_from_db()
        self.assertIsNotNone(session.chiusa_il)

    def test_insufficient_caps_roll_back_jars_summary_output_and_closure(self):
        session = self.open_filling(self.make_tank())
        cart = self.treated_cart(session)
        args = dict(actor=self.filler, sessione=session, vasetti_buoni=90, vasetti_scarti=5,
                    capsule_difettose=2, peso_netto_g="100")
        _, selections, _ = FillingService.packaging_forecast(**args, ubicazioni=[self.mag.ubicazione_id])
        MovementService.register(actor=self.d["users"]["magazzino"], lotto=self.pack_lots["capsule"],
            tipo="RETTIFICA", quantita="1000", origine=self.mag, note="Disponibilità cambiata dopo la proposta")
        before = Movimento.objects.count()
        with self.assertRaises(ValidationError):
            FillingService.close(**args, selections=selections, destinazioni=[Allocation(self.mag, "9")])
        self.assertEqual(Movimento.objects.count(), before)
        self.assertEqual(Giacenza.objects.get(lotto=self.pack_lots["vasetti"], **self.mag.stock_lookup()).quantita, 1000)
        self.assertFalse(session.lavorazione.inputs.filter(requisito_input=self.c["input"]["vasetti"]).exists())
        self.assertFalse(session.lavorazione.outputs.exists())
        self.assertFalse(RiepilogoInvasettamento.objects.filter(sessione=session).exists())
        cart.unita.refresh_from_db()
        session.refresh_from_db()
        self.assertEqual(cart.unita.stato, "ATTIVA")
        self.assertIsNone(session.chiusa_il)
        MovementService.register(actor=self.d["users"]["magazzino"], lotto=self.pack_lots["capsule"],
            tipo="RETTIFICA", quantita="1000", destinazione=self.mag, note="Ripristino disponibilità per ripetere il collaudo")
        self.close(session)

    def test_missing_planned_lot_does_not_silently_switch(self):
        plan, revision = self.plan()
        batch = plan.batch.get()
        BatchService.start(actor=self.op, batch=batch)
        MovementService.register(actor=self.d["users"]["magazzino"], lotto=self.d["lots"]["F_A"],
            tipo="RETTIFICA", quantita="40", origine=self.mag, note="Disponibilità cambiata")
        with self.assertRaises(ValidationError):
            PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=revision)
        self.assertFalse(batch.lavorazione.inputs.exists())
        proposal = PickingPlanService.forecast(actor=self.op, piano=plan, ubicazioni=[self.mag.ubicazione_id])
        updated = PickingPlanService.confirm(actor=self.op, piano=plan, selections=proposal.selections, motivo="Lotto iniziale non disponibile")
        PickingPlanService.consume_batch(actor=self.op, batch=batch, revisione=updated)
        self.assertTrue(batch.lavorazione.inputs.filter(lotto=self.d["lots"]["F_B"]).exists())

    def test_direct_consumption_of_unready_tank_is_forbidden(self):
        tank = self.make_tank(False)
        with self.assertRaises(ValidationError):
            MovementService.register(actor=self.op, lotto=tank.lotto, tipo="CONSUMO", quantita="1", origine=self.buffer)

    def test_configuration_is_idempotent_and_does_not_overwrite(self):
        again = configure_lines(categoria_output=self.d["categories"]["SL"], articolo_vasetti=self.jars, articolo_capsule=self.caps)
        self.assertEqual(again["postazioni"]["roboqbo"].pk, self.shift.postazione_id)
        with self.assertRaises(ValidationError):
            configure_lines(categoria_output=self.d["categories"]["SL"], articolo_vasetti=self.caps, articolo_capsule=self.jars)

    def test_open_session_prevents_shift_end_and_active_line_deactivation(self):
        self.open_filling(self.make_tank())
        with self.assertRaises(ValidationError):
            ShiftService.end(actor=self.filler, turno=self.fill_shift)
        line = self.fill_shift.postazione.linea
        line.attiva = False
        with self.assertRaises(ValidationError):
            line.save()

    def test_numbering_scoped_by_article_day_and_family(self):
        article, day = self.recipe.articolo, date(2026, 9, 7)
        codes = [NumberingService.next(articolo=article, famiglia=f, giorno=day) for f in ("RBQB", "TNK", "CRL", "RBQB", "FINALE", "FINALE")]
        self.assertEqual(codes, ["RbQb260907001", "TNK260907001", "CRL260907001", "RbQb260907002", "260907", "260907A"])
        self.assertEqual(NumberingService.next(articolo=self.jars, famiglia="RBQB", giorno=day), "RbQb260907001")
        self.assertEqual(NumberingService.next(articolo=article, famiglia="RBQB", giorno=date(2026, 9, 8)), "RbQb260908001")
