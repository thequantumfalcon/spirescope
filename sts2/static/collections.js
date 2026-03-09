(function() {
  document.querySelectorAll('.deck-section-header').forEach(function(header) {
    header.addEventListener('click', function() {
      var section = header.closest('.deck-section');
      section.classList.toggle('collapsed');
      header.setAttribute('aria-expanded',
        String(!section.classList.contains('collapsed')));
    });
    header.addEventListener('keydown', function(e) {
      if (e.key === 'Enter' || e.key === ' ') {
        e.preventDefault();
        header.click();
      }
    });
  });
})();
