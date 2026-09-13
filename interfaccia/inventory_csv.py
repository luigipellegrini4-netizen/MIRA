import csv
import io
from decimal import Decimal, InvalidOperation

from django.core.exceptions import ValidationError
from django.db import transaction

from anagrafiche.models import Articolo, CategoriaArticolo, Fornitore, Ubicazione
from magazzino.models import Giacenza, Lotto, Movimento, RicevimentoLotto
from magazzino.services import Allocation, MovementService, Position, ReceivingService


HEADERS = {
    "categorie": ["codice", "nome", "categoria_padre", "attiva", "note"],
    "articoli": ["codice", "descrizione", "categoria", "unita_misura", "criterio_rotazione", "tracciabilita_lotto", "scorta_minima", "attivo", "note"],
    "fornitori": ["codice", "ragione_sociale", "partita_iva", "codice_fiscale", "indirizzo", "cap", "comune", "provincia", "nazione", "telefono", "email", "attivo", "note"],
    "ubicazioni": ["codice", "nome", "attiva", "note"],
    "ricevimenti": ["articolo", "fornitore", "codice_lotto", "data_produzione", "data_scadenza", "quantita",
                    "ubicazione", "scaffale", "piano", "data_ricevimento", "numero_ddt", "data_ddt", "note"],
    "lotti": ["articolo", "codice_lotto", "tipo", "fornitore", "data_produzione", "data_scadenza", "note"],
    "giacenze": ["articolo", "codice_lotto", "fornitore", "ubicazione", "scaffale", "piano", "quantita", "quantita_confezionata"],
}


def csv_response_rows(kind):
    if kind == "categorie":
        return ([o.codice, o.nome, o.categoria_padre.codice if o.categoria_padre else "", "SI" if o.attiva else "NO", o.note]
                for o in CategoriaArticolo.objects.select_related("categoria_padre").order_by("codice"))
    if kind == "articoli":
        objects = Articolo.objects.select_related("categoria").order_by("codice")
        return ([a.codice, a.descrizione, a.categoria.codice, a.unita_misura, a.criterio_rotazione,
                 "SI" if a.tracciabilita_lotto else "NO", a.scorta_minima, "SI" if a.attivo else "NO", a.note] for a in objects)
    if kind == "lotti":
        objects = Lotto.objects.select_related("articolo", "fornitore").order_by("articolo__codice", "codice_lotto")
        return ([l.articolo.codice, l.codice_lotto, l.tipo, l.fornitore.codice if l.fornitore else "",
                 l.data_produzione or "", l.data_scadenza or "", l.note] for l in objects)
    if kind == "fornitori":
        return ([o.codice, o.ragione_sociale, o.partita_iva, o.codice_fiscale, o.indirizzo, o.cap, o.comune,
                 o.provincia, o.nazione, o.telefono, o.email, "SI" if o.attivo else "NO", o.note]
                for o in Fornitore.objects.order_by("codice"))
    if kind == "ubicazioni":
        return ([o.codice, o.nome, "SI" if o.attiva else "NO", o.note] for o in Ubicazione.objects.order_by("codice"))
    if kind == "ricevimenti":
        def receipt_rows():
            receipts = RicevimentoLotto.objects.select_related("lotto__articolo", "lotto__fornitore").order_by("pk")
            for receipt in receipts:
                movements = Movimento.objects.filter(tipo="CARICO", lotto=receipt.lotto,
                    note__startswith=f"Ricevimento #{receipt.pk}").select_related("ubicazione_destinazione")
                for movement in movements:
                    yield [receipt.lotto.articolo.codice, receipt.lotto.fornitore.codice, receipt.lotto.codice_lotto,
                           receipt.lotto.data_produzione or "", receipt.lotto.data_scadenza or "", movement.quantita,
                           movement.ubicazione_destinazione.codice, movement.scaffale_destinazione, movement.piano_destinazione,
                           receipt.data_ricevimento.isoformat(), receipt.numero_ddt, receipt.data_ddt or "", receipt.note]
        return receipt_rows()
    objects = Giacenza.objects.filter(quantita__gt=0).select_related("lotto__articolo", "lotto__fornitore", "ubicazione").order_by("ubicazione__codice", "scaffale", "piano")
    return ([s.lotto.articolo.codice, s.lotto.codice_lotto, s.lotto.fornitore.codice if s.lotto.fornitore else "",
             s.ubicazione.codice, s.scaffale, s.piano, s.quantita, s.quantita_confezionata] for s in objects)


