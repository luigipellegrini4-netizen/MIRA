# Fase 8 — risorse e unità operative

La fase 7 è stata verificata dall'utente su MySQL: 295 test superati.
Questa fase aggiunge RisorsaProduttiva, RisorsaLavorazione, UnitaLavorazione,
PartecipazioneUnitaLavorazione e RequisitoFaseUnitaTipoLavorazione.
Le risorse non sono ubicazioni. La creazione, la partecipazione e la chiusura
delle unità non modificano giacenze e non generano movimenti.

## Configurazione

1. Configurare i tipi di trattamento con genera_lotto=False, inclusi input di
   eventuali materiali consumabili e controlli qualità.
2. Configurare il tipo origine con genera_lotto=True e i requisiti output.
3. Aggiungere le fasi al percorso del tipo origine, indicando tipo_fase, ordine
   e obbligatorio. Ogni tipo fase e ogni ordine sono unici nel percorso.
4. Pianificare le lavorazioni.

Il percorso si congela alla prima lavorazione origine pianificata. Le definizioni
dei trattamenti e dei loro controlli si congelano già quando vengono collegate
a un percorso: configurarle prima del collegamento. Per cambiare un processo
utilizzato, creare nuovi tipi/configurazioni. Il flag attivo resta modificabile.
Nessuna regola contiene nomi di macchine o processi specifici.

## Flusso dei carrelli

```python
from produzione.services import OutputService, WorkUnitService, ResourceService
from produzione.selectors import UnitSelector

# L'origine deve essere IN_CORSO. L'identità INV può precedere lo stock.
lotto = OutputService.prepare_lot(
    actor=operatore, lavorazione=origine, requisito_output=requisito,
    articolo=articolo,
)
unita = WorkUnitService.create(
    actor=operatore, lavorazione_origine=origine, lotto=lotto,
    risorsa_produttiva=carrello, codice="U1", quantita=None,
)
ResourceService.assign(actor=operatore, lavorazione=trattamento,
                       risorsa_produttiva=macchina)
WorkUnitService.participate(actor=operatore, unita_lavorazione=unita,
                            lavorazione=trattamento)
# Registrare i controlli qualità e completare il trattamento con WorkExecutionService.
# Ripetere per ogni fase richiesta, rispettando l'ordine.
WorkUnitService.close(actor=operatore, unita_lavorazione=unita)
stato = UnitSelector.detail(actor=operatore, unita_lavorazione=unita)
# Consolidare l'output reale con OutputService.register(lotto=lotto, ...),
# quindi completare la lavorazione origine.
```

ResourceService.assign richiede un trattamento già IN_CORSO. Unità e partecipazioni
richiedono RP/OP; assegnazione risorse RP/OP. Anagrafiche risorse e percorsi sono
configurabili da A/RP. Tutti i ruoli operativi possono consultare unità e storico.
L'Admin offre configurazione e consultazione; le operazioni nuove usano i servizi Python.

Una risorsa associata a un'unità resta occupata fino alla chiusura dell'unità.
Le macchine possono essere registrate su più lavorazioni: l'assegnazione documenta
l'attrezzatura usata, non implementa un calendario di prenotazioni.
Un'unità non può partecipare a due trattamenti contemporaneamente.
Origine e trattamento devono essere in corso; possono appartenere a cicli diversi.
Nessuna partecipazione può essere aggiunta retroattivamente a una lavorazione chiusa.

Le fasi obbligatorie precedenti devono essere completate prima di iniziare la
partecipazione alla successiva. Ogni fase configurata per unità richiede almeno
una partecipazione prima di essere completata. Più unità possono partecipare
allo stesso trattamento: i suoi controlli qualità riguardano quella lavorazione.
Una ripetizione è una nuova lavorazione e conserva il tentativo precedente.
Un esito qualità determinante non conforme resta bloccante per l'unità anche
se il trattamento viene interrotto e ripetuto: richiede la gestione NC descritta
in [NON_CONFORMITA.md](NON_CONFORMITA.md).
Un trattamento interrotto non soddisfa il requisito; la risoluzione dello stato
del ciclo e delle non conformità resta parte del successivo lavoro sulle NC.

Per chiudere l'origine occorrono tutte le unità chiuse, tutte le fasi obbligatorie
completate e un output consolidato per ogni lotto rappresentato dalle unità.
Le quantità note delle unità non possono superare l'output; null significa
quantità non rilevata e non viene interpretato come zero fisico. Non è richiesta
l'uguaglianza: possono esistere quantità non assegnate alle unità.
Se l'output esiste già, il limite viene verificato anche alla creazione dell'unità.

I servizi usano transazioni e lock ordinati, condivisi con l'esecuzione produttiva.
Lo storico di partecipazioni e risorse è immutabile; per l'unità è prevista solo
la transizione ATTIVA → CHIUSA. Non è previsto uno sblocco manuale dei vincoli qualità.

## Verifica MySQL

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_roles
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita
```

Sono incluse prove del percorso con più carrelli, qualità, quantità, permessi,
storico, ordine delle fasi e concorrenza su assegnazione risorsa/chiusura trattamento.
L'esecuzione MySQL della fase 8 è stata confermata dall'utente: 339 test superati.
Verifica locale: 77 test senza database superati; nessuna migrazione mancante.
Suite completa predisposta: 339 test, inclusi quelli delle fasi precedenti.
