# Fase 9 — non conformità, azioni e verifiche

La fase 8 è stata verificata dall'utente su MySQL: 339 test superati.
La fase 9 aggiunge NonConformita, AzioneNonConformita, VerificaNonConformita,
NonConformityService e NonConformitySelector.

## Permessi e flusso

Tutti i ruoli operativi possono aprire una NC. Soltanto RQ può prenderla in
gestione, eseguire azioni, verificare e chiudere. I gruppi restano cumulativi;
AMMINISTRATORE puro non riceve permessi operativi. RILAVORAZIONE collega una
nuova lavorazione già pianificata da RP: RQ non acquisisce il permesso di pianificare.

APERTA → IN_GESTIONE → CHIUSA. Numero progressivo unico, generato dal servizio
con un lock comune; la numerazione non è basata su un conteggio non protetto.
I dati di apertura, le azioni e le verifiche sono storici. Presa in gestione e
chiusura aggiungono autore, istante e note alla NC; non cambiano i dati originari.

```python
from qualita.services import NonConformityService as NC
from qualita.nc_selectors import NonConformitySelector
from magazzino.services import Position

nc = NC.open(actor=operatore, descrizione="Anomalia rilevata", lotto=lotto)
nc = NC.take_charge(actor=responsabile_qualita, non_conformita=nc)
azione = NC.action(
    actor=responsabile_qualita, non_conformita=nc,
    tipo_azione="QUARANTENA", descrizione="Isolamento della quantità interessata",
    quantita="50", origine=Position(magazzino.pk),
    destinazione=Position(area_isolamento.pk),
)
# Dopo la decisione RQ, reintegro o scarto, anche parziali:
NC.action(
    actor=responsabile_qualita, non_conformita=nc,
    tipo_azione="REINTEGRO", descrizione="Materiale verificato e riammesso",
    quantita="50", origine=Position(area_isolamento.pk),
    destinazione=Position(magazzino.pk),
)
NC.verify(actor=responsabile_qualita, non_conformita=nc,
          esito="EFFICACE", descrizione="Esito della verifica documentato")
# La verifica non chiude automaticamente la NC.
NC.close(actor=responsabile_qualita, non_conformita=nc,
         note="Chiusura autorizzata dopo risoluzione e verifica")
riepilogo = NonConformitySelector.detail(actor=operatore, non_conformita=nc)
```

Le operazioni sono disponibili tramite servizi Python; l'Admin consente la
consultazione di NC, azioni e verifiche, senza modifiche dirette allo storico.

## Stock e quarantena

QUARANTENA e REINTEGRO sono movimenti tra posizioni distinte dello stesso lotto;
SCARTO è un'uscita senza destinazione. Ogni azione fisica ha un movimento univoco.
Il servizio NC chiama MovementService: se uno dei salvataggi fallisce, vengono
annullati insieme azione, movimento e aggiornamenti di giacenza.
RETTIFICA non è un tipo azione NC e rimane riservata al Responsabile Magazzino.

La NC non contiene quantità o stato di quarantena. Il vincolo è ricostruito
dallo storico delle sue azioni per NC, lotto, ubicazione, scaffale e piano:
QUARANTENA aggiunge quantità alla destinazione; REINTEGRO la libera; SCARTO la
rimuove. Lo scarto usa prima la quota vincolata dalla stessa NC e poi quella libera.
Non può intaccare quote vincolate da altre NC. Il reintegro non può superare
la quarantena residua della NC nella posizione di origine.

La giacenza rappresenta la quantità fisica totale, inclusa quella in quarantena.
Una posizione può contenere quote libere e vincolate. Le proposte FEFO/FIFO
considerano solo la parte libera; consumi, trasferimenti e rettifiche in uscita
non possono usare la parte bloccata. I lock sul lotto serializzano i movimenti
con le azioni NC concorrenti. L'ubicazione di isolamento viene scelta esplicitamente:
nessun nome di ubicazione o nuova tabella di stock è codificato nel servizio.

Se la NC indica un lotto, ogni sua azione fisica deve usare quel lotto. Una NC
di processo senza lotto può agire su lotti specificati nelle singole azioni.
Le azioni non fisiche non accettano parametri di magazzino.

## Verifiche, chiusura e produzione

Serve almeno un'azione prima della verifica. Possono esserci più verifiche:
la chiusura richiede che l'ultima sia EFFICACE e successiva a tutte le azioni.
Una nuova azione richiede quindi una nuova verifica. Inoltre devono essere
completate le rilavorazioni collegate e non devono rimanere quantità in quarantena.
La motivazione di chiusura è obbligatoria. Dopo CHIUSA non si aggiungono azioni
o verifiche e non si riapre il record: una nuova anomalia richiede una nuova NC.

Una verifica può essere descrittiva, oppure collegare una nuova misura conforme.
Se viene indicata una misura per una verifica efficace, deve essere successiva
all'ultima azione, riguardare la lavorazione della NC o una correttiva collegata,
e misurare lo stesso parametro della misura contestata, quando presente.
La verifica descrittiva è una valutazione esplicita di RQ, non una misura automatica.

Per gestire un controllo negativo, aprire la NC con controllo_qualita=misura:
la lavorazione viene associata automaticamente. Il risultato originale resta
non conforme. Il blocco al completamento della lavorazione o dell'unità si risolve
solo quando tutte le NC riferite esattamente a quella misura sono CHIUSE.
Una NC generica del lotto o della lavorazione non risolve indistintamente tutte
le misure negative. Una semplice ripetizione conforme continua a non bastare.
Restano obbligatori gli altri controlli, gli input/output e le fasi delle unità.
La chiusura NC non completa automaticamente lavorazioni o cicli e non cambia
lo stato delle lavorazioni interrotte.

## Verifica nel terminale VS Code

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_roles
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita
```

83 test senza database superati; modelli e migrazioni coerenti.
Suite completa predisposta: 389 test, inclusi rollback e concorrenza.
L'esecuzione MySQL della fase 9 è stata confermata dall'utente: 389 test superati.
