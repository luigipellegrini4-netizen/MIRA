# MIRA

Nuovo backend Django per magazzino, produzione, qualità e tracciabilità alimentare.
Progetto indipendente dai gestionali esistenti. Database previsto: **MySQL 8.4 / InnoDB**.

## Stato effettivo

La **fase 1 è stata verificata dall'utente su MySQL**: migration applicate,
ruoli inizializzati e 17 test superati. Non è ancora il gestionale completo.

- progetto Django, Admin, configurazione MySQL e cinque app;
- User standard, sei gruppi, controllo centralizzato dei permessi;
- comando idempotente `bootstrap_roles`;
- test senza database della politica e test di integrazione dei gruppi;
- protezione degli account superuser nell'Admin aziendale.

La **fase 2 è verificata su MySQL**: 77 test passati dopo il recupero della
migration iniziale. Contiene 8 modelli, migration, Admin, permessi e test dei vincoli.
La **fase 3 è verificata su MySQL** (controllo e suite confermati dall'utente): MovementService, ReceivingService,
StockProposalService e generazione centralizzata dei codici tecnici.
La suite della fase 3 comprende 134 test, incluse tre prove di concorrenza.
Nessuna nuova migration era necessaria per quella fase.
Contratti, esempi e limiti sono documentati in [docs/MAGAZZINO.md](docs/MAGAZZINO.md).
La **fase 4 è verificata su MySQL**: 172 test passati. Include Ricetta,
RigaRicetta, versionamento, fabbisogni per batch e Admin.
Dettagli in [docs/RICETTE.md](docs/RICETTE.md).
La **fase 5 è verificata su MySQL**: 219 test passati. Include tipi/requisiti,
cicli/lavorazioni, input/output e collegamenti ai lotti e ai movimenti.
Dettagli in [docs/PRODUZIONE.md](docs/PRODUZIONE.md).
La **fase 6 è verificata su MySQL**: 271 test superati. Include servizi ciclo/lavorazione, input/output atomici,
generazione lotti, riconciliazione al completamento, azioni Admin e nuovi test.
Verifica MySQL della fase 6 confermata dall'utente.
Non servono nuove migration. Dettagli in [docs/ESECUZIONE.md](docs/ESECUZIONE.md).
La fase 7 è verificata su MySQL: 295 test superati. La fase 8 è verificata:
339 test superati. La fase 9 è verificata: 389 test superati.
La fase 10 (genealogia e test end-to-end) è verificata su MySQL: 418 test superati
in 22,613 secondi, come confermato dall'utente. Tutte le dieci fasi del backend
sono completate e verificate; l'interfaccia operativa completa e la distribuzione
in produzione restano attività separate.
Il database nuovo `mira` e l'utente dedicato sono stati creati dall'utente;
nessun vecchio gestionale è stato modificato.

### Verifica fase 2 nel terminale PowerShell di VS Code

Se il primo tentativo si è fermato con l'errore MySQL 3818 su
`categoria_non_autoreferente`, il CHECK incompatibile è stato rimosso dalla
prima migration (non ancora applicata). I cicli restano validati da `clean()` e
`save()`. MySQL vieta CHECK sulle colonne AUTO_INCREMENT:
https://dev.mysql.com/doc/refman/8.4/en/create-table-check-constraints.html

Prima di ripetere migrate, completare la migration parziale con:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py recover_anagrafiche_initial --apply
```

Il comando è specifico per questa interruzione: verifica quattro tabelle vuote,
colonne, tipi, nullabilità, chiavi primarie e univoche; aggiunge solo FK e CHECK
mancanti, quindi registra la migration completata. Non elimina tabelle o dati.
Senza `--apply` controlla soltanto. Se lo schema è inatteso o contiene dati si
ferma. Se la migration è già registrata non la modifica.
Il recupero richiede una sola esecuzione alla volta, con l'applicazione ferma.
32 test senza database passati dopo la correzione; recupero effettivo e suite
di integrazione della fase 2 successivamente verificati dall'utente su MySQL.

Eseguire nella cartella MIRA, fermandosi al primo errore:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_roles
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino
```

Le migration aggiungono solo tabelle e vincoli delle nuove app al database MIRA.
Lotti, ricevimenti, stock e movimenti sono consultabili nell'Admin senza modifica diretta.
La registrazione di magazzino è disponibile nei servizi della fase 3; l'Admin
mantiene lo storico consultivo, senza scrittura diretta sulle giacenze.

### Dettagli schema MySQL

- `Lotto.codice_univoco_produzione` è una colonna tecnica generata dal database:
  contiene il codice per i lotti prodotti, NULL per gli acquisti. L'indice univoco
  articolo/colonna generata garantisce l'unicità di produzione anche con fornitore NULL.
  Un altro indice garantisce articolo/fornitore/codice per gli acquisti.
  Non si usano indici condizionali, non supportati da MySQL.
- Quantità Decimal a 6 decimali; minimo positivo rappresentabile 0.000001.
- Il ricevimento usa un timestamp con timezone; scaffale/piano sono codici normalizzati.
- Le FK verso lavorazione e input/output saranno aggiunte nella fase 5, senza modelli fittizi.
- `_stock_write` è un dettaglio interno riservato al futuro MovementService e alle fixture
  dei test di schema. Non usare il contesto o SQL diretto nei flussi applicativi.
  Le barriere ORM non sostituiscono la sicurezza degli account MySQL.

## Ambiente

Versioni rilevate nei pacchetti locali: Django 6.1 e mysqlclient 2.2.8.
L'ambiente esistente `C:\gestionale\venv` indica Python 3.14.7.
Il suo avvio da Codex ha restituito Accesso negato; questo non dimostra che non funzioni dal terminale dell'utente.

I controlli statici sono eseguibili senza driver MySQL tramite `config.check_settings`,
che usa il backend **dummy**, senza SQLite o altro database sostitutivo.
Questi controlli non sostituiscono i test di integrazione MySQL.

## Configurazione locale

1. Aprire un terminale nella cartella MIRA.
2. Copiare `.env.example` in `.env`.
3. Inserire una chiave segreta casuale, utente e password MySQL in `.env`.
   Il file è escluso da Git. Non inviare password in chat.
4. Creare un database nuovo `mira` con charset `utf8mb4` e tabelle InnoDB;
   predisporre i permessi sul database separato `mira_test` per i test.
5. Usare preferibilmente un utente MySQL dedicato al progetto. L'eventuale
   account root di Workbench serve alla configurazione iniziale, non è obbligatorio per Django.

Parametri già individuati: host locale `127.0.0.1`, porta configurata `3306`.
Utente applicativo concordato: `mira_app`. Le credenziali sono nel file `.env` locale.

Con un interprete che contiene Django e mysqlclient:

```powershell
python manage.py migrate
python manage.py bootstrap_roles
python manage.py check
python manage.py test accounts
python manage.py createsuperuser
python manage.py runserver
```

Aprire http://127.0.0.1:8000/admin/ per l'Admin locale.
Il test runner crea e rimuove `mira_test`: non configurare mai un database reale come database di test.
Per i soli controlli senza database:

```powershell
python manage.py check --settings=config.check_settings
python manage.py test accounts.tests.test_policy --settings=config.check_settings
```

## Decisioni concordate

- Quantità sempre associate a un lotto, anche tecnico; movimenti positivi e stock aggiornato atomicamente.
- Macchine, tank e carrelli sono risorse produttive, non ubicazioni.
- InputLavorazione rappresenta materiale consumato; i trattamenti senza consumo
  identificano il lotto attraverso unità e partecipazioni.
- L'identità INV può precedere il suo output consolidato; i trattamenti sulle unità
  non generano consumi né output artificiali.
- Previsto `RequisitoFaseUnitaTipoLavorazione` per configurare le fasi richieste alle unità.
- Nessuna logica specifica per singole linee produttive in classi Python.
- Permessi operativi cumulativi, nessun bypass aziendale per AMMINISTRATORE.
- Le fasi successive iniziano solo dopo i controlli richiesti della fase precedente.

## App previste

| App | Ambito |
|---|---|
| accounts | Ruoli, permessi, gestione utenti |
| anagrafiche | Categorie, articoli, fornitori, ubicazioni |
| magazzino | Lotti, ricevimenti, movimenti, giacenze, inventario |
| produzione | Ricette, requisiti, cicli, lavorazioni, risorse, unità |
| qualita | Parametri, controlli, non conformità, azioni e verifiche |

I permessi custom sono in `accounts/permissions.py`, ancorati al ContentType
`auth.Group`: la stringa controllata dai servizi è `auth.can_…`.
Il comando risincronizza i permessi custom gestiti da MIRA e conserva quelli esterni.
Le autorizzazioni di consultazione/gestione dei modelli di dominio saranno aggiunte
con le rispettive app nelle fasi successive, senza attribuire operatività al gruppo amministratore.

## Fase 7 verificata

Controlli qualità tipizzati, storico immutabile e blocco della chiusura per controlli mancanti o non conformità determinanti. Dettagli in [docs/QUALITA.md](docs/QUALITA.md). Suite completa della fase 7: 295 test superati su MySQL, confermati dall'utente.

## Fase 8 verificata

Risorse, unità operative, partecipazioni e percorsi configurabili. Il completamento
dell'origine verifica tutte le unità, i trattamenti richiesti e gli output reali.
Le operazioni sulle unità non modificano il magazzino. Dettagli, esempi e comandi
di verifica in [docs/UNITA.md](docs/UNITA.md). Verifica MySQL confermata dall'utente: 339 test superati.

## Fase 9 verificata

Non conformità, azioni, verifiche e chiusura esplicita RQ. Quarantena, reintegro
e scarto passano da MovementService; lo stock vincolato è escluso dalle proposte
e dai normali prelievi. Le NC chiuse risolvono i blocchi delle misure espressamente
collegate, conservandone lo storico. Dettagli in [docs/NON_CONFORMITA.md](docs/NON_CONFORMITA.md).
Suite MySQL della fase 9 confermata dall'utente: 389 test superati.

## Fase 10 verificata

GenealogyService a monte/a valle, collegamenti JSON nella lista lotti dell'Admin,
contesto di unità, risorse, controlli e NC, test del flusso completo dalle materie
prime al lotto commerciale. Nessuna nuova migrazione. Dettagli e comandi finali
in [docs/GENEALOGIA.md](docs/GENEALOGIA.md).
92 test senza database superati; suite completa di 418 test superati su MySQL,
con esito confermato dall'utente (22,613 secondi).

## Interfaccia operativa

La fase 11 è verificata: 442 test MySQL e tutti gli scenari PASS.
È stata aggiunta la prima UI Django con login, panoramica, magazzino,
produzione, qualità e genealogia. Si apre alla radice `/`; l'Admin resta su `/admin/`.
Avvio, nuova migrazione e verifiche: [docs/INTERFACCIA.md](docs/INTERFACCIA.md).
La suite di 462 test è stata superata su MySQL, con esito confermato dall'utente.

## Flusso aziendale semilavorati e confetture

Estensione del motore con linee/postazioni, turni, piano di prelievo revisionato,
batch RoboQbo, tank rilasciati dai controlli Brix/pH, carrelli con lotto finale
comune, confezionamento e resa. Richiede le nuove migrazioni e il bootstrap ruoli.
Il collaudo del motore è stato confermato dall'utente: suite di 495 test.
Specifiche, API dei servizi
e comandi: [docs/FLUSSO_AZIENDALE.md](docs/FLUSSO_AZIENDALE.md).

La UI aziendale è disponibile in **Linee e turni**: configurazione guidata,
turni, igienizzazione, piani/prelievi, batch, tank, carrelli e chiusura con resa.
Suite aggiornata: 525 test, 125 senza database superati; nuovo collaudo MySQL da eseguire. Percorso a video
e limiti: [docs/UI_LINEE_TURNI_BATCH.md](docs/UI_LINEE_TURNI_BATCH.md).

