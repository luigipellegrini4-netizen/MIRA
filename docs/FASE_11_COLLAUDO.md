# Fase 11 — verbale funzionale DEMO11

Esecuzione originale: 2026-09-07T12:35:44.778965+00:00

Il rilancio ripubblica questo verbale storico; non ripete i consumi.
Verifica successiva: 442 test MySQL superati in 33,128 s; check senza problemi. Vedere [verifica conclusiva](FASE_11_VERIFICA_MYSQL.md).

## Scenario A: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "ciclo_id": 1,
    "lavorazione_id": 1,
    "input_ids": [
      1,
      2
    ],
    "output_id": 1,
    "lotto_id": 10,
    "proposti_ids": [
      1,
      3
    ],
    "lotti_effettivi_ids": [
      1,
      3
    ],
    "quantita_reale": "9.800",
    "genealogia": {
      "versione": 1,
      "lotto_radice_id": 10,
      "direzione": "MONTE",
      "generato_il": "2026-09-07T12:35:45.006835+00:00",
      "max_lotti": 1000,
      "troncato": false,
      "frontiera_omessa_ids": [],
      "ciclo_materiale_rilevato": false,
      "lotti": [
        {
          "id": 1,
          "nodo": "lotto:1",
          "codice": "DEMO11_F_A",
          "tipo": "ACQUISTO",
          "articolo_id": 1,
          "articolo_codice": "DEMO11_FRAGOLE",
          "unita_misura": "KG",
          "fornitore_id": 1,
          "fornitore": "Fornitore collaudo DEMO11",
          "data_produzione": null,
          "data_scadenza": "2030-01-01",
          "lavorazione_origine_id": null
        },
        {
          "id": 3,
          "nodo": "lotto:3",
          "codice": "DEMO11_A_A",
          "tipo": "ACQUISTO",
          "articolo_id": 2,
          "articolo_codice": "DEMO11_ACIDO",
          "unita_misura": "KG",
          "fornitore_id": 1,
          "fornitore": "Fornitore collaudo DEMO11",
          "data_produzione": null,
          "data_scadenza": "2031-02-01",
          "lavorazione_origine_id": null
        },
        {
          "id": 10,
          "nodo": "lotto:10",
          "codice": "SL260907",
          "tipo": "PRODUZIONE",
          "articolo_id": 3,
          "articolo_codice": "DEMO11_SEMILAVORATO",
          "unita_misura": "KG",
          "fornitore_id": null,
          "fornitore": null,
          "data_produzione": "2026-09-07",
          "data_scadenza": null,
          "lavorazione_origine_id": 1
        }
      ],
      "lavorazioni": [
        {
          "id": 1,
          "nodo": "lavorazione:1",
          "ciclo_id": 1,
          "tipo_id": 9,
          "tipo_codice": "PRODUZIONE_SEMILAVORATI",
          "stato": "COMPLETATA",
          "ricetta_id": 1,
          "versione_ricetta": "1",
          "inizio": "2026-09-07T12:35:44.811271+00:00",
          "fine": "2026-09-07T12:35:44.986315+00:00",
          "ruolo": "MATERIALE"
        }
      ],
      "legami_materiali": [
        {
          "tipo": "CONSUMO",
          "da": "lotto:1",
          "a": "lavorazione:1",
          "input_id": 1,
          "riga_ricetta_id": 1,
          "requisito_input_id": null,
          "quantita": "10.000000",
          "movimenti_ids": [
            10
          ]
        },
        {
          "tipo": "CONSUMO",
          "da": "lotto:3",
          "a": "lavorazione:1",
          "input_id": 2,
          "riga_ricetta_id": 2,
          "requisito_input_id": null,
          "quantita": "0.050000",
          "movimenti_ids": [
            11
          ]
        },
        {
          "tipo": "PRODUZIONE",
          "da": "lavorazione:1",
          "a": "lotto:10",
          "output_id": 1,
          "quantita": "9.800000",
          "movimenti_ids": [
            12
          ],
          "output_registrato": true
        }
      ],
      "ricevimenti": [
        {
          "id": 1,
          "lotto_id": 1,
          "quantita": "40.000000",
          "data": "2026-01-01T09:00:00+00:00",
          "numero_ddt": "DEMO11_F_A",
          "numero_fattura": ""
        },
        {
          "id": 3,
          "lotto_id": 3,
          "quantita": "1.000000",
          "data": "2026-01-01T09:00:00+00:00",
          "numero_ddt": "DEMO11_A_A",
          "numero_fattura": ""
        }
      ],
      "unita": [],
      "partecipazioni": [],
      "risorse_utilizzate": [],
      "controlli": [],
      "non_conformita": []
    }
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "40.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "40.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "1.000000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "1.000000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "6.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "8.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "1.000000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "40.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "1.000000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "6.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "8.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "1.000000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "movimenti": [
    {
      "id": 10,
      "tipo": "CONSUMO",
      "lotto_id": 1,
      "quantita": "10.000000",
      "origine_id": 1,
      "destinazione_id": null
    },
    {
      "id": 11,
      "tipo": "CONSUMO",
      "lotto_id": 3,
      "quantita": "0.050000",
      "origine_id": 1,
      "destinazione_id": null
    },
    {
      "id": 12,
      "tipo": "PRODUZIONE",
      "lotto_id": 10,
      "quantita": "9.800000",
      "origine_id": null,
      "destinazione_id": 4
    }
  ]
}
```

## Scenario B: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "ciclo_id": 2,
    "lavorazione_id": 2,
    "input_ids": [
      3,
      4
    ],
    "output_id": 2,
    "lotto_id": 11,
    "proposti_ids": [
      1,
      3
    ],
    "lotti_effettivi_ids": [
      2,
      4
    ],
    "quantita_reale": "9.800",
    "genealogia": {
      "versione": 1,
      "lotto_radice_id": 11,
      "direzione": "MONTE",
      "generato_il": "2026-09-07T12:35:45.227964+00:00",
      "max_lotti": 1000,
      "troncato": false,
      "frontiera_omessa_ids": [],
      "ciclo_materiale_rilevato": false,
      "lotti": [
        {
          "id": 2,
          "nodo": "lotto:2",
          "codice": "DEMO11_F_B",
          "tipo": "ACQUISTO",
          "articolo_id": 1,
          "articolo_codice": "DEMO11_FRAGOLE",
          "unita_misura": "KG",
          "fornitore_id": 1,
          "fornitore": "Fornitore collaudo DEMO11",
          "data_produzione": null,
          "data_scadenza": "2030-02-01",
          "lavorazione_origine_id": null
        },
        {
          "id": 4,
          "nodo": "lotto:4",
          "codice": "DEMO11_A_B",
          "tipo": "ACQUISTO",
          "articolo_id": 2,
          "articolo_codice": "DEMO11_ACIDO",
          "unita_misura": "KG",
          "fornitore_id": 1,
          "fornitore": "Fornitore collaudo DEMO11",
          "data_produzione": null,
          "data_scadenza": "2031-01-01",
          "lavorazione_origine_id": null
        },
        {
          "id": 11,
          "nodo": "lotto:11",
          "codice": "SL260907-A",
          "tipo": "PRODUZIONE",
          "articolo_id": 3,
          "articolo_codice": "DEMO11_SEMILAVORATO",
          "unita_misura": "KG",
          "fornitore_id": null,
          "fornitore": null,
          "data_produzione": "2026-09-07",
          "data_scadenza": null,
          "lavorazione_origine_id": 2
        }
      ],
      "lavorazioni": [
        {
          "id": 2,
          "nodo": "lavorazione:2",
          "ciclo_id": 2,
          "tipo_id": 9,
          "tipo_codice": "PRODUZIONE_SEMILAVORATI",
          "stato": "COMPLETATA",
          "ricetta_id": 1,
          "versione_ricetta": "1",
          "inizio": "2026-09-07T12:35:45.064706+00:00",
          "fine": "2026-09-07T12:35:45.212823+00:00",
          "ruolo": "MATERIALE"
        }
      ],
      "legami_materiali": [
        {
          "tipo": "CONSUMO",
          "da": "lotto:2",
          "a": "lavorazione:2",
          "input_id": 3,
          "riga_ricetta_id": 1,
          "requisito_input_id": null,
          "quantita": "10.000000",
          "movimenti_ids": [
            13
          ]
        },
        {
          "tipo": "CONSUMO",
          "da": "lotto:4",
          "a": "lavorazione:2",
          "input_id": 4,
          "riga_ricetta_id": 2,
          "requisito_input_id": null,
          "quantita": "0.050000",
          "movimenti_ids": [
            14
          ]
        },
        {
          "tipo": "PRODUZIONE",
          "da": "lavorazione:2",
          "a": "lotto:11",
          "output_id": 2,
          "quantita": "9.800000",
          "movimenti_ids": [
            15
          ],
          "output_registrato": true
        }
      ],
      "ricevimenti": [
        {
          "id": 2,
          "lotto_id": 2,
          "quantita": "40.000000",
          "data": "2026-01-02T09:00:00+00:00",
          "numero_ddt": "DEMO11_F_B",
          "numero_fattura": ""
        },
        {
          "id": 4,
          "lotto_id": 4,
          "quantita": "1.000000",
          "data": "2026-01-02T09:00:00+00:00",
          "numero_ddt": "DEMO11_A_B",
          "numero_fattura": ""
        }
      ],
      "unita": [],
      "partecipazioni": [],
      "risorse_utilizzate": [],
      "controlli": [],
      "non_conformita": []
    }
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "40.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "1.000000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "6.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "8.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "1.000000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "6.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "8.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "1.000000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "movimenti": [
    {
      "id": 13,
      "tipo": "CONSUMO",
      "lotto_id": 2,
      "quantita": "10.000000",
      "origine_id": 1,
      "destinazione_id": null
    },
    {
      "id": 14,
      "tipo": "CONSUMO",
      "lotto_id": 4,
      "quantita": "0.050000",
      "origine_id": 1,
      "destinazione_id": null
    },
    {
      "id": 15,
      "tipo": "PRODUZIONE",
      "lotto_id": 11,
      "quantita": "9.800000",
      "origine_id": null,
      "destinazione_id": 4
    }
  ]
}
```

