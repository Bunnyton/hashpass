/* Live filter: <input data-filter='<rows selector>'> hides rows whose data-text lacks the query. */
document.querySelectorAll('input[data-filter]').forEach((input) => {
  const rows = () => document.querySelectorAll(input.dataset.filter);
  input.addEventListener('input', () => {
    const q = input.value.trim().toLowerCase();
    rows().forEach((row) => {
      row.hidden = q !== '' && !(row.dataset.text || row.textContent).toLowerCase().includes(q);
    });
  });
});
