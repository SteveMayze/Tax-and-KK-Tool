// Progressive enhancement only: "All" / "None" buttons for each group of filter check boxes. Everything works without it.
(function () {
  var me = document.currentScript;
  document.querySelectorAll('[data-filter-group]').forEach(function (group) {
    var bar = document.createElement('p');
    bar.className = 'filter-tools';
    [['all', true], ['none', false]].forEach(function (pair) {
      var b = document.createElement('button');
      b.type = 'button';
      b.className = 'btn btn-secondary';
      b.textContent = me.dataset[pair[0]];
      b.addEventListener('click', function () {
        group.querySelectorAll('input[type=checkbox]').forEach(function (c) { c.checked = pair[1]; });
        group.querySelector('input[type=checkbox]') && group.querySelector('input[type=checkbox]').dispatchEvent(new Event('change', {bubbles: true}));
      });
      bar.appendChild(b);
    });
    group.insertBefore(bar, group.querySelector('.filter-options'));
  });
})();
