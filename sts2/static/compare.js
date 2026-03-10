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

  // Handle data-auto-submit (replaces inline onchange for CSP compliance)
  var autoSubmit = document.querySelector('[data-auto-submit]');
  if (autoSubmit) {
    autoSubmit.addEventListener('change', function() {
      this.form.submit();
    });
  }
})();
