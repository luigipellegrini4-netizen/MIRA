from decimal import Decimal

from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models.deletion import ProtectedError
from django.test import TestCase

from anagrafiche.models import Articolo, CategoriaArticolo, Fornitore


class CatalogoTests(TestCase):
    def setUp(self):
        self.root = CategoriaArticolo.objects.create(codice="MP", nome="Materie prime")
        self.child = CategoriaArticolo.objects.create(codice="FR", nome="Frutta", categoria_padre=self.root)
        self.leaf = CategoriaArticolo.objects.create(codice="ME", nome="Mele", categoria_padre=self.child)

    def test_antenati_e_percorso(self):
        self.assertEqual(self.leaf.antenati(), [self.root, self.child])
        self.assertEqual(self.leaf.percorso_completo, "Materie prime / Frutta / Mele")

    def test_discendenti(self):
        self.assertSetEqual(set(self.root.discendenti()), {self.child, self.leaf})

    def test_appartenenza_diretta_e_indiretta(self):
        self.assertTrue(self.leaf.appartiene_a_categoria_o_discendenti(self.root))
        self.assertTrue(self.root.appartiene_a_categoria_o_discendenti(self.root))
        self.assertFalse(self.root.appartiene_a_categoria_o_discendenti(self.leaf))

    def test_categoria_con_figli_puo_avere_articoli(self):
        article = Articolo.objects.create(codice="A", descrizione="Ingrediente", categoria=self.root, unita_misura="KG")
        self.assertEqual(article.categoria, self.root)

    def test_articolo_in_discendente(self):
        article = Articolo.objects.create(codice="A", descrizione="Mela", categoria=self.leaf, unita_misura="KG")
        self.assertTrue(article.appartiene_a_categoria_o_discendenti(self.root))

    def test_ciclo_indiretto_rifiutato(self):
        self.root.categoria_padre = self.leaf
        with self.assertRaises(ValidationError):
            self.root.save()

    def test_ciclo_diretto_rifiutato(self):
        self.root.categoria_padre = self.root
        with self.assertRaises(ValidationError):
            self.root.save()

    def test_categoria_utilizzata_protetta(self):
        with self.assertRaises(ProtectedError):
            self.root.delete()

    def test_scorta_negativa_rifiutata(self):
        article = Articolo(codice="A", descrizione="Ingrediente", categoria=self.root, unita_misura="KG", scorta_minima=-1)
        with self.assertRaises(ValidationError):
            article.save()

    def test_db_impedisce_scorta_negativa(self):
        article = Articolo.objects.create(codice="A", descrizione="Ingrediente", categoria=self.root, unita_misura="KG")
        with self.assertRaises(IntegrityError), transaction.atomic():
            Articolo.objects.filter(pk=article.pk).update(scorta_minima=Decimal("-1"))

    def test_unita_non_valida(self):
        article = Articolo(codice="A", descrizione="Ingrediente", categoria=self.root, unita_misura="XX")
        with self.assertRaises(ValidationError):
            article.save()

    def test_codici_fornitore_univoci(self):
        Fornitore.objects.create(codice="F", ragione_sociale="Fornitore")
        with self.assertRaises(ValidationError):
            Fornitore.objects.create(codice="F", ragione_sociale="Altro")
