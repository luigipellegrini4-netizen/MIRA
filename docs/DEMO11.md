# Collaudo DEMO11 — istruzioni

Aprire in VS Code la cartella MIRA e usare il terminale PowerShell.
Usare lo stesso .env locale già configurato per MySQL. Non copiare password
nei comandi condivisi o nella documentazione.

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py seed_demo
& "C:\gestionale\venv\Scripts\python.exe" manage.py seed_demo
& "C:\gestionale\venv\Scripts\python.exe" manage.py collaudo_fase11
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita
& "C:\gestionale\venv\Scripts\python.exe" manage.py showmigrations --plan
& "C:\gestionale\venv\Scripts\python.exe" manage.py makemigrations --check --dry-run
```

Eseguire nell'ordine; se un comando fallisce, fermarsi e conservare l'errore.
Il secondo seed verifica il rilancio senza duplicazione. La suite attesa ha
442 test, inclusi i precedenti 418; il numero individuato non è un esito PASS.
Non usare --keepdb: Django deve creare mira_test dalle migrazioni e poi eliminarlo.

seed_demo richiama bootstrap_roles e crea solo il dataset dimostrativo.
collaudo_fase11 richiama seed_demo ed esegue A–G e STORICO in un'unica transazione.
Un errore annulla tutto il tentativo. Se il seed era stato eseguito separatamente,
il dataset iniziale resta disponibile. Gli errori negli scenari generano un verbale
FAIL: gli ID del tentativo annullato sono provvisori, non record persistiti.
Una collisione prima degli scenari viene segnalata direttamente come CommandError.

I file generati sono docs/FASE_11_COLLAUDO.md e docs/FASE_11_RISULTATI.json.
In caso di successo il JSON originale è conservato anche nelle note del ciclo demo A
prima della chiusura. Rilanciare collaudo_fase11 ripubblica quel verbale storico,
senza nuovi consumi. Se la scrittura dei file fallisce dopo il commit, il rilancio
permette di rigenerarli. Non equivale a verificare nuovamente uno stato modificato
in seguito. Il verbale contiene la genealogia completa dei lotti prodotti.

## Utenti

| Username | Ruolo |
|---|---|
| demo11_admin | AMMINISTRATORE puro, nessun permesso operativo implicito |
| demo11_produzione | RESPONSABILE_PRODUZIONE |
| demo11_magazzino | RESPONSABILE_MAGAZZINO |
| demo11_qualita | RESPONSABILE_QUALITA |
| demo11_operatore | OPERATORE_PRODUZIONE |
| demo11_magazziniere | MAGAZZINIERE |
| demo11_multi | OPERATORE_PRODUZIONE + RESPONSABILE_MAGAZZINO |

Utenti staff, non superuser, con password inizialmente inutilizzabile.
I comandi di collaudo non richiedono login. Per accedere all'Admin:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py changepassword demo11_operatore
```

Sostituire lo username per gli altri ruoli. Lo stesso comando reimposta la password
tramite prompt locale; seed_demo la conserva. Nessuna password comune o predefinita.

## Dataset e limiti

I codici demo usano DEMO11_; il tipo usa il codice richiesto PRODUZIONE_SEMILAVORATI.
Configurazioni preesistenti incompatibili causano un arresto, senza reset automatico.
Non cancellare dati storici per rilanciare. Le categorie distinguono MP, SL, MOCA,
produzione marmellata e prodotti finiti. Gli articoli sono FRAGOLE GELO,
ACIDO ASCORBICO e SEMILAVORATO FRAGOLA, tutti KG.

| Ubicazione demo | Disponibilità iniziale |
|---|---|
| MAG | Fragole 40+40 KG, acido 1+1 KG |
| C | Fragole 6+8 KG, acido 1 KG |
| D | Fragole 10 KG, acido 0,010 KG |
| BUFFER_PRODUZIONE | Vuota, riceve gli output da 9,800 KG |
| QUARANTENA | Vuota, usata dalle azioni NC |

Ricevimenti demo datati 1–2 gennaio 2026; scadenze 2030–2031. Per l'acido l'ordine
delle scadenze è opposto ai ricevimenti: verifica FIFO effettivo. Le date sono esempi
fissi di collaudo, non indicazioni di conservabilità del prodotto reale.

La conferma ricetta richiede tutte le righe e rifiuta una seconda conferma;
un tentativo fallito può essere ripetuto. Le proposte non prenotano scorte.
Gli input strutturali restano disponibili per ingredienti non derivati dalla ricetta.
La compatibilità con i vecchi input non riscrive lo storico. Nessuna tolleranza
quantitativa aziendale è stata aggiunta: resa e consumi reali restano dati espliciti.
I controlli qualità demo sono tecnici; il conteggio G non crea documenti inventariali.

La fase 11 termina con la revisione degli esiti e del verbale, senza avviare la fase 12.
