(function() {
  var overlay = document.getElementById('shortcut-overlay');
  var overlayContent = overlay ? overlay.querySelector('.shortcut-overlay-content') : null;
  var trigger = document.querySelector('.shortcuts-btn');
  var routes = {
    'h': '/',
    'c': '/cards',
    'r': '/relics',
    'a': '/analytics',
    'd': '/deck',
    'l': '/live'
  };

  // Element focused right before the dialog opened, so closing it can put
  // focus back where the user was instead of dropping it to <body>.
  var invoker = null;

  function focusableInOverlay() {
    if (!overlay) return [];
    return Array.prototype.slice.call(
      overlay.querySelectorAll('button, [href], input, select, textarea, [tabindex]:not([tabindex="-1"])')
    ).filter(function(el) { return !el.disabled && el.offsetParent !== null; });
  }

  function openOverlay() {
    if (!overlay) return;
    invoker = document.activeElement;
    overlay.hidden = false;
    var focusables = focusableInOverlay();
    (focusables[0] || overlayContent || overlay).focus();
  }

  function closeOverlay() {
    if (!overlay) return;
    overlay.hidden = true;
    if (invoker && typeof invoker.focus === 'function') invoker.focus();
    invoker = null;
  }

  if (trigger) {
    trigger.addEventListener('click', function() {
      if (overlay && overlay.hidden) {
        openOverlay();
      } else {
        closeOverlay();
      }
    });
  }

  document.addEventListener('keydown', function(e) {
    var tag = e.target.tagName;
    if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
    if (e.ctrlKey || e.altKey || e.metaKey) return;

    if (e.key === '?') {
      e.preventDefault();
      if (overlay) {
        if (overlay.hidden) {
          openOverlay();
        } else {
          closeOverlay();
        }
      }
      return;
    }

    if (e.key === 'Escape') {
      if (overlay && !overlay.hidden) {
        closeOverlay();
        e.preventDefault();
        return;
      }
      return;
    }

    if (e.key === 'Tab' && overlay && !overlay.hidden) {
      // Focus trap: keep Tab/Shift+Tab cycling inside the dialog while open.
      var focusables = focusableInOverlay();
      if (focusables.length === 0) {
        e.preventDefault();
        (overlayContent || overlay).focus();
        return;
      }
      var first = focusables[0];
      var last = focusables[focusables.length - 1];
      if (e.shiftKey && document.activeElement === first) {
        e.preventDefault();
        last.focus();
      } else if (!e.shiftKey && document.activeElement === last) {
        e.preventDefault();
        first.focus();
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
