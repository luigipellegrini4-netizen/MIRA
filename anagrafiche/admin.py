from django.contrib import admin

from .models import Articolo, CategoriaArticolo, Fornitore, Ubicazione


class AnagraficaAdmin(admin.ModelAdmin):
    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CategoriaArticolo)
class CategoriaAdmin(AnagraficaAdmin):
    list_display = ("codice", "nome", "categoria_padre", "attiva")
    list_filter = ("attiva",)
    search_fields = ("codice", "nome")
    autocomplete_fields = ("categoria_padre",)
    list_select_related = ("categoria_padre",)


@admin.register(Articolo)
class ArticoloAdmin(AnagraficaAdmin):
    list_display = ("codice", "descrizione", "categoria", "unita_misura", "criterio_rotazione", "attivo")
    list_filter = ("attivo", "unita_misura", "criterio_rotazione", "tracciabilita_lotto")
    search_fields = ("codice", "descrizione")
    autocomplete_fields = ("categoria",)
    list_select_related = ("categoria",)


@admin.register(Fornitore)
class FornitoreAdmin(AnagraficaAdmin):
    list_display = ("codice", "ragione_sociale", "partita_iva", "attivo")
    list_filter = ("attivo",)
    search_fields = ("codice", "ragione_sociale", "partita_iva")


@admin.register(Ubicazione)
class UbicazioneAdmin(AnagraficaAdmin):
    list_display = ("codice", "nome", "attiva")
    list_filter = ("attiva",)
    search_fields = ("codice", "nome")
