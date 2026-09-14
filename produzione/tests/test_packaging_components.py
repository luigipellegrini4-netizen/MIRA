from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase
from django.urls import reverse

from magazzino.models import Giacenza, Lotto, Movimento
from magazzino.services import MovementService, Position
from produzione.services import ProduzioneSemplificataService as Service
from produzione.services.packaging_availability import packaging_availability
from produzione.tests.test_packaging_availability import PackagingAvailabilityTests
from qualita.nc_services import NonConformityService


class PackagingComponentTests(TestCase):
    setUp = PackagingAvailabilityTests.setUp

    def pack(self, amount=200):
        Service.chiudi_confezionamento(actor=self.actor, sessione=self.session, quantita_confezionata=amount,
                                      giacenza=Giacenza.objects.get(pk=self.stock.pk))

    def move(self, amount, component, kind="VENDITA", destination=None):
        return MovementService.register(actor=self.actor, lotto=self.lot, tipo=kind, quantita=amount,
            componente=component, origine=Position(self.stock.ubicazione_id, "", ""), destinazione=destination, note="Prova")

    def test_pack_then_sell_packed_preserves_loose(self):
        self.pack()
        movement = self.move(100, "CONFEZIONATO")
        self.assertEqual(movement.componente, "CONFEZIONATO")
        stock = Giacenza.objects.get(pk=self.stock.pk)
        self.assertEqual((stock.quantita, stock.quantita_confezionata, stock.quantita_non_confezionata), (500, 100, 400))
        self.assertEqual(packaging_availability(Lotto.objects.get(pk=self.lot.pk), 600), (500, 400))
        self.session.refresh_from_db()
        self.assertEqual(self.session.confezionamento_giacenza_id, stock.pk)
        with self.assertRaises(ValidationError):
            self.pack()

    def test_sell_loose_reduces_packaging_limit(self):
        self.pack()
        self.move(100, "SFUSO")
        stock = Giacenza.objects.get(pk=self.stock.pk)
        self.assertEqual((stock.quantita_confezionata, stock.quantita_non_confezionata), (200, 300))
        with self.assertRaises(ValidationError):
            self.move(301, "SFUSO")
        with self.assertRaises(ValidationError):
            self.move(201, "CONFEZIONATO")
        with self.assertRaises(ValidationError):
            self.move(1, "")
        self.assertEqual(Movimento.objects.filter(tipo="VENDITA").count(), 1)

    def test_transfer_keeps_component_and_position(self):
        self.pack()
        destination = Position(self.stock.ubicazione_id, "B", "2")
        self.move(75, "CONFEZIONATO", "TRASFERIMENTO", destination)
        target = Giacenza.objects.get(lotto_id=self.lot.pk, scaffale="B")
        source = Giacenza.objects.get(pk=self.stock.pk)
        self.assertEqual((target.quantita, target.quantita_confezionata), (75, 75))
        self.assertEqual(source.quantita_confezionata, 125)

    def test_quarantine_blocks_only_its_component_and_nc(self):
        self.pack()
        nc = NonConformityService.open(actor=self.actor, descrizione="Prova", lotto=self.lot)
        NonConformityService.take_charge(actor=self.actor, non_conformita=nc)
        origin = Position(self.stock.ubicazione_id, "", "")
        target = Position(self.stock.ubicazione_id, "Q", "1")
        NonConformityService.action(actor=self.actor, non_conformita=nc, tipo_azione="QUARANTENA",
            descrizione="Isolamento", quantita=50, origine=origin, destinazione=target, componente="CONFEZIONATO")
        self.move(30, "SFUSO", "TRASFERIMENTO", target)
        with self.assertRaises(ValidationError):
            NonConformityService.action(actor=self.actor, non_conformita=nc, tipo_azione="REINTEGRO",
                descrizione="Errato", quantita=1, origine=target, destinazione=origin, componente="SFUSO")
        NonConformityService.action(actor=self.actor, non_conformita=nc, tipo_azione="SCARTO",
            descrizione="Scarto", quantita=50, origine=target, componente="CONFEZIONATO")
        stock = Giacenza.objects.get(lotto_id=self.lot.pk, scaffale="Q")
        self.assertEqual((stock.quantita_confezionata, stock.quantita_non_confezionata), (0, 30))

    def test_unverified_legacy_lot_cannot_be_misclassified(self):
        self.lot.confezionamento_verificato = False
        self.lot.save()
        with self.assertRaises(ValidationError):
            self.pack()
        with self.assertRaises(ValidationError):
            self.move(1, "SFUSO")

    def test_sale_form_records_explicit_component_and_rejects_combined_excess(self):
        from vendite.models import Cliente
        self.pack()
        customer = Cliente.objects.create(codice="C1", ragione_sociale="Cliente")
        self.client.force_login(self.actor)
        data = {"numero_documento": "V1", "data_documento": "2026-09-13", "cliente": customer.pk,
            "righe-TOTAL_FORMS": "2", "righe-INITIAL_FORMS": "0",
            "righe-0-giacenza": self.stock.pk, "righe-0-componente": "CONFEZIONATO", "righe-0-quantita": "150",
            "righe-1-giacenza": self.stock.pk, "righe-1-componente": "CONFEZIONATO", "righe-1-quantita": "100"}
        response = self.client.post(reverse("ui:sale_new"), data)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(Movimento.objects.filter(tipo="VENDITA").count(), 0)
        data["righe-1-componente"] = "SFUSO"
        self.assertEqual(self.client.post(reverse("ui:sale_new"), data).status_code, 302)
        stock = Giacenza.objects.get(pk=self.stock.pk)
        self.assertEqual((stock.quantita_confezionata, stock.quantita_non_confezionata), (50, 300))

    def test_csv_roundtrip_preserves_components_and_adjustment_is_explicit(self):
        from interfaccia.inventory_csv import apply_rows, csv_response_rows, HEADERS
        self.pack()
        rows = [dict(zip(HEADERS["giacenze"], map(str, row))) for row in csv_response_rows("giacenze")]
        self.assertEqual(apply_rows("giacenze", rows, self.actor, "Verifica"), 0)
        rows[0]["quantita_confezionata"] = "100"
        apply_rows("giacenze", rows, self.actor, "Correzione inventario")
        stock = Giacenza.objects.get(pk=self.stock.pk)
        self.assertEqual((stock.quantita, stock.quantita_confezionata), (600, 100))
        self.assertEqual(set(Movimento.objects.filter(tipo="RETTIFICA").values_list("componente", flat=True)), {"SFUSO", "CONFEZIONATO"})

    def test_backup_roundtrip_preserves_packed_stock_and_position_link(self):
        import copy
        import json
        from interfaccia.backup import create_backup, read_backup, restore_backup
        m = MigrationExecutor(connection).loader.project_state().apps.get_model
        m("magazzino", "Movimento").objects.create(tipo="PRODUZIONE", lotto_id=self.lot.pk, quantita=600,
            ubicazione_destinazione_id=self.stock.ubicazione_id, eseguito_da_id=self.actor.pk, componente="SFUSO")
        self.pack()
        payload = create_backup()
        changed = copy.deepcopy(payload)
        next(row for row in changed["records"] if row["model"] == "magazzino.giacenza")["fields"]["quantita_confezionata"] = "201"
        with self.assertRaises(ValidationError):
            read_backup(json.dumps(changed).encode())
        restore_backup(payload)
        self.assertEqual(Giacenza.objects.get(pk=self.stock.pk).quantita_confezionata, 200)
        self.session.refresh_from_db()
        self.assertEqual(self.session.confezionamento_giacenza_id, self.stock.pk)

    def test_migration_keeps_unpacked_stock_and_flags_ambiguous_history(self):
        from importlib import import_module
        from types import SimpleNamespace
        migration = import_module("magazzino.migrations.0008_giacenza_quantita_confezionata_and_more")
        apps = MigrationExecutor(connection).loader.project_state().apps
        migration.initialize_components(apps, SimpleNamespace(connection=connection))
        self.assertTrue(Lotto.objects.get(pk=self.lot.pk).confezionamento_verificato)
        self.assertEqual(Giacenza.objects.get(pk=self.stock.pk).quantita_non_confezionata, 600)
        self.lot.quantita_confezionata = 200
        self.lot.save()
        migration.initialize_components(apps, SimpleNamespace(connection=connection))
        self.assertFalse(Lotto.objects.get(pk=self.lot.pk).confezionamento_verificato)
        self.assertEqual(Giacenza.objects.get(pk=self.stock.pk).quantita, 600)

    def test_old_backup_marks_packaging_history_for_reconciliation(self):
        import json
        from interfaccia.backup import create_backup, read_backup
        m = MigrationExecutor(connection).loader.project_state().apps.get_model
        m("magazzino", "Movimento").objects.create(tipo="PRODUZIONE", lotto_id=self.lot.pk, quantita=600,
            ubicazione_destinazione_id=self.stock.ubicazione_id, eseguito_da_id=self.actor.pk)
        self.pack()
        payload = create_backup()
        payload["format"] = "MIRA_BACKUP_V1"
        lot_codes = {
            str(row["pk"]): row["fields"]["codice_lotto"]
            for row in payload["records"] if row["model"] == "magazzino.lotto"
        }
        for row in payload["records"]:
            field = {"magazzino.giacenza": "quantita_confezionata", "magazzino.lotto": "confezionamento_verificato",
                     "magazzino.movimento": "componente", "produzione.sessioneproduzionesemplificata": "confezionamento_giacenza"}.get(row["model"])
            if field:
                row["fields"].pop(field)
            if row["model"] == "produzione.sessioneproduzionesemplificata":
                lot_id = row["fields"].pop("lotto")
                row["fields"]["lotto_codice"] = lot_codes[str(lot_id)]
                row["fields"]["lotto_prodotto"] = None if row["fields"]["tipo"] == "CONFEZIONAMENTO" else lot_id
        upgraded = read_backup(json.dumps(payload).encode())
        lot = next(row for row in upgraded["records"] if row["model"] == "magazzino.lotto")
        self.assertFalse(lot["fields"]["confezionamento_verificato"])
