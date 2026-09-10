# Struttura produttiva — fase 5

## Stato

La fase 4 è stata verificata dall'utente: 172 test passati su MySQL.
La fase 5 è stata verificata dall'utente: 219 test passati su MySQL.
I servizi produttivi sono ora predisposti nella fase 6 e descritti in ESECUZIONE.md;
la relativa suite estesa resta da eseguire. Qualità, unità e consultazione genealogica
seguiranno nelle fasi previste.

## Configurazione generica

- TipoLavorazione: codice, nome, genera_lotto, attivo, note.
- RequisitoInputTipoLavorazione: articolo oppure categoria, eventualmente
  combinati con tipo_lavorazione_origine. È obbligatorio almeno un filtro.
  Quando sono indicati origine e articolo/categoria devono risultare veri entrambi.
- RequisitoOutputTipoLavorazione: esattamente un articolo o categoria,
  tipo PRINCIPALE/SECONDARIO e prefisso_lotto opzionale.
- Categoria include sempre i suoi discendenti. multiplo=False ammette una sola
  registrazione per quel requisito nella lavorazione; multiplo=True ne ammette più.
- I requisiti di output sono vietati quando genera_lotto=False.
- Dopo il primo utilizzo, tipo e requisiti sono protetti da modifiche della
  configurazione. Per cambiare il processo, creare un nuovo tipo/configurazione.
  Resta consentito disattivare il tipo.

Non esistono classi dedicate a Roboqbo, tank o invasettamento. Il comando:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_process_types
```

crea gli otto tipi concordati senza sovrascrivere configurazioni esistenti.
I requisiti vanno configurati con gli articoli/categorie reali nell'Admin.
Macchine, tank e carrelli come risorse, unità e percorso richiesto delle unità
restano nella fase 8; non vengono simulati tramite ubicazioni.

## Esecuzione e storico

CicloProduzione e Lavorazione contengono gli stati concordati, gli utenti e le date.
Non contengono quantità/resa/lotto finale duplicati. Date e stati hanno vincoli DB:
una lavorazione annullata non è mai iniziata; una interrotta ha inizio e fine;
una completata ha entrambi gli orari. Una fine non può precedere l'inizio.
La data_chiusura del ciclo è valorizzata quando il ciclo è completato o annullato.

Le transizioni richiedono i servizi della fase 6. Il contesto privato
`_execution_write` è riservato a quei servizi e ai test di schema; non costituisce
un endpoint operativo. I test che lo usano verificano i vincoli di stato, non
il soddisfacimento di tutti i requisiti di completamento della futura fase 6/7/8.
Lavorazioni e cicli terminati non sono liberamente modificabili o cancellabili.

La FK Lavorazione.ricetta rende ora effettiva la protezione delle formule usate:
i nuovi test la verificano con una lavorazione reale, non soltanto simulandola.
La creazione/scrittura acquisisce lock tipo → ricetta → ciclo → lavorazione;
i servizi futuri devono rispettare lo stesso ordine per evitare inversioni.

## Input, output e lotti

InputLavorazione e OutputLavorazione sono registrazioni storiche immutabili,
con quantità positiva, ammesse solo su una lavorazione IN_CORSO. Il modello
non modifica giacenze: i servizi della fase 6 registreranno anche i movimenti.
Una lavorazione non può consumare un lotto di cui è essa stessa l'origine.

OutputLavorazione richiede un lotto PRODUZIONE proveniente dalla stessa lavorazione,
un requisito compatibile e genera_lotto=True. I processi senza nuovo lotto non
possono produrre output artificiali.

Lotto.lavorazione_origine è una FK nullable PROTECT: l'identità di un lotto
intermedio può esistere prima di OutputLavorazione, senza creare quantità fittizie.
I filtri di origine consultano questa FK e non richiedono output già consolidati.
I lotti già registrati senza origine rimangono validi; il futuro OutputService
imposterà l'origine dei nuovi lotti produttivi.

Movimento.input_lavorazione e output_lavorazione sono nullable e mutuamente
esclusivi. Se presenti devono corrispondere rispettivamente a CONSUMO e PRODUZIONE,
allo stesso lotto e a una lavorazione in corso. I consumi di magazzino già esistenti
senza input restano validi; InputService collegherà sempre i propri consumi.

MovementService.register accetta ora input_lavorazione per consumi collegati:
blocca prima la lavorazione, poi lotto/ubicazioni/giacenze. Ammette più movimenti
per lo stesso input ma impedisce che la somma superi la quantità registrata.
L'uguaglianza esatta sarà verificata alla chiusura dalla fase 6.
La produzione fisica degli output resta riservata al futuro OutputService.

## Admin e permessi

Tipi e requisiti si configurano nell'Admin da AMMINISTRATORE e RP.
I ruoli operativi li consultano. Cicli, lavorazioni, input e output sono per ora
consultivi: i permessi operativi restano quelli custom già definiti, che verranno
applicati dai servizi. L'Admin non consente transizioni o inserimenti manuali che
aggirino le riconciliazioni tra registrazioni produttive e stock.

## Migration e verifica

La migration produzione.0002 dipende da magazzino.0001 (Lotto esiste già).
magazzino.0002 aggiunge successivamente le FK verso produzione.0002.
Il grafo è stato verificato senza cicli. Le migration aggiungono strutture e
campi nullable; non riscrivono lotti o movimenti preesistenti.

Nel terminale PowerShell di VS Code, eseguire uno alla volta, fermandosi all'errore:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_roles
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_process_types
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione
```
