// Live display of gross - net - withholding tax - expenses on the payment form. Display only: the server
// checks the identity again on save. Amounts are handled as integers in 1/10000 units (no floating point).
(function () {
  var out = document.getElementById('unallocated');
  if (!out) { return; }
  function field(name) { return document.getElementById('id_' + name); }
  function units(el, emptyIs) {
    var v = el ? el.value.trim() : '';
    if (v === '') { return emptyIs; }
    var m = /^(-?)(\d*)(?:\.(\d{0,4})\d*)?$/.exec(v);
    if (!m || (m[2] === '' && !m[3])) { return null; }
    var n = parseInt(m[2] || '0', 10) * 10000 + parseInt(((m[3] || '') + '0000').slice(0, 4), 10);
    return m[1] ? -n : n;
  }
  function show(n) {
    var sign = n < 0 ? '-' : '', a = Math.abs(n);
    return sign + Math.floor(a / 10000) + '.' + String(a % 10000).padStart(4, '0').slice(0, 2);
  }
  function update() {
    var g = units(field('gross_amount'), null), n = units(field('net_amount'), null);
    var w = units(field('withholding_tax'), 0), e = units(field('expenses'), 0);
    var ccy = field('currency') ? field('currency').value : '';
    if (g === null || n === null || w === null || e === null) {
      out.textContent = 'Unallocated: enter gross and net to see it.';
      return;
    }
    var u = g - n - w - e;
    out.textContent = 'Unallocated (gross - net - withholding tax - expenses): ' + show(u) + ' ' + ccy +
      (u === 0 ? ' (OK)' : ' (must be 0.00 to save)');
  }
  ['gross_amount', 'net_amount', 'withholding_tax', 'expenses', 'currency'].forEach(function (name) {
    var el = field(name);
    if (el) { el.addEventListener('input', update); el.addEventListener('change', update); }
  });
  update();
})();
