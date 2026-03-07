(function() {
  var btn = document.querySelector('.nav-toggle');
  if (btn) {
    btn.addEventListener('click', function() {
      var links = btn.nextElementSibling;
      if (links) links.classList.toggle('open');
    });
  }
})();
