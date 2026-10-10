(function() {
  var btn = document.querySelector('.nav-toggle');
  if (btn) {
    btn.addEventListener('click', function() {
      var links = btn.nextElementSibling;
      if (links) {
        var open = links.classList.toggle('open');
        btn.setAttribute('aria-expanded', open ? 'true' : 'false');
      }
    });
  }
  var tb = document.querySelector('.theme-toggle');
  if (tb) {
    tb.addEventListener('click', function() {
      var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
      var next = isDark ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      // Without storage the choice still applies to this page; it is just
      // not remembered.
      try { localStorage.setItem('theme', next); } catch (e) { /* storage unavailable */ }
      tb.textContent = next === 'light' ? '\u2600' : '\u263E';
      tb.setAttribute('aria-label', next === 'light' ? 'Switch to dark mode' : 'Switch to light mode');
      var mc = document.querySelector('meta[name="theme-color"]');
      if (mc) mc.setAttribute('content', next === 'light' ? '#f5f0e8' : '#0c0a0e');
    });
    var cur = document.documentElement.getAttribute('data-theme');
    tb.textContent = cur === 'light' ? '\u2600' : '\u263E';
    tb.setAttribute('aria-label', cur === 'light' ? 'Switch to dark mode' : 'Switch to light mode');
  }
  // Stop button: POST /shutdown with CSRF token from meta tag.
  // Replaces the previous inline onclick handler (CSP-blocked) and includes
  // the CSRF header so the server can prove the request came from a real page.
  var sb = document.querySelector('.stop-btn');
  if (sb) {
    sb.addEventListener('click', function() {
      var meta = document.querySelector('meta[name="csrf-token"]');
      var token = meta ? meta.getAttribute('content') : '';
      fetch('/shutdown', {
        method: 'POST',
        headers: { 'X-CSRF-Token': token }
      }).then(function(response) {
        // fetch resolves on 403/500 too — only report success when it is one.
        if (response.ok) {
          document.body.innerHTML =
            '<h1 class="shutdown-msg">SpireScope stopped. You can close this tab.</h1>';
        } else {
          // The server explains a refusal (for example a data update still
          // installing) in a JSON error; show that rather than a bare status.
          response.json().then(function(body) {
            var reason = body && body.error ? body.error : 'HTTP ' + response.status;
            window.alert('Could not stop SpireScope: ' + reason);
          }, function() {
            window.alert('Could not stop SpireScope (HTTP ' + response.status + ').');
          });
        }
      }).catch(function() {
        // True network error — leave the page intact so the user can retry.
      });
    });
  }
  // Confirmation for destructive forms. Delegated here because the CSP
  // (script-src 'self') blocks inline onsubmit handlers.
  document.addEventListener('submit', function(e) {
    var form = e.target;
    if (form.classList && form.classList.contains('js-confirm')) {
      var msg = form.getAttribute('data-confirm') || 'Are you sure?';
      if (!window.confirm(msg)) e.preventDefault();
    }
  });
  // Copy seed button
  var cs = document.querySelector('.copy-seed');
  if (cs) {
    var flash = function(text) {
      cs.textContent = text;
      setTimeout(function() { cs.textContent = 'Copy'; }, 1500);
    };
    // navigator.clipboard only exists on secure origins, so a LAN visit over
    // plain http has none, and a browser may also refuse the write. Select
    // the seed instead and try the older copy command; if that fails too,
    // the selection is left for the user to copy.
    var fallback = function() {
      var text = document.getElementById('seed-text');
      var copied = false;
      if (text && window.getSelection && document.createRange) {
        var range = document.createRange();
        range.selectNodeContents(text);
        var selection = window.getSelection();
        selection.removeAllRanges();
        selection.addRange(range);
        try { copied = document.execCommand('copy'); } catch (e) { copied = false; }
      }
      flash(copied ? 'Copied!' : 'Seed selected');
    };
    cs.addEventListener('click', function() {
      var seed = cs.getAttribute('data-seed');
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(seed).then(function() { flash('Copied!'); }, fallback);
      } else {
        fallback();
      }
    });
  }
})();
