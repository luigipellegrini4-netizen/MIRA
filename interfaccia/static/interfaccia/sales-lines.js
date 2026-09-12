const salesRows = Array.from(document.querySelectorAll('[data-sales-stock]')).map(stock => ({
  stock,
  quantity: stock.closest('tr')?.querySelector('[data-sales-quantity]')
}));

function updateSalesAvailability() {
  const used = new Map();
  salesRows.forEach(({stock, quantity}) => {
    Array.from(stock.options).forEach(option => {
      if (!option.value) return;
      const available = Number(option.dataset.available || 0);
      const remaining = Math.max(available - (used.get(option.value) || 0), 0);
      const base = option.dataset.baseLabel || option.textContent;
      option.textContent = `${base} · residuo ${remaining.toLocaleString('it-IT', {maximumFractionDigits: 6})}`;
      option.disabled = remaining <= 0 && option.value !== stock.value;
    });
    if (!stock.value || !quantity) return;
    const option = stock.selectedOptions[0];
    const availableBefore = Math.max(Number(option?.dataset.available || 0) - (used.get(stock.value) || 0), 0);
    quantity.max = String(availableBefore);
    const amount = Number(String(quantity.value).replace(',', '.')) || 0;
    used.set(stock.value, (used.get(stock.value) || 0) + amount);
  });
}

salesRows.forEach(({stock, quantity}) => {
  stock.addEventListener('change', updateSalesAvailability);
  quantity?.addEventListener('input', updateSalesAvailability);
});
updateSalesAvailability();
