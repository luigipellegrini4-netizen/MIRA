# Correzioni amministrative

La sezione **Correzioni** (`/configurazione/correzioni/`) richiede il permesso `auth.can_manage_backups`, assegnato al ruolo Amministratore e ai superuser. Ogni operazione richiede una motivazione e registra autore, data e valori prima/dopo.

- **Lotto:** codice, date e note tramite lo storico `CorrezioneLotto`.
- **Controlli:** valori consentiti per il tipo e associazioni tank–batch; l'esito viene ricalcolato dal modello. Una NC già aperta non viene eliminata automaticamente.
- **Giacenza:** nuovo movimento `RETTIFICA` nella posizione scelta; i movimenti precedenti restano intatti. Per il prodotto finito va scelto il componente confezionato o non confezionato.
- **Vendita:** dati del documento modificati con audit; la quantità di una riga viene corretta con un movimento compensativo e una `RettificaRigaVendita` storica. Le viste vendite e la genealogia mostrano la quantità effettiva.
- **Altre tabelle:** l'indice `/configurazione/correzioni/tabelle/` mostra i record del gestionale. I campi consentiti di anagrafiche, ricette e alcuni dati descrittivi si correggono con audit. Per gli altri record è disponibile un'annotazione motivata, senza modificare il dato originale; gli storici protetti richiedono una procedura specifica per alterare quantità o collegamenti.

Prima di usare la pagina in un database già avviato, eseguire `manage.py migrate`. I backup precedenti alla versione V4 restano importabili con gli storici delle nuove correzioni vuoti.
