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

document.querySelectorAll('[data-control-type]').forEach(selector => {
  const form = selector.closest('form');
  const number = form.querySelector('[data-control-number]');
  const updateControlFields = changeNumber => {
    form.querySelectorAll('[data-control-for]').forEach(input => {
      const visible = input.dataset.controlFor === selector.value;
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
