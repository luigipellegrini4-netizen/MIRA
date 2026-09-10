# Esecuzione produttiva — fase 6

## Stato della fase

Fase 5 verificata dall'utente su MySQL: 219 test passati.
La fase 6 aggiunge i servizi produttivi senza cambiare lo schema.
66 test senza database passati durante lo sviluppo; la suite estesa MySQL resta
da eseguire prima della fase 7.

Il completamento qui valida requisiti materiali e riconciliazione dello stock.
Controlli qualità obbligatori/non conformi e percorso delle unità verranno integrati
nelle fasi 7 e 8. Non è ancora un backend alimentare completo per uso operativo.

## Pianificazione e stati

- ProductionCycleService.create/reschedule/start/complete/cancel: permesso
  can_plan_production (RP). Non attribuisce pianificazione ad AMMINISTRATORE puro.
- WorkExecutionService.plan/reschedule/plan_batches: RP. Ogni batch è una distinta
  Lavorazione con i propri dati; plan_batches è atomico.
- WorkExecutionService.start/complete/interrupt: RP e OP.
- WorkExecutionService.cancel: can_cancel_unstarted_work (RP).

Avviare la prima lavorazione avvia anche il ciclo; l'OP non ha bisogno del
permesso di pianificazione per questo effetto interno.
L'avvio ripetuto viene rifiutato, senza cambiare l'orario originario.
Tipi e ricette disattivati non sono pianificabili o avviabili.

Un annullamento è possibile solo prima dell'inizio e senza materiale registrato.
L'annullamento del ciclo annulla le lavorazioni ancora pianificate, ma viene
rifiutato se una lavorazione è iniziata o ha materiale registrato.
L'interruzione richiede una motivazione e conserva i movimenti effettivamente
avvenuti: non reintegra automaticamente consumi reali.
Un ciclo si completa solo se ha almeno una lavorazione completata e tutte le
altre sono completate o annullate. Le interrotte impediscono la chiusura normale.

Le transizioni annotate riportano l'utente nelle note; eseguita_da identifica
l'utente che ha avviato la lavorazione. Le azioni Admin registrano anche LogEntry.

## Esempio dei servizi

Con anagrafiche, ricetta e requisiti già configurati:

```python
from magazzino.services import Allocation, Position
from produzione.services import (
    ProductionCycleService, WorkExecutionService, InputService, OutputService,
)

ciclo = ProductionCycleService.create(actor=responsabile, articolo=prodotto)
batch = WorkExecutionService.plan_batches(
    actor=responsabile, ciclo=ciclo, tipo_lavorazione=tipo,
    ricetta=ricetta, numero_batch=3,
)
lavorazione = WorkExecutionService.start(actor=operatore, lavorazione=batch[0])

consumo = InputService.register(
    actor=operatore, lavorazione=lavorazione, requisito_input=requisito_input,
    lotto=lotto_materia_prima, quantita="5",
    origini=[Allocation(Position(magazzino.pk, "A", "1"), "5")],
)
produzione = OutputService.register(
    actor=operatore, lavorazione=lavorazione, requisito_output=requisito_output,
    articolo=prodotto, quantita="4",
    destinazioni=[Allocation(Position(buffer.pk), "4")],
)
WorkExecutionService.complete(actor=operatore, lavorazione=lavorazione)
```

InputService usa can_record_production_consumption: anche magazzinieri e RM
possono registrare i prelievi produttivi consentiti. OutputService richiede
can_execute_production. I due servizi restituiscono registrazione, lotto e movimenti.
Le allocazioni possono suddividere la quantità su più posizioni e devono sommare
esattamente il totale dichiarato. Ogni errore annulla anche la registrazione input/output
e tutti i movimenti già eseguiti nella chiamata.

## Identità anticipata e codici lotto

```python
identita = OutputService.prepare_lot(
    actor=operatore, lavorazione=lavorazione,
    requisito_output=requisito_output, articolo=prodotto,
)
# Nessuna giacenza, nessun OutputLavorazione con quantità fittizia.

risultato = OutputService.register(
    actor=operatore, lavorazione=lavorazione,
    requisito_output=requisito_output, lotto=identita,
    quantita="123", destinazioni=[Allocation(Position(buffer.pk), "123")],
)
```

Ogni prepare_lot crea una nuova identità. Per riutilizzarla, conservare e passare
il lotto restituito; non ripetere prepare_lot come tentativo di riconnessione.
Un lotto già consolidato non può essere consolidato una seconda volta.
Lotto nuovo + output + movimenti sono atomici; quando il lotto era già preparato,
un errore di consolidamento conserva l'identità e annulla output/movimenti.

LotGenerationService centralizza tutti i codici:

- prefisso non vuoto: ad esempio INT260905, INT260905-A;
- prefisso vuoto: 260905, 260905-A, 260905-B;
- dopo Z si continua con AA, AB e così via;
- la data usata è data_produzione, predefinita alla data locale corrente;
- il lock sull'articolo impedisce duplicazioni concorrenti anche tra tipi e cicli
  diversi; il vincolo univoco MySQL resta la protezione finale.

MovementService ora ammette PRODUZIONE soltanto con un output compatibile,
lo stesso lotto e una lavorazione in corso. La somma dei movimenti non può
superare la quantità dichiarata nell'output.

## Completamento e concorrenza

CompletionValidator controlla:

1. presenza di tutti i requisiti input obbligatori;
2. presenza dei requisiti output obbligatori quando il tipo genera lotto;
3. almeno un output reale per le trasformazioni che generano lotto;
4. assenza di output artificiali per i trattamenti senza nuovo lotto;
5. compatibilità di tutte le registrazioni e uguaglianza esatta fra quantità
   input/output e somma dei rispettivi movimenti CONSUMO/PRODUZIONE.

La ricetta rimane teorica: differenze tra formula e impiego effettivo non vengono
nascoste o corrette automaticamente. Le quantità reali devono soddisfare i requisiti
configurati e risultare interamente riconciliate con lo stock.

Le operazioni acquisiscono i lock in ordine tipi → ricette → cicli → lavorazioni
→ lotti → ubicazioni → giacenze. InputService blocca anche le lavorazioni antenate
e ricontrolla il grafo: un input che chiuderebbe un ciclo genealogico viene rifiutato,
anche se due lavorazioni provano ad alimentarsi reciprocamente in parallelo.
Se pianificazione o grafo cambiano durante l'acquisizione, l'operazione fallisce
senza modifiche e può essere ripetuta rileggendo i dati.

Le nuove prove concorrenti usano connessioni MySQL separate per verificare:
codici lotto univoci, rifiuto di dipendenze cicliche e serializzazione fra
completamento della lavorazione e aggiunta di un input.

## Admin

In Produzione → Lavorazioni sono disponibili azioni per avviare, completare
o annullare una sola lavorazione selezionata. Ogni azione usa i servizi e i
permessi custom; l'OP non vede l'annullamento, l'amministratore puro non vede
azioni operative. La modifica diretta dei record rimane disabilitata.
Pianificazione e registrazione materiali sono per ora disponibili tramite i
servizi Python, senza una UI operativa completa.

## Verifica su MySQL

Non servono migration o nuovi permessi in questa fase. Nel terminale di VS Code:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione
```
