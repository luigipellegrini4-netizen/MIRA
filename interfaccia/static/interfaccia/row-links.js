document.querySelectorAll('[data-row-href]').forEach(row => {
  const openRow = event => {
    const target = event.target instanceof Element ? event.target : event.target.parentElement;
    if (target?.closest('a, button, input, select, textarea, label')) return;
    window.location.assign(row.dataset.rowHref);
  };

  row.addEventListener('click', openRow);
  row.addEventListener('keydown', event => {
    if (event.key !== 'Enter' && event.key !== ' ') return;
    event.preventDefault();
    openRow(event);
  });
});
