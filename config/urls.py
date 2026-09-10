from django.contrib import admin
from django.urls import path, include
from django.contrib.auth.views import LoginView, LogoutView

admin.site.site_header = "MIRA — Amministrazione"
admin.site.site_title = "MIRA"
admin.site.index_title = "Backend gestionale alimentare"

urlpatterns = [
    path("admin/", admin.site.urls),
    path("accesso/", LoginView.as_view(template_name="interfaccia/login.html"), name="login"),
    path("uscita/", LogoutView.as_view(), name="logout"),
    path("", include("interfaccia.urls")),
]
handler403 = "interfaccia.views.forbidden"
