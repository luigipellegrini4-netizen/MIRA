# Fase 10 — genealogia e verifica del flusso completo

La fase 9 è stata verificata dall'utente su MySQL: 389 test superati.
La fase 10 aggiunge GenealogyService, consultazione JSON nell'Admin e test
del flusso produttivo completo. Non aggiunge modelli o migrazioni.

## Consultazione

Nell'Admin, aprire Magazzino → Lotti. La colonna Tracciabilità JSON contiene
i collegamenti A monte e A valle. Sono richiesti un utente staff attivo e
il permesso can_view_genealogy, assegnato ai ruoli operativi. AMMINISTRATORE
puro non ottiene questo permesso automaticamente; il superutente tecnico lo ha.
Le pagine restituiscono JSON e non modificano i dati.

```python
from produzione.services import GenealogyService

monte = GenealogyService.upstream(actor=utente, lotto=lotto_commerciale)
valle = GenealogyService.downstream(actor=utente, lotto=lotto_acquistato)
# Si possono passare oggetti salvati oppure ID numerici.
```

A monte si risale da Lotto.lavorazione_origine agli input reali e ai relativi
lotti, fino alle materie acquistate. A valle si seguono gli InputLavorazione
che consumano i lotti selezionati e i lotti generati dalle relative lavorazioni.
La ricerca usa gli ID, non i codici: codici uguali per fornitori/articoli diversi
non vengono confusi. Un lotto condiviso tra più rami compare una volta sola.

A valle non si risale ai coingredienti estranei al percorso di partenza. A monte
non si espandono i coprodotti della stessa lavorazione. L'origine dei lotti
inclusi rimane comunque documentata. Il grafo è orientato sempre secondo il
flusso fisico: lotto → CONSUMO → lavorazione → PRODUZIONE → nuovo lotto.

## Risultato

Il dizionario è serializzabile direttamente in JSON e contiene:

- lotti, articoli, unità di misura, fornitori e ricevimenti con riferimenti DDT;
- lavorazioni, stato reale, ciclo, ricetta/versione e orari;
- legami materiali, quantità e ID dei movimenti di consumo/produzione;
- unità operative, partecipazioni ai trattamenti e risorse utilizzate;
- misurazioni qualità, compresi esiti negativi storici;
- NC collegate e relativo stato.

Quantità decimali e date sono stringhe, mentre booleani e identificativi
mantengono i loro tipi. Un'identità di lotto preparata prima dell'output compare
con output_registrato=False, output_id=None e quantita=None: non viene inventato
un carico. Una lavorazione interrotta mantiene il proprio stato.

I trattamenti delle unità compaiono come contesto del processo, senza lotti o
movimenti artificiali. Una NC collegata soltanto a una risorsa condivisa è
marcata RISORSA_CONDIVISA: non implica da sola che riguardi il lotto consultato.
Le NC riferite a lotti, lavorazioni, controlli o relative azioni sono DIRETTO.
Per i dettagli delle azioni usare NonConformitySelector.

## Limiti e completezza

La visita è iterativa e tiene traccia dei lotti già esplorati: termina anche in
presenza di collegamenti ciclici anomali. ciclo_materiale_rilevato segnala un
ciclo nel grafo restituito; una normale convergenza di rami non è un ciclo.

Il limite predefinito è 1000 lotti, modificabile con max_lotti da 1 a 10000.
Se il limite viene raggiunto, troncato=True e frontiera_omessa_ids indicano le
prime identità escluse. Un risultato troncato non rappresenta la genealogia
completa e il rilevamento cicli riguarda solo la parte restituita. Il limite
riguarda i lotti, non il numero di misurazioni o registrazioni collegate.

La lettura non prenota materiale e non prende lock operativi. Per lavorazioni
in corso, i dati possono evolvere mentre si consulta la genealogia; generato_il
indica l'istante di generazione, non certifica un'istantanea transazionale.

## Test del processo completo

Il test end-to-end predispone ed esegue tramite i servizi:

1. Due ricevimenti di materia prima con date FEFO diverse e un lotto tecnico
   per il materiale di confezionamento.
2. Ricetta per batch e due lavorazioni distinte; conferma di un lotto alternativo
   alla proposta FEFO senza alterare il criterio di consultazione.
3. Unione dei due lotti intermedi in un lotto tank.
4. Consumi reali per invasettamento, identità INV e due unità/carrelli.
5. Trattamento termico e controllo, abbattimento/verifica vuoto, NC su una misura
   negativa, azione correttiva, nuova misura, verifica e chiusura esplicita RQ.
6. Chiusura delle unità e consolidamento dell'output INV senza movimenti fittizi
   durante i trattamenti.
7. Etichettatura, lotto commerciale e completamento del ciclo.
8. Quarantena parziale del prodotto finito, reintegro, scarto e chiusura NC.
9. Riconciliazione delle giacenze e genealogia a monte/a valle, con conservazione
   dei dati qualità e delle NC storiche.

Gli altri test verificano rami convergenti, cicli, limiti, identità senza output,
ricevimenti ripetuti, permessi, risorse condivise e accesso JSON dall'Admin.

## Verifica finale su MySQL

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita
```

92 test senza database superati e nessuna migrazione mancante. La suite completa
comprende 418 test, tutti superati su MySQL in 22,613 secondi, con esito confermato
dall'utente. Le dieci fasi sono completate e verificate. Il completamento riguarda il backend:
restano separate la futura interfaccia operativa completa e la distribuzione in produzione.
