# Fase 7 — controlli qualità

La fase 6 è stata verificata dall'utente su MySQL: 271 test superati.
La fase 7 aggiunge parametri tipizzati, controlli richiesti e misurazioni storiche.
I limiti appartengono al controllo del tipo di lavorazione, mai al parametro.
Le configurazioni del processo si congelano alla prima lavorazione pianificata;
un parametro già collegato a un controllo conserva significato e unità di misura.
Per cambiare il processo si crea una nuova configurazione.

Numeri: limiti inclusivi, valori negativi e zero ammessi; niente float, NaN o infinito.
Booleani: usare True/False reali. Testi: valore non vuoto ed esito conforme esplicito.
Per numeri e booleani l'esito è calcolato e non può essere forzato.
Un controllo numerico determinante deve avere almeno un limite; un booleano
determinante richiede il valore atteso. Il testo usa la valutazione dell'esecutore.

```python
from qualita.services import QualityService
misura = QualityService.record(
    actor=utente, lavorazione=lavorazione, controllo_richiesto=controllo,
    valore="82.5", note="Misurazione al termine del trattamento",
)
```

Registrazione solo IN_CORSO per RP, RQ, OP; autore e orario sono assegnati dal servizio.
La transazione usa gli stessi lock della chiusura: una misura non può inserirsi
durante una chiusura già confermata. Ogni ripetizione aggiunge una riga immutabile.
Il parametro disattivato non è selezionabile per nuove configurazioni, ma i controlli
già configurati restano eseguibili e obbligatori.

La chiusura richiede tutti i controlli obbligatori. Qualsiasi esito storico non conforme
determinante blocca la chiusura, anche dopo una ripetizione conforme; i controlli
informativi possono risultare non conformi senza bloccare. La gestione esplicita delle
NC è implementata nella fase 9: vedere [NON_CONFORMITA.md](NON_CONFORMITA.md).
Solo la chiusura esplicita delle NC riferite alla misura risolve il suo blocco.

Admin: parametri configurabili da A/RQ, controlli richiesti da A/RP/RQ;
misurazioni consultabili dai ruoli operativi e registrabili attraverso il servizio.
AMMINISTRATORE non riceve permessi operativi. Nessun movimento di magazzino è generato.

Verifica MySQL da eseguire nella cartella MIRA:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_roles
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione qualita
```
