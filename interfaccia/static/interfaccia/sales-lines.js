const salesRows = Array.from(document.querySelectorAll('[data-sales-stock]')).map(stock => ({
  stock,
  component: stock.closest('tr')?.querySelector('[name$="-componente"]'),
  quantity: stock.closest('tr')?.querySelector('[data-sales-quantity]')
}));

function updateSalesAvailability() {
  const used = new Map();
  salesRows.forEach(({stock, quantity, component}) => {
    const kind = component?.value;
    const key = value => `${value}:${kind}`;
    const capacity = option => Number((kind === 'CONFEZIONATO' ? option?.dataset.packed : kind === 'SFUSO' ? option?.dataset.loose : option?.dataset.available) || 0);
    Array.from(stock.options).forEach(option => {
      if (!option.value) return;
      const available = capacity(option);
      const remaining = Math.max(available - (used.get(key(option.value)) || 0), 0);
      const base = option.dataset.baseLabel || option.textContent;
      option.textContent = `${base} · residuo ${remaining.toLocaleString('it-IT', {maximumFractionDigits: 6})}`;
      option.disabled = remaining <= 0 && option.value !== stock.value;
    });
    if (!stock.value || !quantity) return;
    const option = stock.selectedOptions[0];
    const availableBefore = Math.max(capacity(option) - (used.get(key(stock.value)) || 0), 0);
    quantity.max = String(availableBefore);
    const amount = Number(String(quantity.value).replace(',', '.')) || 0;
    used.set(key(stock.value), (used.get(key(stock.value)) || 0) + amount);
  });
}

salesRows.forEach(({stock, quantity, component}) => {
  component?.addEventListener('change', updateSalesAvailability);
  stock.addEventListener('change', updateSalesAvailability);
  quantity?.addEventListener('input', updateSalesAvailability);
});
updateSalesAvailability();
