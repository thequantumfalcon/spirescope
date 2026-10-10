(function() {
  document.querySelectorAll('.deck-section-toggle').forEach(function(toggle) {
    toggle.addEventListener('click', function() {
      var section = toggle.closest('.deck-section');
      section.classList.toggle('collapsed');
      toggle.setAttribute('aria-expanded',
        String(!section.classList.contains('collapsed')));
    });
  });
})();
