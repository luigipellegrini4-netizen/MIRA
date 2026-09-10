# Caricamento di prova per confetture

Il comando conserva utenti, password, ruoli, ricette, configurazioni, produzione e qualità esistenti. Elimina esclusivamente movimenti, giacenze, ricevimenti e lotti, solo se non hanno collegamenti esterni. Prima del reset salva un backup JSON delle quattro tabelle in `backups/`. Tutto il reset e il caricamento sono in una transazione MySQL.

Le ricette sono esempi per provare il gestionale, non formule produttive validate. I semilavorati e le confetture caricati a magazzino sono giacenze iniziali fittizie: non si inventano lavorazioni o genealogie produttive.

## Articoli e lotti

Tre lotti per ogni articolo; ogni lotto contiene la quantità indicata. Gli articoli nuovi hanno prefisso `AVV_`.

| Codice | Articolo | Unità | Quantità per lotto |
|---|---|---|---|
| MP_FRAGOLA | Fragole surgelate pulite | KG | 100 |
| SL_FRAGOLA | Semilavorato di fragole | KG | 50 |
| CF_FRAGOLA | Confettura di fragole | KG | 20 |
| MP_ALBICOCCA | Albicocche surgelate denocciolate | KG | 100 |
| SL_ALBICOCCA | Semilavorato di albicocche | KG | 50 |
| CF_ALBICOCCA | Confettura di albicocche | KG | 20 |
| MP_PESCA | Pesche surgelate denocciolate | KG | 100 |
| SL_PESCA | Semilavorato di pesche | KG | 50 |
| CF_PESCA | Confettura di pesche | KG | 20 |
| MP_PRUGNA | Prugne surgelate denocciolate | KG | 100 |
| SL_PRUGNA | Semilavorato di prugne | KG | 50 |
| CF_PRUGNA | Confettura di prugne | KG | 20 |
| MP_CILIEGIA | Ciliegie surgelate denocciolate | KG | 100 |
| SL_CILIEGIA | Semilavorato di ciliegie | KG | 50 |
| CF_CILIEGIA | Confettura di ciliegie | KG | 20 |
| MP_ZUCCHERO | Zucchero bianco | KG | 150 |
| MP_PECTINA | Pectina per confetture | KG | 5 |
| MP_ASCORBICO | Acido ascorbico | KG | 2 |
| MP_PUREA_MELA | Purea di mela | KG | 60 |
| MOCA_VASETTO | Vasetto vetro 314 ml, imboccatura TO 63 | PZ | 1000 |
| MOCA_CAPSULA | Capsula twist-off TO 63 | PZ | 1000 |

Se le linee AZ_ sono già configurate, il comando riutilizza le categorie di output e i due articoli MOCA della linea, conservandone nomi e codici. Così le nuove ricette e giacenze sono compatibili con la configurazione esistente. Altrimenti crea anche le categorie AVV_MP, AVV_SL, AVV_CF e AVV_MOCA. Le vecchie anagrafiche non vengono eliminate.

## Ricette per un batch

| Prodotto | Ingredienti in KG |
|---|---|
| SL_FRAGOLA | MP_FRAGOLA = 10; MP_ASCORBICO = 0.050 |
| CF_FRAGOLA | SL_FRAGOLA = 10; MP_PECTINA = 0.150; MP_ASCORBICO = 0.020; MP_PUREA_MELA = 2; MP_ZUCCHERO = 6 |
| SL_ALBICOCCA | MP_ALBICOCCA = 10; MP_ASCORBICO = 0.050 |
| CF_ALBICOCCA | SL_ALBICOCCA = 10; MP_PECTINA = 0.150; MP_ASCORBICO = 0.020; MP_PUREA_MELA = 2; MP_ZUCCHERO = 6 |
| SL_PESCA | MP_PESCA = 10; MP_ASCORBICO = 0.050 |
| CF_PESCA | SL_PESCA = 10; MP_PECTINA = 0.150; MP_ASCORBICO = 0.020; MP_PUREA_MELA = 2; MP_ZUCCHERO = 6 |
| SL_PRUGNA | MP_PRUGNA = 10; MP_ASCORBICO = 0.050 |
| CF_PRUGNA | SL_PRUGNA = 10; MP_PECTINA = 0.150; MP_ASCORBICO = 0.020; MP_PUREA_MELA = 2; MP_ZUCCHERO = 6 |
| SL_CILIEGIA | MP_CILIEGIA = 10; MP_ASCORBICO = 0.050 |
| CF_CILIEGIA | SL_CILIEGIA = 10; MP_PECTINA = 0.150; MP_ASCORBICO = 0.020; MP_PUREA_MELA = 2; MP_ZUCCHERO = 6 |

Per i semilavorati: 10 KG di frutta e 0,050 KG di acido ascorbico. La quantità reale ottenuta può essere 10 KG. Per le confetture: massa nominale 18,170 KG per batch. Tutte le ricette hanno versione PROVA-1.

## Esecuzione

Prima eseguire l’anteprima, dalla cartella MIRA:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py inizializza_confetture
```

Se segnala collegamenti a produzione/qualità, nessun dato viene modificato: riportare il messaggio per decidere come procedere, senza cancellare automaticamente le lavorazioni.

Se l’anteprima è libera da blocchi, fermare il server MIRA con Ctrl+C nel relativo terminale e tutte le altre istanze del gestionale. Eseguire, solo se il nome mostrato è mira:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py inizializza_confetture --apply --database-atteso mira
```

Con altro nome usare esattamente quello mostrato nell’anteprima. Il comando mostra le utenze esistenti usate per registrare ricette e carichi; si possono scegliere con --utente-ricette NOME e --utente-carichi NOME. Non crea utenti e non modifica i permessi.

Il rilancio esplicito resetta nuovamente il magazzino e ripristina 63 lotti, riutilizzando articoli/ricette compatibili. Non azzera gli identificativi o i progressivi produttivi. Il backup va conservato; un eventuale ripristino richiede una procedura dedicata per evitare conflitti di identificativi.

Verifica locale: catalogo e formule controllati con test senza database. Reset e caricamento MySQL non eseguiti da Codex: l’interprete locale di MIRA restituisce Accesso negato. Sono predisposti test MySQL di conservazione accessi, caricamento e blocco per collegamenti produttivi.


## Reset operativo completo autorizzato

Con `--includi-produzione-qualita` vengono eliminate anche tutte le registrazioni operative di produzione e qualità: cicli, lavorazioni, prelievi, batch, tank, carrelli, sessioni, turni, controlli eseguiti, non conformità, azioni e codici produttivi. Restano utenti, password, ruoli, anagrafiche, ricette, linee, postazioni, risorse, tipi di lavorazione e configurazioni dei controlli. Il comportamento senza questa opzione resta limitato al magazzino.

Fermare tutte le istanze MIRA. Eseguire prima i test; continuare solo se terminano con OK:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py test magazzino.tests.test_initial_catalog
& "C:\gestionale\venv\Scripts\python.exe" manage.py inizializza_confetture --includi-produzione-qualita --apply --database-atteso mira --utente-ricette luigi --utente-carichi luigi
```

Il backup `backups/operativi_*.json` contiene tutte le registrazioni eliminate, con identificativi originali. Il caricamento e il reset sono atomici: un errore annulla le modifiche al database. I vincoli FK rimangono attivi. Non vengono azzerati gli AUTO_INCREMENT; nel reset completo vengono invece cancellati i registri dei codici produttivi. Eventuali riferimenti da tabelle esterne al perimetro bloccano l'operazione. Conservare il backup per un eventuale ripristino dedicato.
