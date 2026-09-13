# Verifica integrità dei dati

Il ripristino JSON è disponibile su MySQL e SQLite per gli utenti con il permesso amministrativo `can_manage_backups`.

Prima di cancellare i dati di destinazione MIRA verifica formato, campi, identificativi duplicati, riferimenti tra record (compresi i gruppi degli utenti), tipi di valore e corrispondenza dei saldi di magazzino per lotto e posizione. La sostituzione è transazionale: i vincoli del database e le relazioni vengono controllati prima del commit. Un errore annulla l'operazione.

Si possono ancora modificare nomi e descrizioni nel JSON. Un backup con giacenze non riconciliate viene rifiutato: non modificare i movimenti soltanto per superare la verifica. Questi controlli non sostituiscono la verifica delle regole produttive e di qualità.

Eseguire il ripristino durante una finestra senza altre operazioni: il file rappresenta uno stato completo che sostituisce quello presente.

## Controllo dei lotti invasettati

Comando di sola lettura:

```bash
python manage.py verifica_invasettati
```

In locale Windows utilizzare l'interprete del gestionale:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py verifica_invasettati
```

Il comando confronta i pezzi caricati con i vasetti buoni del riepilogo e i saldi delle singole posizioni con lo storico dei movimenti. Riporta ID, codice lotto e articolo per distinguere lotti omonimi. `COERENTE` significa che questi confronti sono soddisfatti, non che sia stata verificata fisicamente la giacenza.

La migrazione 0019 è stata resa prudente per le installazioni che non l'hanno ancora eseguita: converte solo un lotto con un unico movimento di produzione e un'unica giacenza nella stessa posizione. Non converte lotti trasferiti, consumati o con posizioni multiple.

Sulle installazioni che hanno già applicato 0019, `migrate` non la riesegue. Non forzare il ritorno alla migrazione precedente. Eseguire il comando di controllo e valutare ogni anomalia prima di una correzione. In questa fase non è stata introdotta alcuna riparazione automatica dei dati aziendali già migrati.

Validazione effettuata su SQLite di prova, inclusi backup operativi con giacenze, ripristino con gruppi utente, rifiuto di riferimenti mancanti e saldi incoerenti, rollback dopo collisione di unicità, conversione del lotto intatto e conservazione delle posizioni del lotto trasferito. La verifica runtime su MySQL rimane da eseguire in un ambiente di prova dedicato.
