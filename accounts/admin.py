"""Gestione utenti aziendali senza promozione a superuser tecnico."""
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import PermissionDenied


admin.site.unregister(User)


@admin.register(User)
class MiraUserAdmin(UserAdmin):
    add_form = UserCreationForm
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("username", "password1", "password2"),
            },
        ),
    )

    def get_queryset(self, request):
        queryset = super().get_queryset(request)
        return queryset if request.user.is_superuser else queryset.filter(is_superuser=False)

    def get_fieldsets(self, request, obj=None):
        if request.user.is_superuser or obj is None:
            return super().get_fieldsets(request, obj)
        return (
            (None, {"fields": ("username", "password")}),
            ("Dati personali", {"fields": ("first_name", "last_name", "email")}),
            ("Accesso e ruoli", {"fields": ("is_active", "is_staff", "groups")}),
            ("Date", {"fields": ("last_login", "date_joined")}),
        )

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser:
            if obj.is_superuser or (obj.pk and User.objects.filter(pk=obj.pk, is_superuser=True).exists()):
                raise PermissionDenied("Gli account tecnici sono gestiti soltanto da un superuser.")
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        return False
