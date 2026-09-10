# UI aziendale: dalle linee alla chiusura dell'invasettamento

UI aziendale: configurazione delle due linee, postazioni,
inizio/fine turno, igienizzazione, piano di produzione, previsione dei prelievi,
esecuzione dei batch RoboQbo e semilavorati, formazione/rilascio tank, sessioni,
carrelli, trattamenti, prelievi confezioni e resa finale.

La suite precedente di 495 test del motore è stata confermata funzionante
dall'utente. La suite con questa UI comprende **525 test**: **125 test senza
database superati**, test MySQL della nuova UI ancora da eseguire.
Non sono state aggiunte migrazioni né modificati i permessi.

## Verifica in VS Code

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita interfaccia
```

## Percorso a video

1. Aprire **Linee e turni** nel menu laterale, all'indirizzo `/linee/`.
2. Se le linee non sono configurate, accedere come amministratore e premere
   **Configura le due linee**. Selezionare le categorie semilavorati/confetture
   e due articoli distinti per vasetti/capsule, entrambi in PZ. Il riepilogo
   mostra postazioni e controlli prima della conferma. Non crea produzioni o
   movimenti. Una configurazione esistente diversa viene segnalata senza
   sovrascrittura. Servono i permessi di configurazione processi, parametri
   qualità e controlli richiesti: l'amministratore li possiede; un operatore no.
3. Accedere come operatore, aprire **RoboQbo** e premere **Inizia turno**.
4. Premere **Nuovo piano**, scegliere ricetta/versione e numero di batch.
5. Aprire il piano e **Prepara piano prelievi**. Controllare la proposta FIFO/FEFO,
   modificarla se necessario e confermare. È una previsione, non una prenotazione
   o un prelievo. Le righe possono essere aggiunte o eliminate; l'ordine delle
   righe confermate stabilisce l'ordine dei lotti utilizzati nei batch.
6. Aprire un batch, premere **Avvia batch**, poi **Controlla e conferma prelievo**.
   La tabella mostra articolo, lotto, ubicazione, scaffale/piano e KG effettivi.
   La conferma registra i consumi; per cambiare lotti si torna alla revisione
   del piano complessivo, preservando i consumi già registrati.
7. Registrare l'esito **C / NC / NA** di **82 °C × 60 secondi** e concludere il
   batch scegliendo la destinazione. Non si chiede la pesata: la quantità
   nominale è ricavata dalla ricetta. NC e NA restano visibili e bloccanti.
8. Nella postazione **Semilavorati** il percorso è analogo, ma alla conclusione
   si indica la quantità reale ottenuta e non è previsto il controllo RoboQbo.
9. Tornare alla postazione e premere **Termina turno** dopo aver concluso le
   lavorazioni. Il servizio segnala eventuali attività ancora aperte.

Un secondo operatore può aprire contemporaneamente il turno della postazione
**Invasettamento** e confermare che vasetti/capsule sono puliti e igienizzati.
La casella è obbligatoria e non preselezionata; ogni nuovo turno richiede una
nuova conferma.

## Tank e invasettamento

1. Nella postazione RoboQbo premere **Forma un tank**, scegliere la ricetta e
   **Mostra materiali**. Selezionare i batch completati e la destinazione del
   tank. La selezione consuma l'intera quantità indicata nelle posizioni scelte;
   non richiede una pesata. Ogni conferma crea una lavorazione e un lotto TNK.
2. Nella scheda tank registrare **°Brix e pH**. Il rilascio è automatico solo
   con `40 < °Brix < 45` e `pH <= 4,1`. Una misura fuori limite viene registrata
   come NC, non semplicemente rifiutata dal modulo; il tank resta bloccato.
3. Nell'altra postazione, dopo turno e igienizzazione, premere **Apri sessione**.
   Scegliere la ricetta, mostrare i materiali, selezionare i tank pronti e gli
   articoli/requisiti di vasetti e capsule. Sono proposti soltanto i tank pronti
   della stessa linea e ricetta. Confermare il prelievo e l'apertura della sessione.
4. Premere **Carrello pronto** per ciascun carrello; l'associazione a un carrello
   fisico è facoltativa. MIRA assegna CRL e conserva il lotto finale comune.
5. Sul carrello registrare **71 °C × 4 minuti**, poi **Shock termico e vuoto**,
   ciascuno con C/NC/NA. Il pulsante della fase successiva appare solo dopo il
   completamento conforme della precedente. Le fasi già registrate non vengono
   proposte nuovamente. NC e NA rimangono bloccanti, senza una nuova procedura NC.
6. **Aggiungi tank pronti** permette di continuare la stessa sessione con altri
   tank della stessa ricetta. Tutti i carrelli conservano la genealogia comune
   dell'insieme dei tank consumati nella sessione.
7. **Concludi invasettamento** chiede vasetti buoni, vasetti da scartare, capsule
   difettose, peso netto del vasetto in grammi e destinazione del prodotto buono.
8. **Calcola resa e proponi confezioni** mostra quantità reali/teoriche, resa e
   proposta modificabile dei lotti/posizioni di confezioni. Questo passaggio non
   registra prelievi. I vasetti necessari sono buoni + scarti; le capsule sono
   vasetti necessari + capsule difettose. Gli scarti concorrono alla resa.
9. **Conferma prelievi e chiudi sessione** registra confezioni, riepilogo, prodotto
   buono e chiusure nella stessa transazione. Un errore annulla tutto il tentativo.
   I conteggi sono firmati insieme al riepilogo: per cambiarli usare **Modifica
   conteggi** e generare una nuova proposta. Il riepilogo finale rimane nella
   scheda sessione, con collegamento al lotto e alla genealogia.
10. Terminare il turno dalla postazione quando tutte le attività sono chiuse.

## Protezioni e limiti di questa consegna

- GET consulta e mostra moduli; solo POST con CSRF e token valido registra dati.
- Gli invii riusciti non vengono ripetuti al doppio clic o al reinvio del modulo.
- La proposta del batch è firmata e legata a utente, pagina, revisione e quantità
  residue. Se cambia mentre è aperta, la conferma viene rifiutata con richiesta
  di riaprire la pagina; non viene consumata una selezione diversa da quella vista.
- Le revisioni del piano controllano anche l'elenco dei batch ancora da prelevare.
- Le azioni passano ai servizi del motore: disponibilità, turni, postazione,
  controlli e permessi vengono nuovamente verificati al momento della scrittura.
- La lista mostra gli ultimi 30 piani della postazione; i precedenti restano
  consultabili nell'Admin. Anche le liste tank/sessioni mostrano gli ultimi 30.
  Gli ingredienti e i prelievi di confezioni consentono fino a 200 righe per modulo.
- Il dettaglio delle lavorazioni aziendali batch, raggiunto anche dalla lista
  Produzione, apre la nuova schermata dedicata.

La UI preleva interamente ciascuna posizione selezionata di batch/tank; il motore
supporta anche quantità parziali, ma non sono richieste in queste schermate.
Le proposte firmate rifiutano quantità cambiate mentre la pagina era aperta.
È stata aggiunta una validazione dei risultati numerici fuori intervallo, per
segnalare conteggi/pesi eccessivi come errori del modulo.
Non serve avviare produzioni reali per eseguire i test automatici.
