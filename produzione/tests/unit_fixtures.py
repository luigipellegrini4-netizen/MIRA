from magazzino.tests.service_fixtures import setup_inventory
from produzione.models import TipoLavorazione, RequisitoOutputTipoLavorazione, RequisitoFaseUnitaTipoLavorazione, RisorsaProduttiva
from produzione.services import ProductionCycleService, WorkExecutionService, OutputService
from qualita.models import ParametroControllo, ControlloRichiestoTipoLavorazione


def setup_units(case):
    setup_inventory(case)
    case.origin_kind = TipoLavorazione.objects.create(codice="INV_UNIT", nome="Origine unità")
    case.heat_kind = TipoLavorazione.objects.create(codice="HEAT_UNIT", nome="Trattamento 1", genera_lotto=False)
    case.cool_kind = TipoLavorazione.objects.create(codice="COOL_UNIT", nome="Trattamento 2", genera_lotto=False)
    case.output_req = RequisitoOutputTipoLavorazione.objects.create(tipo_lavorazione=case.origin_kind, articolo=case.article, nome="Prodotto", prefisso_lotto="INV")
    parameter = ParametroControllo.objects.create(codice="VAC_UNIT", nome="Verifica vuoto", tipo_dato="BOOLEANO")
    case.quality_req = ControlloRichiestoTipoLavorazione.objects.create(tipo_lavorazione=case.cool_kind, parametro_controllo=parameter, valore_booleano_atteso=True)
    case.heat_route = RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=case.origin_kind, tipo_fase=case.heat_kind, ordine=10)
    case.cool_route = RequisitoFaseUnitaTipoLavorazione.objects.create(tipo_lavorazione=case.origin_kind, tipo_fase=case.cool_kind, ordine=20)
    case.cart = RisorsaProduttiva.objects.create(codice="CART1", nome="Carrello 1", tipo="CARRELLO")
    case.machine = RisorsaProduttiva.objects.create(codice="MACHINE1", nome="Macchina", tipo="MACCHINA")
    case.cycle = ProductionCycleService.create(actor=case.production, articolo=case.article)
    case.origin = WorkExecutionService.plan(actor=case.production, ciclo=case.cycle, tipo_lavorazione=case.origin_kind)
    case.heat = WorkExecutionService.plan(actor=case.production, ciclo=case.cycle, tipo_lavorazione=case.heat_kind)
    case.cool = WorkExecutionService.plan(actor=case.production, ciclo=case.cycle, tipo_lavorazione=case.cool_kind)
    case.origin = WorkExecutionService.start(actor=case.operator, lavorazione=case.origin)
    case.inv_lot = OutputService.prepare_lot(actor=case.operator, lavorazione=case.origin, requisito_output=case.output_req, articolo=case.article)
