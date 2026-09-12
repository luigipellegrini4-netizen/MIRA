document.querySelectorAll('form[data-submit-once]').forEach(form => {
  form.addEventListener('submit', () => {
    form.querySelectorAll('button[type="submit"]').forEach(button => {
      button.disabled = true;
      button.textContent = 'Registrazione in corso…';
    });
  });
});
window.addEventListener('pageshow', event => {
  if (event.persisted) window.location.reload();
});
document.querySelector('[data-add-planned-row]')?.addEventListener('click', event => {
  const total = document.querySelector('#id_form-TOTAL_FORMS');
  const count = Number(total.value);
  if (count >= 200) return;
  const template = document.querySelector('#planned-row-template');
  document.querySelector('#planned-rows').insertAdjacentHTML('beforeend', template.innerHTML.replaceAll('__prefix__', String(count)));
  total.value = String(count + 1);
  if (count + 1 >= 200) event.currentTarget.disabled = true;
});

document.querySelector('[data-picking-rows]')?.addEventListener('click', event => {
  const removeButton = event.target.closest('[data-remove-picking-row]');
  if (removeButton) {
    const row = removeButton.closest('[data-picking-row]');
    const deletion = row.querySelector('input[name$="-DELETE"]');
    if (deletion) {
      deletion.value = 'on';
      row.hidden = true;
    }
    return;
  }
  const button = event.target.closest('[data-add-picking-row]');
  if (!button) return;
  const rows = button.closest('[data-picking-rows]');
  const source = button.closest('[data-picking-row]');
  const total = source.closest('form').querySelector('[name="form-TOTAL_FORMS"]');
  const index = Number(total.value);
  if (index >= 100) return;
  const clone = source.cloneNode(true);
  clone.innerHTML = clone.innerHTML.replace(/form-\d+-/g, `form-${index}-`);
  clone.querySelectorAll('.errorlist').forEach(error => error.remove());
  clone.querySelectorAll('select').forEach(select => { select.selectedIndex = 0; });
  clone.querySelectorAll('input:not([type="hidden"])').forEach(input => { input.value = ''; });
  const deletion = clone.querySelector('input[name$="-DELETE"]');
  if (deletion) deletion.value = '';
  source.after(clone);
  total.value = String(index + 1);
});

document.querySelectorAll('[data-control-type]').forEach(selector => {
  const form = selector.closest('form');
  const number = form.querySelector('[data-control-number]');
  const updateControlFields = changeNumber => {
    form.querySelectorAll('[data-control-for]').forEach(input => {
      const visible = input.dataset.controlFor.split(',').includes(selector.value);
      const container = input.closest('p') || input.closest('.field');
      if (container) container.hidden = !visible;
      input.disabled = !visible;
    });
    if (changeNumber && number) {
      number.value = selector.dataset[`next${selector.value.charAt(0)}${selector.value.slice(1).toLowerCase()}`] || 1;
    }
  };
  selector.addEventListener('change', () => updateControlFields(true));
  updateControlFields(false);
});

document.querySelectorAll('[data-stock-article]').forEach(articleSelector => {
  const key = articleSelector.dataset.stockArticle;
  const stockSelector = articleSelector.form.querySelector(`[data-stock-for="${key}"]`);
  if (!stockSelector) return;
  const allOptions = Array.from(stockSelector.options).map(option => option.cloneNode(true));
  const updateStocks = autoSelect => {
    const articleId = articleSelector.value;
    const previousValues = new Set(Array.from(stockSelector.selectedOptions).map(option => option.value));
    const options = allOptions
      .filter(option => !option.value || option.dataset.article === articleId)
      .map(option => option.cloneNode(true));
    stockSelector.replaceChildren(...options);
    stockSelector.disabled = !articleId;
    if (articleId) {
      const hasPrevious = options.some(option => option.value && previousValues.has(option.value));
      options.forEach(option => {
        option.selected = option.value && (hasPrevious ? previousValues.has(option.value) : Boolean(autoSelect && stockSelector.multiple));
      });
    }
  };
  articleSelector.addEventListener('change', () => updateStocks(true));
  updateStocks(false);
});

document.querySelectorAll('[data-nc-action-type]').forEach(selector => {
  const form = selector.closest('form');
  const updateActionFields = () => {
    form.querySelectorAll('[data-nc-action-for]').forEach(input => {
      const allowed = input.dataset.ncActionFor.split(',').includes(selector.value);
      const container = input.closest('.field') || input.closest('p');
      if (container) container.hidden = !allowed;
      input.disabled = !allowed;
    });
  };
  selector.addEventListener('change', updateActionFields);
  updateActionFields();
});
