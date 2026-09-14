from django.contrib import admin, messages
from django.core.exceptions import ValidationError, PermissionDenied

from .models import (Ricetta, RigaRicetta, TipoLavorazione, RequisitoInputTipoLavorazione,
                     RequisitoOutputTipoLavorazione, CicloProduzione, Lavorazione,
                     InputLavorazione, OutputLavorazione)
from .models import (RisorsaProduttiva, RisorsaLavorazione, UnitaLavorazione,
                     PartecipazioneUnitaLavorazione, RequisitoFaseUnitaTipoLavorazione)


class RigaRicettaInline(admin.TabularInline):
    model = RigaRicetta
    extra = 0
    autocomplete_fields = ("articolo", "categoria_articolo")

    def has_add_permission(self, request, obj=None):
        return (obj is None or not obj.utilizzata) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return (obj is None or not obj.utilizzata) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (obj is None or not obj.utilizzata) and super().has_delete_permission(request, obj)


@admin.register(Ricetta)
class RicettaAdmin(admin.ModelAdmin):
    list_display = ("nome", "articolo", "versione", "attiva")
    list_filter = ("attiva",)
    search_fields = ("nome", "articolo__codice", "versione")
    autocomplete_fields = ("articolo",)
    list_select_related = ("articolo",)
    inlines = (RigaRicettaInline,)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ("articolo", "nome", "versione", "note") if obj and obj.utilizzata else ()


@admin.register(RigaRicetta)
class RigaRicettaAdmin(admin.ModelAdmin):
    list_display = ("ricetta", "articolo", "categoria_articolo", "quantita")
    search_fields = ("ricetta__nome", "articolo__codice", "categoria_articolo__codice")
    autocomplete_fields = ("ricetta", "articolo", "categoria_articolo")
    list_select_related = ("ricetta", "articolo", "categoria_articolo")

    def get_readonly_fields(self, request, obj=None):
        return ("ricetta",) if obj else ()

    def has_change_permission(self, request, obj=None):
        return (obj is None or not obj.ricetta.utilizzata) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (obj is None or not obj.ricetta.utilizzata) and super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


class RequisitoInline(admin.TabularInline):
    extra = 0
    fk_name = "tipo_lavorazione"
    autocomplete_fields = ("articolo", "categoria_articolo")

    def has_add_permission(self, request, obj=None):
        return (obj is None or not obj.lavorazioni.exists()) and super().has_add_permission(request, obj)

    def has_change_permission(self, request, obj=None):
        return (obj is None or not obj.lavorazioni.exists()) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (obj is None or not obj.lavorazioni.exists()) and super().has_delete_permission(request, obj)


class InputRequisitoInline(RequisitoInline):
    model = RequisitoInputTipoLavorazione
    autocomplete_fields = ("articolo", "categoria_articolo", "tipo_lavorazione_origine")


class OutputRequisitoInline(RequisitoInline):
    model = RequisitoOutputTipoLavorazione


@admin.register(TipoLavorazione)
class TipoLavorazioneAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "genera_lotto", "attivo")
    search_fields = ("codice", "nome")
    list_filter = ("genera_lotto", "attivo")
    inlines = (InputRequisitoInline, OutputRequisitoInline)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ("codice", "nome", "genera_lotto", "fase_operativa", "note") if obj and obj.lavorazioni.exists() else ()


@admin.register(RequisitoInputTipoLavorazione, RequisitoOutputTipoLavorazione)
class RequisitoAdmin(admin.ModelAdmin):
    list_display = ("nome", "tipo_lavorazione", "articolo", "categoria_articolo", "obbligatorio", "multiplo", "ordine")
    search_fields = ("nome", "tipo_lavorazione__codice")
    list_filter = ("obbligatorio", "multiplo")
    autocomplete_fields = ("tipo_lavorazione", "articolo", "categoria_articolo")
    list_select_related = ("tipo_lavorazione", "articolo", "categoria_articolo")

    def has_change_permission(self, request, obj=None):
        return (obj is None or not obj.tipo_lavorazione.lavorazioni.exists()) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (obj is None or not obj.tipo_lavorazione.lavorazioni.exists()) and super().has_delete_permission(request, obj)

    def get_readonly_fields(self, request, obj=None):
        return ("tipo_lavorazione",) if obj else ()

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


class ProductionReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(CicloProduzione)
class CicloAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "articolo", "data", "stato", "creato_da")
    list_filter = ("stato", "data")
    search_fields = ("articolo__codice", "note")
    list_select_related = ("articolo", "creato_da")


@admin.register(Lavorazione)
class LavorazioneAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "ciclo_produzione", "tipo_lavorazione", "stato", "ricetta", "data_ora_inizio", "data_ora_fine")
    list_filter = ("stato", "tipo_lavorazione")
    search_fields = ("tipo_lavorazione__codice", "note")
    list_select_related = ("ciclo_produzione__articolo", "tipo_lavorazione", "ricetta")
    actions = ("start_work", "complete_work", "cancel_work")

    def has_execute_production_permission(self, request):
        return request.user.has_perm("auth.can_execute_production")

    def has_cancel_unstarted_work_permission(self, request):
        return request.user.has_perm("auth.can_cancel_unstarted_work")

    def _apply_single(self, request, queryset, operation, label):
        if queryset.count() != 1:
            self.message_user(request, "Selezionare una sola lavorazione per volta.", level=messages.ERROR)
            return
        obj = queryset.get()
        try:
            operation(actor=request.user, lavorazione=obj.pk)
        except (ValidationError, PermissionDenied) as exc:
            self.message_user(request, "; ".join(exc.messages) if isinstance(exc, ValidationError) else str(exc), level=messages.ERROR)
            return
        self.log_change(request, obj, label)
        self.message_user(request, label, level=messages.SUCCESS)

    @admin.action(description="Avvia la lavorazione selezionata", permissions=["execute_production"])
    def start_work(self, request, queryset):
        from .services import WorkExecutionService
        self._apply_single(request, queryset, WorkExecutionService.start, "Lavorazione avviata.")

    @admin.action(description="Completa la lavorazione selezionata", permissions=["execute_production"])
    def complete_work(self, request, queryset):
        from .services import WorkExecutionService
        self._apply_single(request, queryset, WorkExecutionService.complete, "Lavorazione completata.")

    @admin.action(description="Annulla la lavorazione mai iniziata", permissions=["cancel_unstarted_work"])
    def cancel_work(self, request, queryset):
        from .services import WorkExecutionService
        self._apply_single(request, queryset, WorkExecutionService.cancel, "Lavorazione annullata.")


@admin.register(InputLavorazione)
class InputAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "lavorazione", "requisito_input", "riga_ricetta", "lotto", "quantita")
    search_fields = ("lotto__codice_lotto", "lavorazione__tipo_lavorazione__codice")
    list_select_related = ("lavorazione__tipo_lavorazione", "requisito_input__tipo_lavorazione", "lotto__articolo")


@admin.register(OutputLavorazione)
class OutputAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "lavorazione", "requisito_output", "lotto", "quantita")
    search_fields = ("lotto__codice_lotto", "lavorazione__tipo_lavorazione__codice")
    list_select_related = ("lavorazione__tipo_lavorazione", "requisito_output__tipo_lavorazione", "lotto__articolo")


@admin.register(RisorsaProduttiva)
class RisorsaAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "tipo", "attiva")
    search_fields = ("codice", "nome")
    list_filter = ("tipo", "attiva")

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ("codice", "nome", "tipo", "note") if obj and (obj.unita.exists() or obj.impieghi.exists()) else ()


