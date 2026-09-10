from django.contrib import admin
from .models import ParametroControllo, ControlloRichiestoTipoLavorazione, ControlloQualita
from .models import NonConformita, AzioneNonConformita, VerificaNonConformita


@admin.register(ParametroControllo)
class ParametroAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "tipo_dato", "unita_misura", "attivo")
    search_fields = ("codice", "nome")

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ControlloRichiestoTipoLavorazione)
class RequisitoAdmin(admin.ModelAdmin):
    list_display = ("tipo_lavorazione", "parametro_controllo", "obbligatorio", "determina_conformita")
    list_filter = ("tipo_lavorazione",)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ControlloQualita)
class ControlloAdmin(admin.ModelAdmin):
    list_display = ("lavorazione", "controllo_richiesto", "esito", "conforme", "data_ora", "eseguito_da")
    list_filter = ("esito", "conforme")

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class NCReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(NonConformita)
class NonConformitaAdmin(NCReadOnlyAdmin):
    list_display = ("numero", "tipo", "stato", "data_ora_apertura", "lotto", "lavorazione", "aperta_da")
    list_filter = ("stato", "tipo")
    search_fields = ("descrizione", "lotto__codice_lotto")
    list_select_related = ("lotto", "lavorazione", "aperta_da")


@admin.register(AzioneNonConformita)
class AzioneNCAdmin(NCReadOnlyAdmin):
    list_display = ("non_conformita", "tipo_azione", "data_ora", "movimento", "lavorazione", "eseguita_da")
    list_filter = ("tipo_azione",)
    list_select_related = ("non_conformita", "movimento", "lavorazione", "eseguita_da")


@admin.register(VerificaNonConformita)
class VerificaNCAdmin(NCReadOnlyAdmin):
    list_display = ("non_conformita", "esito", "data_ora", "controllo_qualita", "verificata_da")
    list_filter = ("esito",)
    list_select_related = ("non_conformita", "controllo_qualita", "verificata_da")
