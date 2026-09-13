# Ricette — fase 4

## Modelli e regole

`Ricetta` descrive la formula di un singolo batch per un articolo. Campi:
articolo, nome, versione, attiva, note. Articolo/versione è univoco anche nel DB.
La versione è un codice testuale (ad esempio `1`, `2`, `1.1`). Non esiste
quantita_riferimento e non viene memorizzato il numero batch nella ricetta.

`RigaRicetta` contiene ricetta, articolo, quantita e note. Le nuove righe devono
sempre indicare un articolo preciso. Il campo categoria_articolo rimane nello
schema soltanto per leggere eventuali formule storiche; interfaccia, CSV e
RecipeService non consentono di creare nuove righe generiche.
Le quantità usano 18 cifre totali e 6 decimali, come il magazzino.

Nel frontend le righe si aggiungono e rimuovono senza ricaricare la pagina.
La scelta dell'articolo mostra la sua unità di misura; il riepilogo somma le
quantità per unità separata. Il form e RecipeService impediscono ingredienti
duplicati e una ricetta deve contenere almeno una riga.

## Permessi e Admin

- AMMINISTRATORE e RESPONSABILE_PRODUZIONE possono creare e modificare ricette e righe.
- I ruoli operativi possono consultarle; non ricevono permessi di modifica.
- Le ricette si disattivano dall'Admin. Non è disponibile la cancellazione della ricetta.
- Le righe di una formula non utilizzata si possono rimuovere; quelle storiche no.
- In Admin, aprire Produzione → Ricette. Le righe sono modificabili anche nella
  pagina della ricetta; l'articolo deve essere selezionato esplicitamente.

`bootstrap_roles` aggiorna i permessi dei nuovi modelli e va rilanciato dopo migrate.

## Versioni e storico

RecipeService.new_version copia la formula in una nuova ricetta e assegna la versione
richiesta. La copia è atomica: se una riga fallisce non rimane una ricetta parziale.
L'originale non cambia. La nuova versione nasce attiva; le versioni precedenti non
vengono disattivate automaticamente, perché possono essere ancora necessarie.

La proprietà `utilizzata` consulta la FK Lavorazione.ricetta, aggiunta nella fase 5.
Le regole predisposte vietano modifiche della formula, aggiunta/rimozione/modifica
righe e cancellazione dopo il primo utilizzo; resta consentito cambiare `attiva`.
Anche una ricetta storica può essere copiata in una nuova versione.
I test di fase 4 isolano questo controllo simulando l'utilizzo; la fase 5 aggiunge
il test con una lavorazione effettiva.

Le scritture di formula acquisiscono il lock della ricetta. La futura pianificazione
deve acquisire lo stesso lock prima di referenziarla. Aggiornamenti/cancellazioni
ORM massivi della formula sono bloccati; SQL arbitrario resta responsabilità degli
amministratori del database.

## Servizi

```python
from produzione.services import RecipeService

ricetta = RecipeService.create(
    actor=responsabile,
    articolo=prodotto,
    nome="Confettura",
    versione="1",
)
riga = RecipeService.add_line(
    actor=responsabile,
    ricetta=ricetta,
    articolo=fragole_gelo,
    quantita="25.000000",
)
RecipeService.update_line(actor=responsabile, riga=riga, quantita="26")
nuova = RecipeService.new_version(actor=responsabile, ricetta=ricetta, versione="2")
fabbisogni = RecipeService.requirements(actor=operatore, ricetta=nuova, numero_batch=3)
```

`requirements` restituisce una riga di risultato per ogni RigaRicetta con ID,
articolo, quantità per batch e quantità totale. Non aggrega righe diverse:
possono avere unità differenti. Non seleziona lotti, non
prenota stock e non crea ancora lavorazioni. La pianificazione dei batch arriverà
nei servizi produttivi successivi.

L'import CSV valida prima l'intero file: richiede almeno un ingrediente preciso
per ricetta, rifiuta duplicati e dati generali discordanti, quindi applica tutte
le modifiche in una transazione. Le categorie storiche restano visibili
nell'esportazione per permettere la conversione manuale.

## Verifica

Fase 4 verificata dall'utente su MySQL: 172 test passati. Durante lo sviluppo
erano passati anche 52 test senza DB. Comandi usati per la verifica:

```powershell
& "C:\gestionale\venv\Scripts\python.exe" manage.py migrate
& "C:\gestionale\venv\Scripts\python.exe" manage.py bootstrap_roles
& "C:\gestionale\venv\Scripts\python.exe" manage.py check --database default
& "C:\gestionale\venv\Scripts\python.exe" manage.py test accounts anagrafiche magazzino produzione
```
