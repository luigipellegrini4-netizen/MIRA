# Confezionamento parziale: intervento da implementare

## Problema verificato

Il lotto conserva `quantita_confezionata` cumulativa. Le giacenze e i movimenti
non distinguono pezzi confezionati e non confezionati. Il limite attuale,
minimo tra disponibilità fisica e residuo storico, non basta dopo vendite
o scarti: potrebbe permettere di confezionare nuovamente pezzi già confezionati.

## Comportamento previsto

- Conservare articolo e codice lotto.
- Distinguere per ubicazione, scaffale e piano quantità confezionata,
  non confezionata e, per gli storici ambigui, da classificare.
- Alla chiusura del confezionamento selezionare le posizioni e trasformare
  quantità non confezionate in confezionate senza cambiare il totale fisico.
- Vendite, scarichi, rettifiche e azioni NC devono indicare quale quantità
  movimentano. L'utente ha confermato la scelta esplicita tra confezionato e
  non confezionato anche nelle vendite.
- I trasferimenti conservano la distinzione nella destinazione.
- Le quarantene conservano anche la distinzione della quantità vincolata
  per ciascuna NC, per evitare reintegri o scarti della componente sbagliata.
- Mostrare i residui separati in giacenze, vendita e chiusura confezionamento.

## Invarianti e integrazioni

La somma delle componenti deve coincidere con la giacenza fisica, senza valori
negativi. La disponibilità di ciascuna componente deve escludere la rispettiva
quarantena. Aggiornamenti e registrazioni storiche devono essere atomici,
serializzati dal lock sul lotto già usato dal servizio movimenti.

Adeguare anche import/export CSV, backup/ripristino e azzeramento: un import
non deve perdere la classificazione né crearla arbitrariamente.

## Dati esistenti

Il totale confezionato storico non determina la classificazione corrente
dopo uscite o spostamenti. Preparare una verifica in sola lettura e una
procedura esplicita di riconciliazione per posizione. Nessuna redistribuzione
automatica dei casi ambigui. Conservare il totale storico come dato distinto
dalla quantità confezionata attualmente in magazzino.

## Verifiche necessarie

Esempio base: 600 pezzi, 200 confezionati, vendita di 100 confezionati:
residuo 100 confezionati e 400 non confezionati. Vendita invece di 100 non
confezionati: residuo 200 confezionati e 300 non confezionati.

Verificare trasferimenti parziali, scarti ordinari e da NC, quarantena e
reintegro, rettifiche, doppia chiusura, concorrenza con vendita, import/export
e ripristino. Verificare sia SQLite sia MySQL.

Questo documento descrive il lavoro da fare: non introduce modifiche al DB
o al comportamento applicativo.

Diagnosi disponibile: `python manage.py verifica_confezionamento`. Il comando
confronta saldi fisici e movimenti per posizione, totale storico e sessioni
chiuse, ed elenca i lotti la cui ripartizione deve essere verificata.
