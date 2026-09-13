# Confezionamento parziale

La giacenza mantiene il totale e la quantità confezionata per ubicazione,
scaffale e piano. La differenza è la quantità non confezionata.
Articolo e codice lotto rimangono invariati.

## Uso

Alla chiusura del confezionamento scegliere una posizione e la quantità
realmente confezionata. Se il materiale è su più posizioni, registrare una
sessione per posizione. La chiusura conserva il totale fisico e registra
posizione, quantità, operatore e data nella sessione.

Nelle vendite, nei trasferimenti, negli scarichi, nelle rettifiche e nelle
azioni NC sui prodotti finiti scegliere Confezionato o Non confezionato.
Per movimentare entrambe le componenti registrare due righe o operazioni.
Il controllo delle disponibilità è ripetuto al salvataggio sotto lock del lotto.
Le quarantene riservano separatamente le componenti per ciascuna NC.

Giacenze e scheda lotto mostrano i due saldi per posizione. I movimenti
mostrano la componente. La vendita propone il residuo delle righe precedenti
per la componente selezionata.

Esempio: 600 pezzi, confezionamento di 200, vendita di 100 confezionati:
restano 100 confezionati e 400 non confezionati. Se la vendita riguarda invece
100 non confezionati, restano 200 confezionati e 300 non confezionati.

## CSV e backup

Il CSV giacenze contiene `quantita` totale e `quantita_confezionata`.
Per i prodotti finiti quest'ultima colonna deve essere compilata, anche con 0.
L'import produce rettifiche distinte delle due componenti e rispetta le
quarantene. Per gli altri articoli i vecchi CSV senza la colonna restano accettati.

I backup V2 conservano saldi, componenti e posizione di confezionamento.
I backup V1 vengono convertiti in lettura: i lotti con confezionamenti storici
positivi sono segnalati per riconciliazione e non vengono redistribuiti a caso.

## Aggiornamento

Applicare le migrazioni magazzino 0008 e produzione 0020, eseguire collectstatic
e riavviare il server. Non usare contemporaneamente versioni vecchie e nuove
dell'applicazione sullo stesso database.

I saldi locali verificati erano 30 PZ fragola e 100 PZ albicocca; quello online
23 PZ fragola. Non risultavano confezionamenti: la migrazione li lascia nelle
posizioni esistenti e li considera non confezionati.
Se dopo la verifica sono stati registrati confezionamenti, i relativi lotti
sono marcati da verificare: la riconciliazione di quei casi non è automatica.
La migrazione dei dati non è reversibile automaticamente.

`python manage.py verifica_confezionamento` resta un controllo in sola lettura.

## Validazione

29 test mirati su SQLite superati: servizi, vendita, CSV, backup nuovo e
precedente, inizializzazione dei saldi e regressioni precedenti.
MySQL e concorrenza reale tra connessioni non verificati in questa sessione.

La suite estesa ha inoltre segnalato due errori preesistenti, riprodotti
sul commit 96a8c92: un test vendite che attende ValidationError invece di
PermissionDenied e un test al limite numerico Decimal su SQLite.
Un test NC basato sull'ordine degli orari ha avuto un fallimento intermittente;
questi punti restano separati dal confezionamento e da approfondire.