@admin.register(RequisitoFaseUnitaTipoLavorazione)
class PercorsoUnitaAdmin(admin.ModelAdmin):
    list_display = ("tipo_lavorazione", "tipo_fase", "ordine", "obbligatorio")
    autocomplete_fields = ("tipo_lavorazione", "tipo_fase")
    list_filter = ("tipo_lavorazione",)

    def has_change_permission(self, request, obj=None):
        return (obj is None or not obj.tipo_lavorazione.configurazione_utilizzata) and super().has_change_permission(request, obj)

    def has_delete_permission(self, request, obj=None):
        return (obj is None or not obj.tipo_lavorazione.configurazione_utilizzata) and super().has_delete_permission(request, obj)

    def get_actions(self, request):
        actions = super().get_actions(request)
        actions.pop("delete_selected", None)
        return actions


@admin.register(RisorsaLavorazione)
class ImpiegoAdmin(ProductionReadOnlyAdmin):
    list_display = ("lavorazione", "risorsa_produttiva", "note")
    list_select_related = ("lavorazione", "risorsa_produttiva")


@admin.register(UnitaLavorazione)
class UnitaAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "codice", "lotto", "lavorazione_origine", "risorsa_produttiva", "quantita", "stato")
    list_filter = ("stato",)
    search_fields = ("codice", "lotto__codice_lotto", "risorsa_produttiva__codice")
    list_select_related = ("lotto", "lavorazione_origine", "risorsa_produttiva")


@admin.register(PartecipazioneUnitaLavorazione)
class PartecipazioneAdmin(ProductionReadOnlyAdmin):
    list_display = ("unita_lavorazione", "lavorazione", "note")
    list_select_related = ("unita_lavorazione", "lavorazione")


from .models import (LineaProduttiva, PostazioneLinea, TurnoOperativo, PianoProduzione, BatchPiano,
    RevisionePrelievo, RigaPianoPrelievo, PrelievoDaPiano, TankAziendale, SessioneInvasettamento,
    CarrelloSessione, TrattamentoCarrello, RiepilogoInvasettamento, CodiceProduzione)
from .models import (SessioneProduzioneSemplificata, PrelievoSessioneSemplificata,
    ConfigurazioneControlloSemplificato, ControlloSessioneSemplificata, RiepilogoSessioneSemplificata, NonConformitaSessioneSemplificata,
    AzioneNCSessioneSemplificata, VerificaNCSessioneSemplificata, AssociazioneTankBatch)


@admin.register(LineaProduttiva)
class LineaAdmin(admin.ModelAdmin):
    list_display = ("codice", "nome", "tipo_batch", "tipo_invasettamento", "attiva")
    search_fields = ("codice", "nome")

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return tuple(f.name for f in self.model._meta.fields if f.name not in {"id", "attiva"}) if obj and obj.postazioni.exists() else ()


@admin.register(PostazioneLinea)
class PostazioneAdmin(admin.ModelAdmin):
    list_display = ("id", "linea", "risorsa", "ruolo")
    list_filter = ("linea", "ruolo")
    search_fields = ("linea__codice", "linea__nome", "risorsa__codice", "risorsa__nome")

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        return ("linea", "risorsa", "ruolo") if obj and obj.turni.exists() else ()


@admin.register(TurnoOperativo)
class TurnoAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "postazione", "operatore", "inizio", "igienizzazione_confermata_il", "fine")
    list_filter = ("postazione",)


@admin.register(TankAziendale)
class TankAziendaleAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "linea", "ricetta", "lotto", "pronto_il")
    search_fields = ("lotto__codice_lotto", "ricetta__articolo__codice")


@admin.register(SessioneInvasettamento)
class SessioneAdmin(ProductionReadOnlyAdmin):
    list_display = ("id", "turno", "ricetta", "lotto", "aperta_il", "chiusa_il")


@admin.register(RiepilogoInvasettamento)
class RiepilogoAdmin(ProductionReadOnlyAdmin):
    list_display = ("sessione", "vasetti_buoni", "vasetti_scarti", "capsule_difettose", "massa_teorica_kg", "massa_reale_kg", "resa_percentuale")


