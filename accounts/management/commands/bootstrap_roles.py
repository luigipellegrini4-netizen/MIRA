from django.contrib.auth.models import Group, Permission
from django.contrib.contenttypes.models import ContentType
from django.core.management.base import BaseCommand
from django.db import transaction

from accounts.permissions import A, RP, RQ, CAPABILITIES, MODEL_MANAGERS, OPERATIVE_ROLES, ROLES


class Command(BaseCommand):
    help = "Crea i sette ruoli e sincronizza solo i permessi gestiti da MIRA."

    @transaction.atomic
    def handle(self, *args, **options):
        # Il lock comune serializza bootstrap concorrenti.
        ct = ContentType.objects.get_for_model(Group)
        ContentType.objects.select_for_update().get(pk=ct.pk)
        groups = {name: Group.objects.get_or_create(name=name)[0] for name in ROLES}
        for code, (label, members) in CAPABILITIES.items():
            permission, _ = Permission.objects.update_or_create(
                content_type=ct, codename=code, defaults={"name": label}
            )
            for name, group in groups.items():
                if name in members:
                    group.permissions.add(permission)
                else:
                    group.permissions.remove(permission)
        # Nessun permesso delete e nessuna attribuzione di is_superuser.
        for model, actions in {
            "user": ("view", "add", "change"),
            "group": ("view", "add", "change"),
            "permission": ("view",),
        }.items():
            permissions = Permission.objects.filter(
                content_type__app_label="auth", content_type__model=model,
                codename__in=[f"{action}_{model}" for action in actions],
            )
            groups[A].permissions.add(*permissions)
        for model, managers in MODEL_MANAGERS.items():
            for action in ("view", "add", "change", "delete"):
                permission = Permission.objects.get(content_type__app_label="anagrafiche", codename=f"{action}_{model}")
                members = (set(OPERATIVE_ROLES) | managers) if action == "view" else managers if action in {"add", "change"} else set()
                for name, group in groups.items():
                    if name in members:
                        group.permissions.add(permission)
                    else:
                        group.permissions.remove(permission)
        for permission in Permission.objects.filter(content_type__app_label="magazzino"):
            for name, group in groups.items():
                if permission.codename.startswith("view_") and name in OPERATIVE_ROLES:
                    group.permissions.add(permission)
                else:
                    group.permissions.remove(permission)
        for model in ("ricetta", "rigaricetta"):
            for permission in Permission.objects.filter(content_type__app_label="produzione", content_type__model=model):
                if permission.codename.startswith("view_"):
                    members = set(OPERATIVE_ROLES) | {A}
                elif permission.codename.startswith(("add_", "change_")) or (model == "rigaricetta" and permission.codename.startswith("delete_")):
                    members = {A, RP}
                else:
                    members = set()
                for name, group in groups.items():
                    if name in members:
                        group.permissions.add(permission)
                    else:
                        group.permissions.remove(permission)
        configurations = {"tipolavorazione", "requisitoinputtipolavorazione", "requisitooutputtipolavorazione", "risorsaproduttiva", "requisitofaseunitatipolavorazione"}
        execution = {"cicloproduzione", "lavorazione", "inputlavorazione", "outputlavorazione", "risorsalavorazione", "unitalavorazione", "partecipazioneunitalavorazione"}
        configurations |= {"lineaproduttiva", "postazionelinea"}
        execution |= {"turnooperativo", "pianoproduzione", "batchpiano", "revisioneprelievo", "rigapianoprelievo",
            "prelievodapiano", "tankaziendale", "sessioneinvasettamento", "carrellosessione", "trattamentocarrello",
            "riepilogoinvasettamento", "codiceproduzione"}
        execution |= {
            "sessioneproduzionesemplificata", "prelievosessionesemplificata",
            "controllosessionesemplificata", "associazionetankbatch",
            "riepilogosessionesemplificata", "nonconformitasessionesemplificata",
            "azionencsessionesemplificata", "verificancsessionesemplificata",
        }
        for permission in Permission.objects.filter(content_type__app_label="produzione", content_type__model__in=configurations | execution).select_related("content_type"):
            model = permission.content_type.model
            if permission.codename.startswith("view_"):
                members = set(OPERATIVE_ROLES) | ({A} if model in configurations else set())
            elif model in configurations and permission.codename.startswith(("add_", "change_")):
                members = {A, RP}
            elif model in configurations - {"tipolavorazione", "risorsaproduttiva", "lineaproduttiva", "postazionelinea"} and permission.codename.startswith("delete_"):
                members = {A, RP}
            else:
                members = set()  # l'esecuzione passa dai permessi custom dei servizi
            for name, group in groups.items():
                if name in members:
                    group.permissions.add(permission)
                else:
                    group.permissions.remove(permission)
        for permission in Permission.objects.filter(content_type__app_label="qualita").select_related("content_type"):
            model = permission.content_type.model
            quality_configurations = {"parametrocontrollo", "controllorichiestotipolavorazione"}
            managers = {A, RQ} if model == "parametrocontrollo" else {A, RP, RQ}
            if permission.codename.startswith("view_"):
                members = set(OPERATIVE_ROLES) | ({A} if model in quality_configurations else set())
            elif model in quality_configurations and permission.codename.startswith(("add_", "change_")):
                members = managers
            else:
                members = set()
            for name, group in groups.items():
                if name in members:
                    group.permissions.add(permission)
                else:
                    group.permissions.remove(permission)
        self.stdout.write(self.style.SUCCESS("MIRA: sette ruoli inizializzati; permessi operativi separati."))
