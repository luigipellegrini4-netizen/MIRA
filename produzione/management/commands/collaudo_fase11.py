import json
from pathlib import Path
from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.management.base import BaseCommand, CommandError
from produzione.services.demo_collation import run_demo, CollationFailure


class Command(BaseCommand):
    help = "Esegue il collaudo DEMO11 e genera il verbale. Rilanci: ristampa il verbale originale senza duplicare operazioni."

    def handle(self, *args, **options):
        failure = None
        try:
            result = run_demo()
        except CollationFailure as exc:
            result, failure = exc.report, exc
        except ValidationError as exc:
            raise CommandError("; ".join(exc.messages) + " Operazioni del tentativo annullate.") from exc
        docs = Path(settings.BASE_DIR) / "docs"
        docs.mkdir(exist_ok=True)
        (docs / "FASE_11_RISULTATI.json").write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
        text = ["# Fase 11 — verbale funzionale DEMO11", "", f"Esecuzione originale: {result['eseguito_il']}",
            "", result.get("nota_rollback", "Il rilancio ripubblica questo verbale storico; non ripete i consumi."),
            "La verifica dell'intera suite MySQL va eseguita separatamente dopo il collaudo.", ""]
        for code, scenario in result["scenari"].items():
            style = self.style.ERROR if scenario["esito"] == "FAIL" else self.style.SUCCESS
            self.stdout.write(style(f"{code}: {scenario['esito']}"))
            text += [f"## Scenario {code}: {scenario['esito']}", "", "Dati iniziali, operazioni/record e saldi effettivi:", "", "```json", json.dumps(scenario, indent=2, ensure_ascii=False), "```", ""]
        text += ["## Problemi architetturali emersi dal collaudo", "",
            "È stata applicata la modifica approvata: input da RigaRicetta alternativi ai requisiti strutturali, conferma ingredienti atomica e articolo principale da ricetta.",
            "Tentativo fallito: analizzare l'errore riportato prima di trarre conclusioni sull'architettura." if failure else "Nessun ulteriore problema rilevato negli scenari eseguiti.",
            "I conteggi dello scenario G sono confronti tecnici simulati; non esiste un documento inventariale dedicato. I controlli E sono esplicitamente DEMO, non parametri aziendali.", "",
            "## Dati demo e utenti", "", "```json", json.dumps({k: v for k, v in result.items() if k != "scenari"}, indent=2, ensure_ascii=False), "```", "",
            "## Prima della UI", "", "Completare la verifica MySQL dell'intera suite; concordare eventuali scostamenti degli ingredienti, parametri qualità aziendali e modalità di registrazione dei conteggi. Nessuna UI o fase 12 avviata."]
        (docs / "FASE_11_COLLAUDO.md").write_text("\n".join(text) + "\n", encoding="utf-8")
        self.stdout.write("Verbale: docs/FASE_11_COLLAUDO.md; evidenze: docs/FASE_11_RISULTATI.json")
        if failure:
            raise CommandError("; ".join(failure.messages) + " Tutto il tentativo annullato; dettagli nel verbale.") from failure