## Scenario C: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "ciclo_id": 3,
    "lavorazione_id": 3,
    "input_ids": [
      5,
      6,
      7
    ],
    "output_id": 3,
    "lotto_id": 12,
    "proposti_ids": [
      5,
      6,
      7
    ],
    "lotti_effettivi_ids": [
      5,
      6,
      7
    ],
    "quantita_reale": "9.800",
    "genealogia": {
      "versione": 1,
      "lotto_radice_id": 12,
      "direzione": "MONTE",
      "generato_il": "2026-09-07T12:35:45.458745+00:00",
      "max_lotti": 1000,
      "troncato": false,
      "frontiera_omessa_ids": [],
      "ciclo_materiale_rilevato": false,
      "lotti": [
        {
          "id": 5,
          "nodo": "lotto:5",
          "codice": "DEMO11_FC_A",
          "tipo": "ACQUISTO",
          "articolo_id": 1,
          "articolo_codice": "DEMO11_FRAGOLE",
          "unita_misura": "KG",
          "fornitore_id": 1,
          "fornitore": "Fornitore collaudo DEMO11",
          "data_produzione": null,
          "data_scadenza": "2030-01-01",
          "lavorazione_origine_id": null
        },
        {
          "id": 6,
          "nodo": "lotto:6",
          "codice": "DEMO11_FC_B",
          "tipo": "ACQUISTO",
          "articolo_id": 1,
          "articolo_codice": "DEMO11_FRAGOLE",
          "unita_misura": "KG",
          "fornitore_id": 1,
          "fornitore": "Fornitore collaudo DEMO11",
          "data_produzione": null,
          "data_scadenza": "2030-02-01",
          "lavorazione_origine_id": null
        },
        {
          "id": 7,
          "nodo": "lotto:7",
          "codice": "DEMO11_AC",
          "tipo": "ACQUISTO",
          "articolo_id": 2,
          "articolo_codice": "DEMO11_ACIDO",
          "unita_misura": "KG",
          "fornitore_id": 1,
          "fornitore": "Fornitore collaudo DEMO11",
          "data_produzione": null,
          "data_scadenza": "2031-01-01",
          "lavorazione_origine_id": null
        },
        {
          "id": 12,
          "nodo": "lotto:12",
          "codice": "SL260907-B",
          "tipo": "PRODUZIONE",
          "articolo_id": 3,
          "articolo_codice": "DEMO11_SEMILAVORATO",
          "unita_misura": "KG",
          "fornitore_id": null,
          "fornitore": null,
          "data_produzione": "2026-09-07",
          "data_scadenza": null,
          "lavorazione_origine_id": 3
        }
      ],
      "lavorazioni": [
        {
          "id": 3,
          "nodo": "lavorazione:3",
          "ciclo_id": 3,
          "tipo_id": 9,
          "tipo_codice": "PRODUZIONE_SEMILAVORATI",
          "stato": "COMPLETATA",
          "ricetta_id": 1,
          "versione_ricetta": "1",
          "inizio": "2026-09-07T12:35:45.269296+00:00",
          "fine": "2026-09-07T12:35:45.444221+00:00",
          "ruolo": "MATERIALE"
        }
      ],
      "legami_materiali": [
        {
          "tipo": "CONSUMO",
          "da": "lotto:5",
          "a": "lavorazione:3",
          "input_id": 5,
          "riga_ricetta_id": 1,
          "requisito_input_id": null,
          "quantita": "6.000000",
          "movimenti_ids": [
            16
          ]
        },
        {
          "tipo": "CONSUMO",
          "da": "lotto:6",
          "a": "lavorazione:3",
          "input_id": 6,
          "riga_ricetta_id": 1,
          "requisito_input_id": null,
          "quantita": "4.000000",
          "movimenti_ids": [
            17
          ]
        },
        {
          "tipo": "CONSUMO",
          "da": "lotto:7",
          "a": "lavorazione:3",
          "input_id": 7,
          "riga_ricetta_id": 2,
          "requisito_input_id": null,
          "quantita": "0.050000",
          "movimenti_ids": [
            18
          ]
        },
        {
          "tipo": "PRODUZIONE",
          "da": "lavorazione:3",
          "a": "lotto:12",
          "output_id": 3,
          "quantita": "9.800000",
          "movimenti_ids": [
            19
          ],
          "output_registrato": true
        }
      ],
      "ricevimenti": [
        {
          "id": 5,
          "lotto_id": 5,
          "quantita": "6.000000",
          "data": "2026-01-01T09:00:00+00:00",
          "numero_ddt": "DEMO11_FC_A",
          "numero_fattura": ""
        },
        {
          "id": 6,
          "lotto_id": 6,
          "quantita": "8.000000",
          "data": "2026-01-02T09:00:00+00:00",
          "numero_ddt": "DEMO11_FC_B",
          "numero_fattura": ""
        },
        {
          "id": 7,
          "lotto_id": 7,
          "quantita": "1.000000",
          "data": "2026-01-01T09:00:00+00:00",
          "numero_ddt": "DEMO11_AC",
          "numero_fattura": ""
        }
      ],
      "unita": [],
      "partecipazioni": [],
      "risorse_utilizzate": [],
      "controlli": [],
      "non_conformita": []
    }
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "6.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "8.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "1.000000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "movimenti": [
    {
      "id": 16,
      "tipo": "CONSUMO",
      "lotto_id": 5,
      "quantita": "6.000000",
      "origine_id": 2,
      "destinazione_id": null
    },
    {
      "id": 17,
      "tipo": "CONSUMO",
      "lotto_id": 6,
      "quantita": "4.000000",
      "origine_id": 2,
      "destinazione_id": null
    },
    {
      "id": 18,
      "tipo": "CONSUMO",
      "lotto_id": 7,
      "quantita": "0.050000",
      "origine_id": 2,
      "destinazione_id": null
    },
    {
      "id": 19,
      "tipo": "PRODUZIONE",
      "lotto_id": 12,
      "quantita": "9.800000",
      "origine_id": null,
      "destinazione_id": 4
    }
  ]
}
```

## Scenario D: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "lavorazione_id": 4,
    "esito_atteso": "Consumi annullati; nessun output",
    "input_creati": 0
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "movimenti": []
}
```