def read_upload(upload):
    if upload.size > 2_000_000:
        raise ValidationError("Il file supera 2 MB.")
    try:
        text = upload.read().decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ValidationError("Salvare il CSV in formato UTF-8.") from None
    try:
        dialect = csv.Sniffer().sniff(text[:4096], delimiters=";,")
        reader = csv.DictReader(io.StringIO(text), dialect=dialect)
        rows = [{(k or "").strip(): (v or "").strip() for k, v in row.items()} for row in reader]
    except csv.Error as exc:
        raise ValidationError("CSV non leggibile: " + str(exc)) from None
    if len(rows) > 5000:
        raise ValidationError("Il file può contenere al massimo 5.000 righe.")
    return rows


def _bool(value):
    values = {"SI": True, "SÌ": True, "1": True, "TRUE": True, "NO": False, "0": False, "FALSE": False}
    if value.upper() not in values:
        raise ValueError("usare SI oppure NO")
    return values[value.upper()]


def inspect_rows(kind, rows):
    if not rows:
        raise ValidationError("Il CSV non contiene righe di dati.")
    missing = [h for h in HEADERS[kind] if rows and h not in rows[0] and h != "quantita_confezionata"]
    if missing:
        raise ValidationError("Colonne mancanti: " + ", ".join(missing))
    report = []
    for number, row in enumerate(rows, 2):
        try:
            if kind == "categorie":
                _bool(row["attiva"])
                if not row["codice"] or not row["nome"]:
                    raise ValueError("codice e nome sono obbligatori")
                if row["categoria_padre"] and not CategoriaArticolo.objects.filter(codice=row["categoria_padre"]).exists():
                    raise ValueError("categoria padre inesistente")
                action = "Aggiorna" if CategoriaArticolo.objects.filter(codice=row["codice"]).exists() else "Crea"
            elif kind == "articoli":
                category = CategoriaArticolo.objects.get(codice=row["categoria"])
                Decimal(row["scorta_minima"]); _bool(row["tracciabilita_lotto"]); _bool(row["attivo"])
                existing = Articolo.objects.filter(codice=row["codice"]).first()
                action = "Aggiorna" if existing else "Crea"
                if not row["codice"] or not row["descrizione"] or row["unita_misura"] not in Articolo.UnitaMisura.values or row["criterio_rotazione"] not in Articolo.CriterioRotazione.values:
                    raise ValueError("dati articolo non validi")
            elif kind == "fornitori":
                _bool(row["attivo"])
                forms_email = row["email"]
                if forms_email:
                    Fornitore._meta.get_field("email").clean(forms_email, None)
                if not row["codice"] or not row["ragione_sociale"]:
                    raise ValueError("codice e ragione sociale sono obbligatori")
                action = "Aggiorna" if Fornitore.objects.filter(codice=row["codice"]).exists() else "Crea"
            elif kind == "ubicazioni":
                _bool(row["attiva"])
                if not row["codice"] or not row["nome"]:
                    raise ValueError("codice e nome sono obbligatori")
                action = "Aggiorna" if Ubicazione.objects.filter(codice=row["codice"]).exists() else "Crea"
            elif kind == "lotti":
                article = Articolo.objects.get(codice=row["articolo"])
                if row["tipo"] != Lotto.Tipo.ACQUISTO:
                    raise ValueError("l’upload accetta soltanto lotti ACQUISTO")
                supplier = Fornitore.objects.get(codice=row["fornitore"])
                Lotto._meta.get_field("data_produzione").clean(row["data_produzione"] or None, None)
                Lotto._meta.get_field("data_scadenza").clean(row["data_scadenza"] or None, None)
                existing = Lotto.objects.filter(articolo=article, fornitore=supplier, codice_lotto=row["codice_lotto"]).first()
                action = "Già presente" if existing else "Crea"
            elif kind == "ricevimenti":
                article = Articolo.objects.get(codice=row["articolo"], attivo=True)
                Fornitore.objects.get(codice=row["fornitore"], attivo=True)
                Ubicazione.objects.get(codice=row["ubicazione"], attiva=True)
                amount = Decimal(row["quantita"])
                if not amount.is_finite() or amount <= 0:
                    raise ValueError("quantità non valida")
                for field in ("data_produzione", "data_scadenza"):
                    Lotto._meta.get_field(field).clean(row[field] or None, None)
                RicevimentoLotto._meta.get_field("data_ricevimento").clean(row["data_ricevimento"] or None, None)
                RicevimentoLotto._meta.get_field("data_ddt").clean(row["data_ddt"] or None, None)
                action = f"Ricevi {amount:g} {article.unita_misura}"
            elif kind == "giacenze":
                article = Articolo.objects.get(codice=row["articolo"])
                lots = Lotto.objects.filter(articolo=article, codice_lotto=row["codice_lotto"])
                lots = lots.filter(fornitore__codice=row["fornitore"]) if row["fornitore"] else lots.filter(fornitore__isnull=True)
                lot = lots.get(); location = Ubicazione.objects.get(codice=row["ubicazione"], attiva=True)
                target = Decimal(row["quantita"])
                if lot.stato_prodotto == "PRODOTTO_FINITO" and not row.get("quantita_confezionata"):
                    raise ValueError("per i prodotti finiti compilare quantita_confezionata (anche 0)")
                packed = Decimal(row.get("quantita_confezionata") or "0")
                if not packed.is_finite() or not target.is_finite() or not 0 <= packed <= target:
                    raise ValueError("quantità confezionata non valida")
                if packed and lot.stato_prodotto != "PRODOTTO_FINITO":
                    raise ValueError("quantità confezionata ammessa soltanto sui prodotti finiti")
                if not lot.confezionamento_verificato:
                    raise ValueError("ripartizione storica del lotto da verificare")
                if not target.is_finite() or target < 0:
                    raise ValueError("quantità finale non valida")
                current = Giacenza.objects.filter(lotto=lot, ubicazione=location, scaffale=row["scaffale"].upper(), piano=row["piano"].upper()).values_list("quantita", flat=True).first() or Decimal("0")
                action = f"Saldo finale {target:g}, di cui confezionati {packed:g}"
            report.append({"line": number, "action": action, "error": "", "row": row})
        except (ValueError, InvalidOperation, ValidationError, Articolo.DoesNotExist, CategoriaArticolo.DoesNotExist, Fornitore.DoesNotExist, Ubicazione.DoesNotExist, Lotto.DoesNotExist, Lotto.MultipleObjectsReturned) as exc:
            message = " · ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc)
            report.append({"line": number, "action": "Errore", "error": message or "riferimento inesistente o ambiguo", "row": row})
    return report


