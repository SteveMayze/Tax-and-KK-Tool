// Progressive enhancement: let text areas grow with their content in browsers without CSS field-sizing.
(function () {
  if (window.CSS && CSS.supports && CSS.supports('field-sizing', 'content')) { return; }
  function fit(el) { el.style.height = 'auto'; el.style.height = el.scrollHeight + 2 + 'px'; }
  document.querySelectorAll('textarea').forEach(function (el) {
    fit(el);
    el.addEventListener('input', function () { fit(el); });
  });
})();