## Scenario E: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "tipo": "Controllo DEMO tecnico separato, non parametro aziendale",
    "controlli_ids": [
      1,
      2
    ],
    "lavorazioni_ids": [
      5,
      6
    ]
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "movimenti": []
}
```

## Scenario F: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "nc_id": 1,
    "azioni_ids": [
      1,
      2,
      3
    ],
    "verifica_id": 1
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.300000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 13,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_QUARANTENA",
      "quantita": "0.000000"
    }
  ],
  "movimenti": [
    {
      "id": 21,
      "tipo": "QUARANTENA",
      "lotto_id": 10,
      "quantita": "2.000000",
      "origine_id": 4,
      "destinazione_id": 5
    },
    {
      "id": 22,
      "tipo": "REINTEGRO",
      "lotto_id": 10,
      "quantita": "1.500000",
      "origine_id": 5,
      "destinazione_id": 4
    },
    {
      "id": 23,
      "tipo": "SCARTO",
      "lotto_id": 10,
      "quantita": "0.500000",
      "origine_id": 5,
      "destinazione_id": null
    }
  ]
}
```

## Scenario G: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "movimento_id": 24,
    "conteggio": "Confronto tecnico simulato e permesso verificato; nessun documento inventariale dedicato"
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.300000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 13,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_QUARANTENA",
      "quantita": "0.000000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "29.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.300000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 13,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_QUARANTENA",
      "quantita": "0.000000"
    }
  ],
  "movimenti": [
    {
      "id": 24,
      "tipo": "RETTIFICA",
      "lotto_id": 1,
      "quantita": "1.000000",
      "origine_id": 1,
      "destinazione_id": null
    }
  ]
}
```

## Scenario STORICO: PASS

Dati iniziali, operazioni/record e saldi effettivi:

```json
{
  "esito": "PASS",
  "dettagli": {
    "record_verificati": [
      {
        "modello": "Lavorazione",
        "id": 1
      },
      {
        "modello": "InputLavorazione",
        "id": 1
      },
      {
        "modello": "OutputLavorazione",
        "id": 1
      },
      {
        "modello": "Movimento",
        "id": 12
      },
      {
        "modello": "ControlloQualita",
        "id": 1
      },
      {
        "modello": "ControlloQualita",
        "id": 2
      }
    ]
  },
  "giacenze_prima": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "29.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.300000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 13,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_QUARANTENA",
      "quantita": "0.000000"
    }
  ],
  "giacenze_dopo": [
    {
      "id": 1,
      "lotto_id": 1,
      "lotto": "DEMO11_F_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "29.000000"
    },
    {
      "id": 2,
      "lotto_id": 2,
      "lotto": "DEMO11_F_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "30.000000"
    },
    {
      "id": 3,
      "lotto_id": 3,
      "lotto": "DEMO11_A_A",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 4,
      "lotto_id": 4,
      "lotto": "DEMO11_A_B",
      "ubicazione": "DEMO11_MAG",
      "quantita": "0.950000"
    },
    {
      "id": 5,
      "lotto_id": 5,
      "lotto": "DEMO11_FC_A",
      "ubicazione": "DEMO11_C",
      "quantita": "0.000000"
    },
    {
      "id": 6,
      "lotto_id": 6,
      "lotto": "DEMO11_FC_B",
      "ubicazione": "DEMO11_C",
      "quantita": "4.000000"
    },
    {
      "id": 7,
      "lotto_id": 7,
      "lotto": "DEMO11_AC",
      "ubicazione": "DEMO11_C",
      "quantita": "0.950000"
    },
    {
      "id": 8,
      "lotto_id": 8,
      "lotto": "DEMO11_FD",
      "ubicazione": "DEMO11_D",
      "quantita": "10.000000"
    },
    {
      "id": 9,
      "lotto_id": 9,
      "lotto": "DEMO11_AD",
      "ubicazione": "DEMO11_D",
      "quantita": "0.010000"
    },
    {
      "id": 10,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.300000"
    },
    {
      "id": 11,
      "lotto_id": 11,
      "lotto": "SL260907-A",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 12,
      "lotto_id": 12,
      "lotto": "SL260907-B",
      "ubicazione": "DEMO11_BUFFER_PRODUZIONE",
      "quantita": "9.800000"
    },
    {
      "id": 13,
      "lotto_id": 10,
      "lotto": "SL260907",
      "ubicazione": "DEMO11_QUARANTENA",
      "quantita": "0.000000"
    }
  ],
  "movimenti": []
}
```

## Problemi architetturali emersi dal collaudo

È stata applicata la modifica approvata: input da RigaRicetta alternativi ai requisiti strutturali, conferma ingredienti atomica e articolo principale da ricetta.
Nessun ulteriore problema rilevato negli scenari eseguiti.
I conteggi dello scenario G sono confronti tecnici simulati; non esiste un documento inventariale dedicato. I controlli E sono esplicitamente DEMO, non parametri aziendali.

## Dati demo e utenti

```json
{
  "eseguito_il": "2026-09-07T12:35:44.778965+00:00",
  "problemi_architetturali": [],
  "utenti": {
    "admin": {
      "id": 2,
      "username": "demo11_admin"
    },
    "produzione": {
      "id": 3,
      "username": "demo11_produzione"
    },
    "magazzino": {
      "id": 4,
      "username": "demo11_magazzino"
    },
    "qualita": {
      "id": 5,
      "username": "demo11_qualita"
    },
    "operatore": {
      "id": 6,
      "username": "demo11_operatore"
    },
    "magazziniere": {
      "id": 7,
      "username": "demo11_magazziniere"
    },
    "multi": {
      "id": 8,
      "username": "demo11_multi"
    }
  },
  "articoli": {
    "FRAGOLE": 1,
    "ACIDO": 2,
    "SEMILAVORATO": 3
  },
  "ricetta_id": 1
}
```

## Prima della UI

Verifica MySQL completata con successo. Restano da concordare eventuali scostamenti degli ingredienti, parametri qualità aziendali e modalità di registrazione dei conteggi. Nessuna UI o fase 12 avviata.

