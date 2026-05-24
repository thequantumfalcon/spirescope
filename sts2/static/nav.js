(function() {
  var btn = document.querySelector('.nav-toggle');
  if (btn) {
    btn.addEventListener('click', function() {
      var links = btn.nextElementSibling;
      if (links) links.classList.toggle('open');
    });
  }
  var tb = document.querySelector('.theme-toggle');
  if (tb) {
    tb.addEventListener('click', function() {
      var isDark = document.documentElement.getAttribute('data-theme') !== 'light';
      var next = isDark ? 'light' : 'dark';
      document.documentElement.setAttribute('data-theme', next);
      localStorage.setItem('theme', next);
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
      }).then(function() {
        document.body.innerHTML =
          '<h1 class="shutdown-msg">SpireScope stopped. You can close this tab.</h1>';
      }).catch(function() {
        // Network error or 403 — leave page intact so user knows something failed
      });
    });
  }
  // Copy seed button
  var cs = document.querySelector('.copy-seed');
  if (cs) {
    cs.addEventListener('click', function() {
      var seed = cs.getAttribute('data-seed');
      if (navigator.clipboard) {
        navigator.clipboard.writeText(seed).then(function() {
          cs.textContent = 'Copied!';
          setTimeout(function() { cs.textContent = 'Copy'; }, 1500);
        });
      }
    });
  }
})();
