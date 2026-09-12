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

document.querySelectorAll('[data-picking-quantity]').forEach(quantityInput => {
  const panel = quantityInput.closest('.ingredient-panel');
  const lots = panel?.querySelector('[data-picking-lots]');
  if (!lots) return;
  quantityInput.addEventListener('input', () => {
    let remaining = Number(String(quantityInput.value).replace(',', '.')) || 0;
    Array.from(lots.options).forEach(option => {
      const available = Number(option.dataset.available) || 0;
      option.selected = remaining > 0 && available > 0;
      remaining -= option.selected ? available : 0;
    });
  });
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
