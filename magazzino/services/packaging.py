from django.db import models


def refresh_packaging_state(lot):
    if lot.stato_prodotto != "PRODOTTO_FINITO":
        return
    totals = lot.giacenze.aggregate(total=models.Sum("quantita"), packed=models.Sum("quantita_confezionata"))
    total, packed = totals["total"] or 0, totals["packed"] or 0
    if total == 0:
        return
    lot.stato_confezionamento = "DA_CONFEZIONARE" if packed == 0 else ("CONFEZIONATO" if packed == total else "PARZIALE")
    models.Model.save(lot, force_update=True, update_fields=["stato_confezionamento"])
