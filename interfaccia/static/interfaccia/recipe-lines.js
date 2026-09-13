const recipeEditor = document.querySelector('[data-recipe-editor]');

if (recipeEditor) {
  const rows = recipeEditor.querySelector('[data-recipe-lines]');
  const totalInput = recipeEditor.querySelector('[name$="-TOTAL_FORMS"]');
  const template = recipeEditor.querySelector('[data-recipe-template]');
  const addButton = recipeEditor.querySelector('[data-add-recipe-line]');
  const totals = recipeEditor.querySelector('[data-recipe-totals]');

  const visibleRows = () => Array.from(rows.querySelectorAll('[data-recipe-line]')).filter(row => !row.hidden);

  const updateTotals = () => {
    const sums = new Map();
    visibleRows().forEach(row => {
      const article = row.querySelector('[data-recipe-article]');
      const quantity = row.querySelector('[data-recipe-quantity]');
      const unit = article?.selectedOptions[0]?.dataset.unit;
      const amount = Number(String(quantity?.value || '').replace(',', '.'));
      if (unit && Number.isFinite(amount) && amount > 0) sums.set(unit, (sums.get(unit) || 0) + amount);
    });
    totals.replaceChildren();
    const label = document.createElement('span');
    label.textContent = 'Totale teorico per batch:';
    totals.append(label);
    if (!sums.size) {
      const empty = document.createElement('span');
      empty.className = 'pill neutral'; empty.textContent = '—'; totals.append(empty);
    }
    sums.forEach((amount, unit) => {
      const badge = document.createElement('span');
      badge.className = 'pill neutral';
      badge.textContent = `${amount.toLocaleString('it-IT', {maximumFractionDigits: 6})} ${unit}`;
      totals.append(badge);
    });
    const emptyMessage = rows.querySelector('[data-recipe-empty]');
    if (emptyMessage) emptyMessage.hidden = visibleRows().length > 0;
  };

  const bindRow = row => {
    const article = row.querySelector('[data-recipe-article]');
    const quantity = row.querySelector('[data-recipe-quantity]');
    const unit = row.querySelector('[data-recipe-unit]');
    const remove = row.querySelector('[data-remove-recipe-line]');
    const deletion = row.querySelector('[name$="-DELETE"]');
    const updateUnit = () => {
      unit.textContent = article?.selectedOptions[0]?.dataset.unit || '—';
      updateTotals();
    };
    article?.addEventListener('change', updateUnit);
    quantity?.addEventListener('input', updateTotals);
    remove?.addEventListener('click', () => {
      if (deletion) deletion.checked = true;
      row.hidden = true;
      updateTotals();
    });
    updateUnit();
  };

  rows.querySelectorAll('[data-recipe-line]').forEach(bindRow);
  addButton?.addEventListener('click', () => {
    const index = Number(totalInput.value);
    if (index >= 100) return;
    rows.insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', String(index)));
    totalInput.value = String(index + 1);
    bindRow(rows.lastElementChild);
    if (index + 1 >= 100) addButton.disabled = true;
  });
  updateTotals();
}
