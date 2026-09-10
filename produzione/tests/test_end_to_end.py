import json
from datetime import date
from decimal import Decimal
from django.core.exceptions import ValidationError
from django.test import TestCase
from anagrafiche.models import Articolo
from magazzino.models import Giacenza, Movimento
from magazzino.services import Allocation, ReceivingService
from magazzino.selectors import StockProposalService
from magazzino.tests.service_fixtures import ServiceFixtures
from produzione.models import (TipoLavorazione, RequisitoInputTipoLavorazione,
    RequisitoOutputTipoLavorazione, RequisitoFaseUnitaTipoLavorazione, RisorsaProduttiva)
from produzione.services import (RecipeService, ProductionCycleService, WorkExecutionService,
    InputService, OutputService, ResourceService, WorkUnitService, GenealogyService)
from qualita.models import ParametroControllo, ControlloRichiestoTipoLavorazione
from qualita.services import QualityService, NonConformityService as NC


class ProcessEndToEndTests(ServiceFixtures, TestCase):
    def test_raw_materials_batches_tank_units_quality_nc_and_commercial_lot(self):
        self.article.criterio_rotazione = "FEFO"
        self.article.save()

        def article(code, unit):
            return Articolo.objects.create(codice=code, descrizione=code, categoria=self.category, unita_misura=unit)

        rb_article, tank_article = article("RB", "KG"), article("TNK", "KG")
        inv_article, final_article = article("INV", "PZ"), article("COMM", "PZ")
        caps = article("CAPS", "PZ")
        caps.tracciabilita_lotto = False
        caps.save()

        def receive(art, amount, **kwargs):
            return ReceivingService.receive(actor=self.warehouse, articolo=art, fornitore=self.supplier,
                quantita_ricevuta=amount, destinazioni=[Allocation(self.position, amount)], **kwargs).lotto

        early = receive(self.article, "5", codice_lotto="EARLY", data_scadenza=date(2030, 1, 1), numero_ddt="D1")
        late = receive(self.article, "5", codice_lotto="LATE", data_scadenza=date(2030, 2, 1), numero_ddt="D2")
        caps_lot = receive(caps, "80", numero_ddt="D3")
        self.assertTrue(caps_lot.codice_lotto.startswith("TECH-"))
        proposal = StockProposalService.propose(actor=self.operator, articolo=self.article, quantita="5")
        self.assertEqual(proposal.righe[0].lotto_id, early.pk)

        def kind(code, generates=True):
            return TipoLavorazione.objects.create(codice=code, nome=code, genera_lotto=generates)

        rb, tank, inv, label = [kind(c) for c in ("ROBOQBO_E2E", "TANK_E2E", "INV_E2E", "LABEL_E2E")]
        heat, cool = kind("HEAT_E2E", False), kind("COOL_E2E", False)

        def input_req(process, art, **kwargs):
            return RequisitoInputTipoLavorazione.objects.create(tipo_lavorazione=process, articolo=art, nome=art.codice, **kwargs)

        def output_req(process, art, prefix):
            return RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=process, articolo=art, nome=art.codice, prefisso_lotto=prefix)

        rb_in, rb_out = input_req(rb, self.article), output_req(rb, rb_article, "RBQB")
        tank_in = input_req(tank, rb_article, multiplo=True, tipo_lavorazione_origine=rb)
        tank_out = output_req(tank, tank_article, "TNK")
        inv_in, cap_in = input_req(inv, tank_article), input_req(inv, caps)
        inv_out = output_req(inv, inv_article, "INV")
        label_in, label_out = input_req(label, inv_article), output_req(label, final_article, "")
        temperature = ParametroControllo.objects.create(codice="TEMPERATURE_E2E", nome="Temperatura", tipo_dato="DECIMALE", unita_misura="C")
        vacuum = ParametroControllo.objects.create(codice="VACUUM_E2E", nome="Vuoto", tipo_dato="BOOLEANO")
        heat_control = ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=heat, parametro_controllo=temperature, valore_minimo=80, valore_massimo=90)
        cool_control = ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=cool, parametro_controllo=vacuum, valore_booleano_atteso=True)
        RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=inv, tipo_fase=heat, ordine=1)
        RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=inv, tipo_fase=cool, ordine=2)
        machine = RisorsaProduttiva.objects.create(codice="MACHINE_E2E", nome="Macchina", tipo="MACCHINA")
        carts = [RisorsaProduttiva.objects.create(codice=f"CART_E2E_{i}", nome=f"Carrello {i}", tipo="CARRELLO") for i in range(2)]
        recipe = RecipeService.create(actor=self.production, articolo=rb_article, nome="Formula", versione="1")
        RecipeService.add_line(actor=self.production, ricetta=recipe, articolo=self.article, quantita="5")
        self.assertEqual(RecipeService.requirements(actor=self.operator, ricetta=recipe, numero_batch=2)[0].quantita_totale, 10)
        cycle = ProductionCycleService.create(actor=self.production, articolo=final_article)

        def plan(process):
            return WorkExecutionService.plan(actor=self.production, ciclo=cycle, tipo_lavorazione=process)

        batches = WorkExecutionService.plan_batches(actor=self.production, ciclo=cycle, tipo_lavorazione=rb, ricetta=recipe, numero_batch=2)
        tank_work, inv_work, heat_work, cool_work, label_work = [plan(p) for p in (tank, inv, heat, cool, label)]

        def start(work):
            WorkExecutionService.start(actor=self.operator, lavorazione=work)

        def consume(work, req, lot, amount, position):
            InputService.register(actor=self.operator, lavorazione=work, requisito_input=req, lotto=lot,
                quantita=amount, origini=[Allocation(position, amount)])

        def produce(work, req, amount, **kwargs):
            return OutputService.register(actor=self.operator, lavorazione=work, requisito_output=req,
                quantita=amount, destinazioni=[Allocation(self.destination, amount)], **kwargs).lotto

        def complete(work):
            WorkExecutionService.complete(actor=self.operator, lavorazione=work)

        batch_lots = []
        # Conferma volontaria del lotto alternativo: FEFO è una proposta.
        for work, raw in zip(batches, (late, early)):
            start(work)
            ResourceService.assign(actor=self.operator, lavorazione=work, risorsa_produttiva=machine)
            consume(work, rb_in, raw, "5", self.position)
            batch_lots.append(produce(work, rb_out, "4", articolo=rb_article))
            complete(work)
        self.assertNotEqual(batch_lots[0].codice_lotto, batch_lots[1].codice_lotto)
        with self.assertRaises(ValidationError):
            RecipeService.add_line(actor=self.production, ricetta=recipe, articolo=self.article, quantita="1")

        start(tank_work)
        for lot in batch_lots:
            consume(tank_work, tank_in, lot, "4", self.destination)
        tank_lot = produce(tank_work, tank_out, "8", articolo=tank_article)
        complete(tank_work)
        start(inv_work)
        consume(inv_work, inv_in, tank_lot, "8", self.destination)
        consume(inv_work, cap_in, caps_lot, "80", self.position)
        inv_lot = OutputService.prepare_lot(actor=self.operator, lavorazione=inv_work, requisito_output=inv_out, articolo=inv_article)
        units = [WorkUnitService.create(actor=self.operator, lavorazione_origine=inv_work, lotto=inv_lot,
            risorsa_produttiva=cart, codice=f"U{i}", quantita="40") for i, cart in enumerate(carts)]
        self.assertFalse(Giacenza.objects.filter(lotto=inv_lot).exists())
        with self.assertRaises(ValidationError):
            complete(inv_work)
        material_count = Movimento.objects.count()

        start(heat_work)
        for unit in units:
            WorkUnitService.participate(actor=self.operator, unita_lavorazione=unit, lavorazione=heat_work)
        QualityService.record(actor=self.operator, lavorazione=heat_work, controllo_richiesto=heat_control, valore="85")
        complete(heat_work)
        start(cool_work)
        for unit in units:
            WorkUnitService.participate(actor=self.operator, unita_lavorazione=unit, lavorazione=cool_work)
        bad = QualityService.record(actor=self.operator, lavorazione=cool_work, controllo_richiesto=cool_control, valore=False)
        with self.assertRaises(ValidationError):
            complete(cool_work)
        quality_nc = NC.open(actor=self.operator, descrizione="Vuoto fuori criterio", controllo_qualita=bad)
        NC.take_charge(actor=self.quality, non_conformita=quality_nc)
        NC.action(actor=self.quality, non_conformita=quality_nc, tipo_azione="CORREZIONE_PROCESSO", descrizione="Regolazione e ricontrollo")
        good = QualityService.record(actor=self.quality, lavorazione=cool_work, controllo_richiesto=cool_control, valore=True)
        NC.verify(actor=self.quality, non_conformita=quality_nc, esito="EFFICACE", descrizione="Vuoto verificato", controllo_qualita=good)
        with self.assertRaises(ValidationError):
            complete(cool_work)
        NC.close(actor=self.quality, non_conformita=quality_nc, note="Correzione verificata e accettata")
        complete(cool_work)
        for unit in units:
            WorkUnitService.close(actor=self.operator, unita_lavorazione=unit)
        self.assertEqual(Movimento.objects.count(), material_count)
        produce(inv_work, inv_out, "80", lotto=inv_lot)
        complete(inv_work)
        start(label_work)
        consume(label_work, label_in, inv_lot, "80", self.destination)
        commercial = produce(label_work, label_out, "80", articolo=final_article)
        complete(label_work)
        self.assertEqual(ProductionCycleService.complete(actor=self.production, ciclo=cycle).stato, "COMPLETATO")

        stock_nc = NC.open(actor=self.warehouse, descrizione="Verifica confezioni", lotto=commercial)
        NC.take_charge(actor=self.quality, non_conformita=stock_nc)
        NC.action(actor=self.quality, non_conformita=stock_nc, tipo_azione="QUARANTENA", descrizione="Isolamento",
            quantita="10", origine=self.destination, destinazione=self.position)
        NC.action(actor=self.quality, non_conformita=stock_nc, tipo_azione="REINTEGRO", descrizione="Confezioni idonee",
            quantita="6", origine=self.position, destinazione=self.destination)
        NC.action(actor=self.quality, non_conformita=stock_nc, tipo_azione="SCARTO", descrizione="Confezioni non idonee",
            quantita="4", origine=self.position)
        NC.verify(actor=self.quality, non_conformita=stock_nc, esito="EFFICACE", descrizione="Selezione conclusa")
        NC.close(actor=self.quality, non_conformita=stock_nc, note="Materiale residuo verificato")
        self.assertEqual(sum(Giacenza.objects.filter(lotto=commercial).values_list("quantita", flat=True)), 76)
        for lot in (early, late, caps_lot, *batch_lots, tank_lot, inv_lot):
            self.assertEqual(sum(Giacenza.objects.filter(lotto=lot).values_list("quantita", flat=True)), 0)

        graph = GenealogyService.upstream(actor=self.quality, lotto=commercial)
        expected = {early.pk, late.pk, caps_lot.pk, *[l.pk for l in batch_lots], tank_lot.pk, inv_lot.pk, commercial.pk}
        self.assertEqual({l["id"] for l in graph["lotti"]}, expected)
        self.assertEqual(len(graph["unita"]), 2)
        self.assertEqual(len(graph["partecipazioni"]), 4)
        self.assertEqual(len(graph["controlli"]), 3)
        self.assertEqual({n["id"] for n in graph["non_conformita"]}, {quality_nc.pk, stock_nc.pk})
        self.assertTrue(all(n["stato"] == "CHIUSA" for n in graph["non_conformita"]))
        self.assertTrue(all(w["stato"] == "COMPLETATA" for w in graph["lavorazioni"]))
        self.assertEqual(len([w for w in graph["lavorazioni"] if w["ruolo"] == "TRATTAMENTO_UNITA"]), 2)
        self.assertFalse(graph["ciclo_materiale_rilevato"])
        self.assertFalse(graph["troncato"])
        self.assertTrue(json.dumps(graph, ensure_ascii=False))
        downstream = GenealogyService.downstream(actor=self.operator, lotto=early)
        self.assertIn(commercial.pk, {l["id"] for l in downstream["lotti"]})
        self.assertNotIn(late.pk, {l["id"] for l in downstream["lotti"]})
        self.assertEqual(next(c for c in graph["controlli"] if c["id"] == bad.pk)["conforme"], False)
