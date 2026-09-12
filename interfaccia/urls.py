from django.urls import path
from . import views
from . import csv_views
from . import recipe_views
from . import simple_production_views
from . import supplier_views
from . import article_views
from . import catalog_views
from . import lot_views

app_name = "ui"
urlpatterns = [
    path("fornitori/", supplier_views.suppliers, name="suppliers"),
    path("fornitori/nuovo/", supplier_views.supplier_new, name="supplier_new"),
    path("fornitori/<int:pk>/", supplier_views.supplier_edit, name="supplier_edit"),
    path("anagrafiche/articoli/<int:pk>/modifica/", article_views.article_edit, name="article_edit"),
    path("anagrafiche/articoli/nuovo/", article_views.article_new, name="article_new"),
    path("anagrafiche/categorie/", catalog_views.categories, name="categories"),
    path("anagrafiche/categorie/nuova/", catalog_views.category_new, name="category_new"),
    path("anagrafiche/categorie/<int:pk>/", catalog_views.category_edit, name="category_edit"),
    path("anagrafiche/ubicazioni/", catalog_views.locations, name="locations"),
    path("anagrafiche/ubicazioni/nuova/", catalog_views.location_new, name="location_new"),
    path("anagrafiche/ubicazioni/<int:pk>/", catalog_views.location_edit, name="location_edit"),
    path("lotti/<int:pk>/modifica/", lot_views.lot_edit, name="lot_edit"),
    path("produzione/", simple_production_views.sessions, name="simple_sessions"),
    path("produzione/roboqbo/nuova/", simple_production_views.open_roboqbo, name="simple_open_roboqbo"),
    path("produzione/semilavorato/nuova/", simple_production_views.open_semifinished, name="simple_open_semifinished"),
    path("produzione/invasettamento/nuova/", simple_production_views.open_filling, name="simple_open_filling"),
    path("produzione/<int:pk>/", simple_production_views.session, name="simple_session"),
    path("produzione/<int:pk>/prelievo/", simple_production_views.picking, name="simple_picking"),
    path("produzione/<int:pk>/altro-prelievo/", simple_production_views.additional_picking, name="simple_additional_picking"),
    path("produzione/<int:pk>/controllo/", simple_production_views.control, name="simple_control"),
    path("produzione/<int:pk>/controlli-batch/", simple_production_views.batch_controls, name="simple_batch_controls"),
    path("produzione/<int:pk>/nc/", simple_production_views.nc, name="simple_nc"),
    path("produzione/<int:pk>/chiudi/", simple_production_views.close, name="simple_close"),
    path("produzione/<int:pk>/<slug:action>/", simple_production_views.lifecycle, name="simple_lifecycle"),
    path("", views.home, name="home"),
    path("magazzino/", views.stock, name="magazzino"),
    path("magazzino/movimenti/", views.movements, name="movimenti"),
    path("tracciabilita/", views.trace_search, name="trace_search"),
    path("configurazione/", csv_views.manage_csv, name="manage_csv"),
    path("configurazione/csv/scarica/<slug:kind>/", csv_views.download_csv, name="download_csv"),
    path("configurazione/backup/", csv_views.download_backup, name="download_backup"),
    path("configurazione/ripristino/", csv_views.restore, name="restore_backup"),
    path("configurazione/azzera/", csv_views.reset_database, name="reset_database"),
    path("lotti/<int:pk>/", views.lot_detail, name="lot"),
    path("ricette/", recipe_views.recipes, name="recipes"),
    path("ricette/nuova/", recipe_views.recipe_edit, name="recipe_new"),
    path("ricette/scarica/", recipe_views.recipes_csv, name="recipes_csv"),
    path("ricette/carica/", recipe_views.recipes_import, name="recipes_import"),
    path("ricette/<int:pk>/", recipe_views.recipe_edit, name="recipe"),
    path("ricette/<int:pk>/duplica/", recipe_views.recipe_clone, name="recipe_clone"),
    path("qualita/", views.quality, name="qualita"),
    path("qualita/produzione/<int:pk>/", views.simple_case_detail, name="simple_case"),
    path("qualita/produzione/<int:pk>/<slug:action>/", simple_production_views.manage_nc, name="simple_case_operation"),
    path("qualita/<int:pk>/", views.case_detail, name="case"),
    path("anagrafiche/", views.articles, name="anagrafiche"),
    path("operazioni/<slug:op>/", views.operation, name="operation"),
    path("operazioni/<slug:op>/<int:pk>/", views.operation, name="record_operation"),
]
