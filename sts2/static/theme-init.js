(function() {
  // Reading storage throws where site data is blocked or in a sandboxed
  // frame; the system preference still applies then.
  var stored = null;
  try { stored = localStorage.getItem('theme'); } catch (e) { /* storage unavailable */ }
  var t = stored ||
    (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  document.documentElement.setAttribute('data-theme', t);
  var mc = document.querySelector('meta[name="theme-color"]');
  if (mc) mc.setAttribute('content', t === 'light' ? '#f5f0e8' : '#0c0a0e');
})();
