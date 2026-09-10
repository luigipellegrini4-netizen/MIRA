# Linee semilavorati e confetture: motore aziendale

Il flusso concordato è implementato nei servizi `ShiftService`, `PickingPlanService`,
`BatchService`, `TankService` e `FillingService`, importabili da `produzione.services`.
Le nuove configurazioni hanno il prefisso `AZ_`. I processi precedenti conservano
le proprie regole e la convenzione storica dei lotti.

Il motore e la consultazione nell'Admin sono stati collaudati dall'utente.
La UI per configurazione, turni, piano, batch, tank e sessioni è descritta in
[UI_LINEE_TURNI_BATCH.md](UI_LINEE_TURNI_BATCH.md). Il suo collaudo MySQL va eseguito
dopo questo aggiornamento. I comandi generici di avvio, consumo e chiusura non possono
aggirare le regole dei processi aziendali.

## Installazione e collaudo

Dal terminale PowerShell di VS Code, nella cartella che contiene `manage.py`:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_roles
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita interfaccia
```

Le nuove migrazioni sono `produzione.0005` e `qualita.0003`. Non creano ricette,
movimenti o produzioni e non rinumerano lotti già presenti. Il bootstrap ruoli
aggiunge a OP e RP la scelta del numero di batch del proprio turno; il permesso
generale di pianificazione resta separato e riservato a RP.

I test MySQL usano il database di test configurato da Django. Non eseguire il
collaudo con un database di test coincidente con quello operativo.

Stato del motore al 2026-09-08: suite di 495 test MySQL confermata funzionante
dall'utente. La successiva UI aggiunge altri test: lo stato del relativo collaudo
è riportato nel documento UI collegato sopra.

## Configurazione delle linee

Occorrono articoli esistenti e attivi per vasetti e capsule, entrambi in **PZ** e
distinti, e le categorie degli articoli prodotti. Le ricette di questo flusso
indicano ingredienti specifici in **KG** e prodotto in **KG**.

Il comando seguente mostra la sintassi: sostituire i quattro ID con quelli reali
letti nell'Admin prima di eseguirlo. Non crea gli articoli né le ricette.

```text
manage.py bootstrap_linee_aziendali --categoria-semilavorati ID_SL --categoria-confetture ID_CONF --vasetti ID_VASI --capsule ID_CAPS
```

Se si omette `--categoria-semilavorati`, viene usata la categoria di output anche
per i semilavorati. `--categoria-output` è un alias di `--categoria-confetture`.
Il comando crea due linee, tre postazioni, sei tipi di lavorazione, requisiti,
controlli e il percorso dei carrelli. Un secondo lancio con gli stessi dati è
idempotente; configurazioni già presenti ma diverse causano un errore e rollback,
senza sovrascrittura. Altri formati di confezione possono essere configurati
esplicitamente con requisiti dedicati; il comando iniziale configura una coppia.

L'Admin permette di configurare linee/postazioni e consultare piani, revisioni,
turni, tank, sessioni, carrelli e riepiloghi. Lo storico operativo non è modificabile.

## Sequenza dei servizi

I parametri che indicano record accettano l'oggetto salvato oppure il suo ID.
Le quantità accettano stringhe decimali o `Decimal`, mai `float`. Ogni allocazione
usa `Allocation(Position(id_ubicazione, scaffale, piano), quantita)`.
Per `InputSelection` specificare una sola origine teorica: `riga_ricetta` per gli
ingredienti, oppure `requisito_input` per batch, tank e confezioni.

### Turni

- `ShiftService.start(actor=operatore, postazione=...)`: registra l'inizio turno.
- `ShiftService.confirm_hygiene(actor=operatore, turno=..., confermato=True)`:
  registra la conferma di vasetti e capsule puliti e igienizzati nel turno di
  invasettamento. Senza conferma non si apre una sessione.
- `ShiftService.end(actor=operatore, turno=...)`: registra la fine. Le sessioni
  devono essere chiuse e batch/tank in corso completati o interrotti.

Un operatore e una postazione possono avere un solo turno attivo. RoboQbo e
invasettamento lavorano contemporaneamente con due operatori diversi. La conferma
di igienizzazione non viene ereditata dal turno successivo. Linea e risorsa della
postazione non possono essere disattivate con un turno aperto.

### Piano e singoli batch

1. `PickingPlanService.create(actor=..., postazione=..., ricetta=..., numero_batch=...)`
   crea piano e batch: numero intero positivo, massimo 1000 per piano.
2. `PickingPlanService.forecast(actor=..., piano=..., ubicazioni=[...])` restituisce
   una proposta aggregata secondo FIFO/FEFO configurato per ciascun articolo.
   Non prenota e non consuma materiale.
3. `PickingPlanService.confirm(actor=..., piano=..., selections=..., motivo=...)`
   conserva i lotti e le posizioni confermati, nell'ordine scelto. L'operatore può
   modificare le selezioni prima di confermare. Nessuna prenotazione.
4. `BatchService.start(actor=..., batch=...)` registra l'inizio del singolo batch.
5. `PickingPlanService.batch_proposal(actor=..., batch=...)` restituisce revisione
   e righe del prelievo del batch, calcolate dal residuo del piano confermato.
6. `PickingPlanService.consume_batch(actor=..., batch=..., revisione=...)` ricontrolla
   lo stock e registra tutti gli ingredienti del batch in una transazione.
7. Per RoboQbo, `QualityService.record` registra il controllo configurato con
   funzione `BATCH` ed esito `C`, `NC` o `NA`.
8. `BatchService.finish(actor=..., batch=..., destinazioni=..., quantita=...)`
   registra l'output e la fine ciclo, solo se i controlli sono soddisfatti.

Per RoboQbo si può omettere `quantita`: il motore usa automaticamente la somma
della ricetta come quantità contabile, senza chiedere una pesata del batch.
Le destinazioni devono sommare tale quantità. Per i semilavorati si può indicare
l'output reale, ad esempio 10 KG anche con ingredienti totali pari a 10,050 KG.

Esempio di ordine confermato: fragole A 15 KG, B 15 KG, tre batch da 10 KG.
Il primo preleva A 10; il secondo A 5 e B 5; il terzo B 10. Se A non è disponibile,
il prelievo fallisce: nessun passaggio silenzioso a B. Occorre confermare una
revisione esplicita per tutti i batch ancora da prelevare. I consumi già registrati
rimangono collegati alla loro revisione. Una richiesta con revisione superata è
rifiutata. Due richieste simultanee sullo stesso batch non devono duplicare i consumi.

### Formazione tank

`TankService.form(actor=..., postazione=..., ricetta=..., selections=...,
destinazioni=..., quantita=...)` crea una lavorazione per tank. Le selezioni
indicano batch completati della stessa linea e versione di ricetta. Omettendo
`quantita`, l'output contabile è la somma delle quantità selezionate.

Registrare con `QualityService.record` i valori decimali dei controlli con funzione
`BRIX` e `PH`. Il tank diventa automaticamente pronto e la lavorazione viene
completata solo dopo entrambe le misure conformi:

- **40 < °Brix < 45**: 40 e 45 sono esclusi.
- **pH <= 4,1**: 4,1 è incluso.

Un tank presente a magazzino ma non pronto non può alimentare l'invasettamento.
Una misura conforme successiva non cancella una precedente misura non conforme.

### Sessione di invasettamento e carrelli

`FillingService.open` riceve operatore, postazione, ricetta, selezioni dei tank
pronti, articoli vasetti/capsule e relativi requisiti. Crea subito l'identità del
lotto finale, senza un carico fittizio, e registra il consumo dei tank confermati.

- `add_tanks(actor=..., sessione=..., selections=...)` aggiunge altri tank pronti
  della stessa linea e ricetta mentre la sessione è aperta.
- `add_cart(actor=..., sessione=...)` crea un carrello con identificativo CRL e
  collega lo stesso lotto finale della sessione. Non richiede peso per carrello.
- `treat_cart(actor=..., carrello=..., fase="PASTORIZZAZIONE", esito="C")` registra
  il controllo **71 °C × 4 minuti**.
- `treat_cart(actor=..., carrello=..., fase="VUOTO", esito="C")` registra shock
  termico e presenza del vuoto. Richiede la fase precedente conforme.

Ogni trattamento conserva esito e operatore senza cambiare il lotto. NC e NA sono
distinti nello storico ma entrambi bloccano l'avanzamento; questo intervento non
aggiunge una procedura per risolverli. I carrelli sono tutti collegati all'insieme
dei tank consumati nella sessione: non si attribuisce un singolo tank a un carrello.

### Chiusura, confezioni e resa

`FillingService.packaging_forecast` propone lotti e posizioni per le confezioni;
`FillingService.close` riceve le selezioni confermate e le destinazioni del prodotto
buono. Entrambi ricevono `vasetti_buoni`, `vasetti_scarti`, `capsule_difettose` e
`peso_netto_g`.

```text
vasetti da prelevare = vasetti buoni + vasetti da scartare
capsule da prelevare = vasetti da prelevare + capsule difettose
massa reale KG = (vasetti buoni + vasetti da scartare) × peso netto g / 1000
massa buona KG = vasetti buoni × peso netto g / 1000
resa % = massa reale KG / massa teorica attribuita alla sessione × 100
```

La massa teorica deriva dalle ricette dei batch effettivamente entrati nei tank.
Quando una sessione consuma solo una frazione del tank, le viene attribuita quella
frazione della massa teorica: il conteggio non viene ripetuto integralmente nella
sessione successiva. Il numero pianificato di batch non entra nel denominatore.

I prelievi delle confezioni devono essere esatti, in pezzi interi e sugli articoli
previsti. Tutti i carrelli devono aver superato entrambi i trattamenti. Prelievo
vasetti, prelievo capsule, riepilogo, carico del prodotto buono, chiusura carrelli
e chiusura lavorazione sono atomici: qualsiasi errore annulla l'intero tentativo.

Gli scarti contribuiscono alla resa e sono conservati nel riepilogo; non vengono
caricati nello stock utilizzabile. Se tutti i vasetti sono scarti, la sessione
può chiudersi con riepilogo e confezioni consumate, senza output buono e senza
destinazioni. Non viene creata automaticamente una nuova NC o una giacenza scarti.

## Numerazione

| Identità | Primo codice dell'articolo il 7 settembre 2026 | Successivo |
| --- | --- | --- |
| Batch RoboQbo | RbQb260907001 | RbQb260907002 |
| Tank | TNK260907001 | TNK260907002 |
| Carrello | CRL260907001 | CRL260907002 |
| Lotto finale sessione | 260907 | 260907A, poi 260907B |

Progressivi distinti per **articolo, giorno e famiglia**. Lo stesso testo può quindi
esistere per due articoli diversi: l'identità va sempre letta insieme all'articolo.
Dopo Z, i lotti finali proseguono con AA. La data è quella locale di generazione
dell'identità; il lotto finale resta quello aperto con la sessione anche se questa
attraversa la mezzanotte. Ogni nuovo carrello ha il proprio CRL e mantiene il lotto
finale comune e l'articolo della ricetta. I codici storici non vengono modificati.
