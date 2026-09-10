# MIRA — interfaccia operativa

La UI Django è disponibile alla radice del gestionale, `/`, con accesso da
`/accesso/`. L'Admin esistente resta su `/admin/` per configurazioni, ricette,
anagrafiche e gestione degli utenti. Si usano gli stessi account e gruppi.

## Avvio in VS Code

Nella cartella MIRA eseguire un comando alla volta e fermarsi in caso di errore:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita interfaccia
& "C:\gestionale\venv\Scripts\python.exe" manage.py runserver
```

Aprire http://127.0.0.1:8000/ e accedere con un account esistente.
La suite comprende ora 462 test; il numero individuato non equivale a test superati.
Il server di sviluppo usa la configurazione locale già presente. Le risorse CSS/JS
sono nell'app interfaccia; per un futuro rilascio usare collectstatic e il server
statico della distribuzione, senza modificare le impostazioni di sicurezza qui.

Gli utenti demo creati da seed_demo inizialmente non hanno una password utilizzabile.
Per impostarne una tramite prompt locale:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py changepassword demo11_multi
```

demo11_multi ha i ruoli operatore produzione e responsabile magazzino.
demo11_produzione può pianificare; demo11_qualita gestisce le NC. Non è necessario
ricreare gli utenti o il dataset.

## Pagine e flussi

- Panoramica: lavorazioni in corso, pianificate, NC aperte e lotti tracciati,
  limitati ai permessi di consultazione. Indicatori calcolati dal database.
- Magazzino: giacenze fisiche, ricerca, paginazione, movimenti storici, ricevimento,
  trasferimento e rettifica motivata. Quantità nelle unità dei singoli articoli.
  Le giacenze fisiche includono la quarantena; il servizio di consumo verifica
  nuovamente la disponibilità libera. Il ricevimento registra una destinazione;
  ulteriori ripartizioni sono eseguibili con trasferimenti.
- Produzione: pianificazione di uno o più batch, filtro per stato, avvio, input
  strutturali o ingredienti da ricetta, registrazione resa, controlli, completamento,
  interruzione e annullamento delle lavorazioni mai avviate.
- Prelievi da ricetta: proposta FIFO/FEFO con righe modificabili, scelta lotti,
  ubicazioni/scaffali/piani, ripartizione su più input e conferma atomica.
  Le quantità reali possono discostarsi dal teorico, come nel servizio collaudato:
  nessuna nuova tolleranza aziendale introdotta. Le proposte parziali sono segnalate.
- Risorse e unità: assegnazione risorsa, preparazione identità lotto, creazione
  unità, partecipazione ai trattamenti e chiusura unità. Il consolidamento del
  prodotto può usare un lotto già preparato. La chiusura del ciclo è disponibile
  al responsabile produzione dopo il completamento e resta validata dal servizio.
- Qualità: apertura NC, presa in gestione, azioni incluse quarantena/reintegro/scarto,
  verifica efficacia e chiusura esplicita. Storico consultabile senza modifica diretta.
- Lotto: articolo, scadenza, ubicazioni e genealogia a monte/a valle con collegamenti
  ai lotti e alle lavorazioni coinvolti.
- Anagrafiche: catalogo consultabile; configurazioni e modifiche nell'Admin,
  accessibili ai rispettivi ruoli autorizzati.

## Protezioni e modifica dello schema

Tutte le mutazioni richiedono POST, CSRF e permessi verificati sul server prima
dell'esecuzione. I servizi esistenti applicano le regole operative. Nessuna
scrittura diretta di giacenze, input/output, controlli o NC dalle viste.

La nuova migrazione interfaccia.0001 aggiunge soltanto InvioOperativo: una ricevuta
tecnica con identificativo univoco, utente, percorso e data. Il token del modulo è
firmato, legato a utente/percorso e scade dopo due ore. Ricevuta e servizio sono
nella stessa transazione: un errore permette il ritentativo, mentre il reinvio
dello stesso modulo non ripete un movimento. Le migrazioni storiche restano intatte.

## Verifiche e limiti effettivi

106 test senza database superati, inclusi compilazione template, accesso anonimo,
login, quantità italiane e firme dei moduli. Test di integrazione predisposti per
pagine, permessi, CSRF, invio duplicato, rollback e prelievi da ricetta. La suite
MySQL aggiornata deve ancora essere eseguita nel terminale dell'utente: questa
sessione non può avviare il Python del virtualenv, come già documentato.

Anteprime statiche con dati fittizi generate in work/ui_preview (fuori dal progetto).
Il controllo visuale automatizzato non è stato completato: il browser di automazione
ha restituito un errore di sessione. Non viene dichiarata una verifica visiva riuscita.
Verificare nel browser reale desktop e telefono dopo l'avvio locale.

L'interfaccia è una prima versione operativa. Non include ancora editor dedicati
per le configurazioni avanzate (resta l'Admin), stampa documenti o documenti di
conteggio inventariale. La UI non introduce nuovi parametri di qualità aziendali.


### Correzione pagina ingredienti

Il primo collaudo UI MySQL ha eseguito 460 test con un errore nella visualizzazione
principale degli ingredienti: il filtro default tentava di leggere il nome di una
categoria nulla anche per le righe con articolo. Sostituito con una scelta esplicita
fra articolo e categoria. Aggiunti due test di rendering per le due alternative;
i 9 test locali interfaccia.tests.test_rules sono superati. La suite MySQL aggiornata
(462 test) resta da rieseguire. Nessuna nuova migrazione necessaria per la correzione.
