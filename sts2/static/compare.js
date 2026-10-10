(function() {
  'use strict';
  var selected = [];
  var btn = document.getElementById('compare-btn');
  var checkboxes = document.querySelectorAll('.compare-check');

  function updateBtn() {
    if (btn) { btn.disabled = selected.length !== 2; }
  }

  for (var i = 0; i < checkboxes.length; i++) {
    checkboxes[i].addEventListener('change', function() {
      var id = this.getAttribute('data-run-id');
      if (this.checked) {
        selected.push(id);
        if (selected.length > 2) {
          var oldest = selected.shift();
          for (var j = 0; j < checkboxes.length; j++) {
            if (checkboxes[j].getAttribute('data-run-id') === oldest) {
              checkboxes[j].checked = false;
            }
          }
        }
      } else {
        var idx = selected.indexOf(id);
        if (idx !== -1) { selected.splice(idx, 1); }
      }
      updateBtn();
    });
  }

  if (btn) {
    btn.addEventListener('click', function() {
      if (selected.length === 2) {
        window.location.href = '/runs/compare?a=' + encodeURIComponent(selected[0]) + '&b=' + encodeURIComponent(selected[1]);
      }
    });
  }

  // Handle data-auto-submit (replaces inline onchange for CSP compliance).
  // requestSubmit(), unlike submit(), fires the submit event, so js-confirm
  // and other listeners run. Only a submission that went ahead marks the
  // form as sent; a cancelled confirm leaves it usable.
  function autoSubmit(form) {
    if (!form || form.getAttribute('data-submitting') === '1') return;
    var submitEvent = null;
    function record(e) { submitEvent = e; }
    form.addEventListener('submit', record);
    form.requestSubmit();
    form.removeEventListener('submit', record);
    if (submitEvent && !submitEvent.defaultPrevented) form.setAttribute('data-submitting', '1');
  }
  var autoSubmits = document.querySelectorAll('[data-auto-submit]');
  for (var k = 0; k < autoSubmits.length; k++) {
    autoSubmits[k].addEventListener('change', function() {
      autoSubmit(this.form);
    });
  }
  // A page restored from the back/forward cache must accept changes again.
  window.addEventListener('pageshow', function(e) {
    if (!e.persisted) return;
    var sent = document.querySelectorAll('form[data-submitting]');
    for (var m = 0; m < sent.length; m++) sent[m].removeAttribute('data-submitting');
  });
})();
