# Verifica conclusiva fase 11 — 7 settembre 2026

Fonte: output PowerShell fornito dall'utente, allegato dc94e0bd-faa3-4e22-aa60-2317087e6045/pasted-text.txt, e FASE_11_RISULTATI.json.

- Migrazione produzione.0004 applicata: OK.
- seed_demo eseguito due volte: OK.
- Scenari A, B, C, D, E, F, G e STORICO: PASS.
- Check sul database default: nessun problema.
- Suite MySQL: 442 test superati in 33,128 secondi, inclusi i precedenti 418.
- Database di test creato ed eliminato al termine: OK.

Il primo comando senza interprete Python era stato rifiutato da PowerShell. Il successivo comando completo è riuscito: non è un errore del backend.

## Genealogia reale dello scenario A

Fornitore collaudo DEMO11, ID 1:

- Ricevimento 1, DDT DEMO11_F_A: 40 KG fragole, lotto DEMO11_F_A (ID 1), scadenza 2030-01-01.
- Ricevimento 3, DDT DEMO11_A_A: 1 KG acido, lotto DEMO11_A_A (ID 3), scadenza 2031-02-01.

Ciclo 1, lavorazione 1 PRODUZIONE_SEMILAVORATI, ricetta 1 versione 1:

- Riga ricetta 1 → input 1 → movimento consumo 10: 10 KG fragole dal lotto 1.
- Riga ricetta 2 → input 2 → movimento consumo 11: 0,050 KG acido dal lotto 3.
- Output 1 → movimento produzione 12 → lotto SL260907 (ID 10): 9,800 KG SEMILAVORATO FRAGOLA.

Lavorazione COMPLETATA. Input collegati direttamente alla ricetta, senza requisiti duplicati. Genealogia non troncata e senza cicli materiali. Questa fotografia precede la NC F: il verbale documenta separatamente i movimenti qualità successivi.

## Esito e punto di arresto

Fase 11 superata negli scenari previsti. Nessun ulteriore problema architetturale rilevato in questi scenari. Modifiche approvate: input da ricetta alternativi ai requisiti strutturali, conferma atomica, verifica copertura e articolo principale dalla ricetta. Nessuna migrazione storica modificata.

Dataset iniziale: 7 utenti, 5 categorie, 3 articoli, 1 fornitore, 5 ubicazioni, 9 lotti acquistati e ricetta Fragola v1. Il collaudo aggiunge 3 lotti prodotti e le registrazioni nel verbale.

Prima della UI concordare tolleranze dei consumi, parametri qualità aziendali e flusso di conteggio. Il controllo demo è tecnico; il conteggio non crea un documento inventariale dedicato. Fase 12 non avviata.