@admin.register(CodiceProduzione)
class CodiceProduzioneAdmin(ProductionReadOnlyAdmin):
    list_display = ("articolo", "giorno", "famiglia", "numero", "codice")
    list_filter = ("famiglia", "giorno")
    search_fields = ("codice", "articolo__codice")


for historical_model in (PianoProduzione, BatchPiano, RevisionePrelievo, RigaPianoPrelievo,
                         PrelievoDaPiano, CarrelloSessione, TrattamentoCarrello):
    admin.site.register(historical_model, ProductionReadOnlyAdmin)


@admin.register(SessioneProduzioneSemplificata)
class SessioneProduzioneSemplificataAdmin(admin.ModelAdmin):
    list_display = ("codice_lotto", "tipo", "postazione", "ricetta", "lotto_origine", "stato", "aperta_il", "chiusa_il")
    list_filter = ("tipo", "stato", "postazione")
    search_fields = ("lotto__codice_lotto", "ricetta__articolo__codice", "ricetta__articolo__descrizione")

    @admin.display(description="Lotto", ordering="lotto__codice_lotto")
    def codice_lotto(self, obj):
        return obj.lotto.codice_lotto
    autocomplete_fields = ("postazione", "ricetta", "lotto_origine", "aperta_da", "chiusa_da")


@admin.register(PrelievoSessioneSemplificata)
class PrelievoSessioneSemplificataAdmin(admin.ModelAdmin):
    list_display = ("sessione", "numero_batch", "lotto", "quantita_kg", "registrato_il")
    search_fields = ("sessione__lotto__codice_lotto", "lotto__codice_lotto", "lotto__articolo__codice")
    autocomplete_fields = ("sessione", "lotto", "movimento", "registrato_da")


@admin.register(ControlloSessioneSemplificata)
class ControlloSessioneSemplificataAdmin(admin.ModelAdmin):
    list_display = ("sessione", "tipo", "numero", "conforme", "registrato_il")
    list_filter = ("tipo",)
    search_fields = ("sessione__lotto__codice_lotto",)


@admin.register(ConfigurazioneControlloSemplificato)
class ConfigurazioneControlloSemplificatoAdmin(admin.ModelAdmin):
    list_display = ("ambito", "nome", "codice", "ordine", "obbligatorio", "attivo")
    list_filter = ("ambito", "obbligatorio", "attivo")
    ordering = ("ambito", "ordine")


@admin.register(AssociazioneTankBatch)
class AssociazioneTankBatchAdmin(admin.ModelAdmin):
    list_display = ("tank", "batch", "registrato_da", "registrato_il")
    search_fields = ("tank__sessione__lotto__codice_lotto",)


@admin.register(RiepilogoSessioneSemplificata)
class RiepilogoSessioneSemplificataAdmin(admin.ModelAdmin):
    list_display = ("sessione", "vasetti_buoni", "vasetti_scartati", "vasetti_quarantena", "peso_netto_g", "resa_percentuale")


@admin.register(NonConformitaSessioneSemplificata)
class NonConformitaSessioneSemplificataAdmin(admin.ModelAdmin):
    list_display = ("id", "sessione", "controllo", "stato", "aperta_il", "chiusa_il")
    list_filter = ("stato",)
    search_fields = ("sessione__lotto__codice_lotto", "descrizione")


@admin.register(AzioneNCSessioneSemplificata)
class AzioneNCSessioneSemplificataAdmin(admin.ModelAdmin):
    list_display = ("id", "non_conformita", "tipo", "movimento", "registrata_da", "registrata_il")
    search_fields = ("non_conformita__sessione__lotto__codice_lotto", "descrizione")


@admin.register(VerificaNCSessioneSemplificata)
class VerificaNCSessioneSemplificataAdmin(admin.ModelAdmin):
    list_display = ("id", "non_conformita", "esito", "verificata_da", "verificata_il")
    list_filter = ("esito",)
    search_fields = ("non_conformita__sessione__lotto__codice_lotto", "descrizione")
