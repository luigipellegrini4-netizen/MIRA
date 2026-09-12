from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone

from magazzino.models import Movimento
from magazzino.services import MovementService, Position
from interfaccia.views import permitted, paged
from .forms import ClienteForm, RigheVenditaFormSet, VenditaForm
from .models import Cliente, RigaVendita, Vendita


@permitted("auth.can_manage_sales")
def sales(request):
    query = request.GET.get("q", "").strip()[:150]
    rows = Vendita.objects.select_related("cliente", "registrata_da").prefetch_related("righe__movimento__lotto__articolo")
    if query:
        rows = rows.filter(Q(numero_documento__icontains=query) | Q(cliente__ragione_sociale__icontains=query) | Q(righe__movimento__lotto__codice_lotto__icontains=query)).distinct()
    return render(request, "vendite/sales.html", {"section": "vendite", "page": paged(request, rows), "q": query})


@permitted("auth.can_manage_sales")
def customers(request):
    rows = Cliente.objects.all()
    return render(request, "vendite/customers.html", {"section": "vendite", "rows": rows})


@permitted("auth.can_manage_sales")
def customer_edit(request, pk=None):
    obj = get_object_or_404(Cliente, pk=pk) if pk else None
    form = ClienteForm(request.POST or None, instance=obj)
    if request.method == "POST" and form.is_valid():
        form.save(); messages.success(request, "Cliente salvato."); return redirect("ui:sales_customers")
    return render(request, "vendite/form.html", {"section": "vendite", "title": "Modifica cliente" if obj else "Nuovo cliente", "form": form})


@permitted("auth.can_manage_sales")
def sale_new(request):
    form = VenditaForm(request.POST or None, initial={"data_documento": timezone.localdate()})
    lines = RigheVenditaFormSet(request.POST or None, prefix="righe")
    if request.method == "POST" and form.is_valid() and lines.is_valid():
        active = [row for row in lines.cleaned_data if row and row.get("giacenza")]
        if not active:
            lines._non_form_errors = lines.error_class(["Inserire almeno una riga di vendita."])
        else:
            try:
                with transaction.atomic():
                    sale = Vendita.objects.create(registrata_da=request.user, **form.cleaned_data)
                    for row in active:
                        stock = row["giacenza"]
                        movement = MovementService.register(actor=request.user, lotto=stock.lotto, tipo=Movimento.Tipo.VENDITA,
                            quantita=row["quantita"], origine=Position(stock.ubicazione_id, stock.scaffale, stock.piano),
                            note=f"Vendita {sale.numero_documento} · {sale.cliente.ragione_sociale}")
                        RigaVendita.objects.create(vendita=sale, movimento=movement)
            except ValidationError as exc:
                form.add_error(None, " · ".join(exc.messages))
            else:
                messages.success(request, "Vendita registrata e giacenze scaricate."); return redirect("ui:sales")
    return render(request, "vendite/sale_form.html", {"section": "vendite", "form": form, "lines": lines})