@transaction.atomic
def apply_rows(kind, rows, actor, reason):
    report = inspect_rows(kind, rows)
    errors = [r for r in report if r["error"]]
    if errors:
        raise ValidationError("Il file contiene errori; ripetere l’anteprima.")
    changed = 0
    for row in rows:
        if kind == "categorie":
            obj = CategoriaArticolo.objects.filter(codice=row["codice"]).first() or CategoriaArticolo(codice=row["codice"])
            obj.nome = row["nome"]; obj.attiva = _bool(row["attiva"]); obj.note = row["note"]
            obj.categoria_padre = CategoriaArticolo.objects.get(codice=row["categoria_padre"]) if row["categoria_padre"] else None
            obj.save(); changed += 1
        elif kind == "articoli":
            obj = Articolo.objects.filter(codice=row["codice"]).first() or Articolo(codice=row["codice"])
            for key, value in {"descrizione": row["descrizione"], "categoria": CategoriaArticolo.objects.get(codice=row["categoria"]),
                "unita_misura": row["unita_misura"], "criterio_rotazione": row["criterio_rotazione"],
                "tracciabilita_lotto": _bool(row["tracciabilita_lotto"]), "scorta_minima": Decimal(row["scorta_minima"]),
                "attivo": _bool(row["attivo"]), "note": row["note"]}.items(): setattr(obj, key, value)
            obj.save(); changed += 1
        elif kind == "fornitori":
            obj = Fornitore.objects.filter(codice=row["codice"]).first() or Fornitore(codice=row["codice"])
            for key in ("ragione_sociale", "partita_iva", "codice_fiscale", "indirizzo", "cap", "comune", "provincia", "nazione", "telefono", "email", "note"):
                setattr(obj, key, row[key])
            obj.attivo = _bool(row["attivo"]); obj.save(); changed += 1
        elif kind == "ubicazioni":
            obj = Ubicazione.objects.filter(codice=row["codice"]).first() or Ubicazione(codice=row["codice"])
            obj.nome = row["nome"]; obj.attiva = _bool(row["attiva"]); obj.note = row["note"]; obj.save(); changed += 1
        elif kind == "lotti":
            article = Articolo.objects.get(codice=row["articolo"]); supplier = Fornitore.objects.get(codice=row["fornitore"])
            if not Lotto.objects.filter(articolo=article, fornitore=supplier, codice_lotto=row["codice_lotto"]).exists():
                Lotto.objects.create(articolo=article, codice_lotto=row["codice_lotto"], tipo="ACQUISTO", fornitore=supplier,
                    data_produzione=row["data_produzione"] or None, data_scadenza=row["data_scadenza"] or None, note=row["note"]); changed += 1
        elif kind == "ricevimenti":
            article = Articolo.objects.get(codice=row["articolo"]); supplier = Fornitore.objects.get(codice=row["fornitore"])
            location = Ubicazione.objects.get(codice=row["ubicazione"]); amount = Decimal(row["quantita"])
            ReceivingService.receive(actor=actor, articolo=article, fornitore=supplier, codice_lotto=row["codice_lotto"] or None,
                data_produzione=row["data_produzione"] or None, data_scadenza=row["data_scadenza"] or None,
                quantita_ricevuta=amount, destinazioni=[Allocation(Position(location.pk, row["scaffale"], row["piano"]), amount)],
                data_ricevimento=row["data_ricevimento"] or None, numero_ddt=row["numero_ddt"], data_ddt=row["data_ddt"] or None,
                note=row["note"]); changed += 1
        elif kind == "giacenze":
            article = Articolo.objects.get(codice=row["articolo"]); lots = Lotto.objects.filter(articolo=article, codice_lotto=row["codice_lotto"])
            lot = (lots.filter(fornitore__codice=row["fornitore"]) if row["fornitore"] else lots.filter(fornitore__isnull=True)).get()
            location = Ubicazione.objects.get(codice=row["ubicazione"]); position = Position(location.pk, row["scaffale"], row["piano"])
            lot = Lotto.objects.select_for_update().get(pk=lot.pk)
            stock = Giacenza.objects.filter(lotto=lot, **position.stock_lookup()).first()
            current = stock.quantita if stock else Decimal("0")
            target = Decimal(row["quantita"])
            packed = Decimal(row.get("quantita_confezionata") or "0")
            old_packed = stock.quantita_confezionata if stock else Decimal("0")
            deltas = [("CONFEZIONATO", packed-old_packed), ("SFUSO", (target-packed)-(current-old_packed))]
            for component, delta in sorted(deltas, key=lambda item: item[1]):
                if delta:
                    MovementService.register(actor=actor, lotto=lot, tipo=Movimento.Tipo.RETTIFICA, quantita=abs(delta),
                        origine=position if delta < 0 else None, destinazione=position if delta > 0 else None,
                        componente=component, note=f"Importazione inventario CSV — {reason}")
                    changed += 1
    return changed
