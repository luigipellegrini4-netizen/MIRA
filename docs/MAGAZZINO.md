# Servizi di magazzino — fase 3

## Stato della verifica

- Fase 2: l'utente ha verificato 77 test su MySQL 8.4 dopo il recupero della migration.
- Fase 3: 43 test senza database passati; controllo e suite MySQL (134 test predisposti)
  successivamente confermati OK dall'utente.
- Nessuna variazione di schema nella fase 3: `makemigrations --check --dry-run` non rileva cambiamenti.

## Contratti

`Position(ubicazione_id, scaffale='', piano='')` normalizza scaffale e piano
con strip/uppercase. Gli ID devono identificare record già salvati.
`Allocation(posizione, quantita)` rappresenta una quota ricevuta in una posizione.
Le quantità accettano `Decimal`, interi o stringhe, non float: precisione 18, scala 6,
nessun arrotondamento implicito, quantità finita e strettamente positiva.

### Movimento

```python
from magazzino.services import MovementService, Position

movimento = MovementService.register(
    actor=utente,
    lotto=lotto,                  # istanza salvata oppure ID
    tipo="TRASFERIMENTO",
    quantita="2.500000",
    origine=Position(ubicazione_a.pk, "A", "1"),
    destinazione=Position(ubicazione_b.pk),
    note="Prelievo per lavorazione",
)
```

Tipi esposti nella fase 3:

| Tipo | Origine | Destinazione | Permesso |
|---|---|---|---|
| CARICO | assente | presente | can_receive_goods |
| TRASFERIMENTO | presente | presente e distinta | can_transfer_stock |
| CONSUMO | presente | assente | can_record_production_consumption |
| RETTIFICA positiva | assente | presente | can_adjust_inventory |
| RETTIFICA negativa | presente | assente | can_adjust_inventory |

La rettifica richiede una motivazione non vuota. CARICO riguarda lotti di acquisto.
Un consumo di fase 3 non ha ancora la FK InputLavorazione, che arriverà in fase 5;
la registrazione produttiva userà poi InputService e le relative riconciliazioni.
PRODUZIONE e movimenti da NC verranno abilitati con i rispettivi servizi; VENDITA
rimane un tipo del modello senza workflow applicativo.

Il servizio controlla i permessi, acquisisce il lotto con `select_for_update`,
poi le ubicazioni in ordine di ID e le giacenze coinvolte. Il lock sul lotto
copre anche la giacenza che ancora non esiste. La disattivazione di un'ubicazione
acquisisce il medesimo lock sull'ubicazione.
Tutti i valori finali sono validati prima del primo salvataggio.
Movimento e giacenze vengono salvati nella stessa `transaction.atomic`.
Qualsiasi eccezione annulla l'intera operazione; le giacenze a zero restano presenti.

### Ricevimento

```python
from magazzino.services import Allocation, Position, ReceivingService

risultato = ReceivingService.receive(
    actor=utente_magazzino,
    articolo=articolo,
    fornitore=fornitore,
    codice_lotto="FORN-2026-001",
    quantita_ricevuta="10",
    destinazioni=[Allocation(Position(ubicazione_a.pk), "4"),
                  Allocation(Position(ubicazione_b.pk), "6")],
    numero_ddt="123",
)
# risultato.lotto, risultato.ricevimento, risultato.movimenti
```

Le allocazioni devono sommare esattamente la quantità ricevuta. La destinazione
fisica resta nei movimenti, non nel ricevimento. Le note dei movimenti includono
il numero interno del ricevimento; lo schema concordato non contiene una FK
ricevimento sul movimento.

Il lock sull'articolo serializza la ricerca/creazione dello stesso lotto;
tutte le destinazioni sono bloccate in ordine prima dei carichi.
Lo stesso articolo/fornitore/codice riusa il lotto ma crea un nuovo ricevimento.
Un errore su un qualsiasi carico annulla anche lotto nuovo e ricevimento.
Articoli e fornitori disattivati non sono ricevibili.
Date incompatibili con un lotto esistente sono rifiutate, senza sovrascriverlo.

Se `tracciabilita_lotto=False` e il codice non è fornito, LotGenerationService
genera un identificativo tecnico `TECH-…`. Per richiamarlo in un altro ricevimento
si passa il codice restituito. Se l'articolo è tracciato, il codice è obbligatorio.
Una seconda chiamata receive è un nuovo ricevimento intenzionale: non reinviare
automaticamente la richiesta dopo una risposta persa senza verificare lo storico.

### Proposta FEFO/FIFO

```python
from magazzino.selectors import StockProposalService

proposta = StockProposalService.propose(
    actor=utente,
    articolo=articolo,
    quantita="8",
    ubicazioni=[ubicazione_a.pk, ubicazione_b.pk],  # opzionale
)
proposta.as_dict()  # struttura serializzabile, Decimal resi come stringhe
```

- FEFO: scadenza crescente, scadenze assenti in fondo, poi primo ricevimento,
  ID lotto e ID giacenza.
- FIFO: primo ricevimento, poi ID lotto e giacenza. Senza ricevimenti si usa
  il primo movimento in ingresso; senza date si ordina in fondo.
- NESSUNO: ID lotto e ID giacenza.
- Solo stock positivo in ubicazioni attive; un elenco vuoto di ubicazioni
  propone zero righe, mentre `None` considera tutte le ubicazioni attive.
- Non ci sono prenotazioni o movimenti. `mancante` espone la quantità non coperta.
- L'operatore può consumare un lotto alternativo: la proposta non è vincolante.
- La proposta non è un controllo qualità né una verifica di utilizzabilità:
  ambiti di quarantena e decisioni NC saranno trattati nella fase qualità.

## Test su MySQL

Nel terminale PowerShell di VS Code, dalla cartella MIRA:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino
```

Tre test usano connessioni separate e transazioni reali:
due consumi concorrenti, due ricevimenti del medesimo lotto nuovo,
due carichi sulla medesima posizione inizialmente vuota.
Il test runner opera sul database separato `mira_test`.

## Limiti di questa fase

L'Admin delle anagrafiche e quello consultivo di magazzino restano disponibili.
I servizi sono invocabili da codice/shell Django; non sono state aggiunte pagine
operative. Ricette, produzione, qualità e workflow inventariali di conteggio
appartengono alle fasi successive. La fase 3 non ne simula il completamento.
