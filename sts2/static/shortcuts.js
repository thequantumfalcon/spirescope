(function() {
  var overlay = document.getElementById('shortcut-overlay');
  var routes = {
    'h': '/',
    'c': '/cards',
    'r': '/relics',
    'a': '/analytics',
    'd': '/deck',
    'l': '/live'
  };

  document.addEventListener('keydown', function(e) {
    var tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    if (e.key === '?') {
      e.preventDefault();
      if (overlay) {
        if (overlay.hidden) {
          overlay.hidden = false;
        } else {
          overlay.hidden = true;
        }
      }
      return;
    }

    if (e.key === 'Escape') {
      if (overlay && !overlay.hidden) {
        overlay.hidden = true;
        e.preventDefault();
        return;
      }
      return;
    }

    if (e.key === '/') {
      var deckSearch = document.getElementById('deck-search');
      var navSearch = document.querySelector('.search-form input[name="q"]');
      if (deckSearch) {
        e.preventDefault();
        deckSearch.focus();
      } else if (navSearch) {
        e.preventDefault();
        navSearch.focus();
      }
      return;
    }

    var dest = routes[e.key];
    if (dest && window.location.pathname !== dest) {
      window.location.href = dest;
    }
  });
})();
