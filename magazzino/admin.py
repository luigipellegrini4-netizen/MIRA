from django.contrib import admin
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.urls import path, reverse
from django.utils.html import format_html

from .models import Giacenza, Lotto, Movimento, RicevimentoLotto


class StoricoAdmin(admin.ModelAdmin):
    """La scrittura passa dai servizi; l'Admin di fase 2 è consultivo."""
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Lotto)
class LottoAdmin(StoricoAdmin):
    list_display = ("codice_lotto", "articolo", "tipo", "stato_prodotto", "fornitore", "data_scadenza", "genealogia")
    list_filter = ("tipo", "stato_prodotto")
    search_fields = ("codice_lotto", "articolo__codice", "fornitore__ragione_sociale")
    list_select_related = ("articolo", "fornitore")
    exclude = ("codice_univoco_produzione",)

    def get_urls(self):
        return [path("<int:lotto_id>/genealogia/", self.admin_site.admin_view(self.genealogy_view), name="magazzino_lotto_genealogia")] + super().get_urls()

    @admin.display(description="Tracciabilità JSON")
    def genealogia(self, obj):
        url = reverse("admin:magazzino_lotto_genealogia", args=[obj.pk])
        return format_html('<a href="{}?direzione=MONTE">A monte</a> · <a href="{}?direzione=VALLE">A valle</a>', url, url)

    def genealogy_view(self, request, lotto_id):
        from produzione.services import GenealogyService
        if request.method != "GET":
            from django.http import HttpResponseNotAllowed
            return HttpResponseNotAllowed(["GET"])
        try:
            result = GenealogyService.trace(actor=request.user, lotto=lotto_id, direzione=request.GET.get("direzione", "MONTE"))
        except ValidationError as exc:
            return JsonResponse({"errori": exc.messages}, status=400)
        return JsonResponse(result, json_dumps_params={"ensure_ascii": False, "indent": 2})


@admin.register(Giacenza)
class GiacenzaAdmin(StoricoAdmin):
    list_display = ("lotto", "ubicazione", "scaffale", "piano", "quantita")
    list_filter = ("ubicazione",)
    search_fields = ("lotto__codice_lotto", "lotto__articolo__codice", "scaffale", "piano")
    list_select_related = ("lotto__articolo", "ubicazione")


@admin.register(Movimento)
class MovimentoAdmin(StoricoAdmin):
    list_display = ("data_ora", "tipo", "lotto", "quantita", "ubicazione_origine", "ubicazione_destinazione", "eseguito_da")
    list_filter = ("tipo", "data_ora")
    search_fields = ("lotto__codice_lotto", "lotto__articolo__codice", "note")
    list_select_related = ("lotto__articolo", "ubicazione_origine", "ubicazione_destinazione", "eseguito_da")


@admin.register(RicevimentoLotto)
class RicevimentoAdmin(StoricoAdmin):
    list_display = ("data_ricevimento", "lotto", "quantita_ricevuta", "numero_ddt")
    list_filter = ("data_ricevimento",)
    search_fields = ("lotto__codice_lotto", "numero_ddt", "numero_fattura")
    list_select_related = ("lotto__articolo",)
