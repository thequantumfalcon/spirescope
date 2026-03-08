(function() {
  var t = localStorage.getItem('theme') ||
    (window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark');
  document.documentElement.setAttribute('data-theme', t);
  var mc = document.querySelector('meta[name="theme-color"]');
  if (mc) mc.setAttribute('content', t === 'light' ? '#f8f9fa' : '#0d1117');
})();
