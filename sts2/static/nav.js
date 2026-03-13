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
