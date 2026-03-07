(function() {
  var el = document.getElementById('live-config');
  if (!el) return;
  var player = parseInt(el.dataset.player, 10) || 0;
  var wasActive = el.dataset.wasActive === 'true';
  var es = new EventSource('/api/live/stream?player=' + player);
  var lastJson = '';
  es.onmessage = function(e) {
    if (e.data !== lastJson) {
      lastJson = e.data;
      var d = JSON.parse(e.data);
      var hp = document.querySelector('.live-hp');
      if (hp) hp.textContent = d.current_hp + '/' + d.max_hp;
      var gold = document.querySelector('.live-gold');
      if (gold) gold.textContent = d.gold;
      var act = document.querySelector('.live-act');
      if (act) act.textContent = 'Act ' + d.act;
      var floor = document.querySelector('.live-floor');
      if (floor) floor.textContent = 'Floor ' + d.floor;
      var cards = document.querySelector('.live-cards');
      if (cards) cards.textContent = d.deck.length;
      var relics = document.querySelector('.live-relics');
      if (relics) relics.textContent = d.relics.length;
      var potions = document.querySelector('.live-potions');
      if (potions) potions.textContent = d.potions.length;
      var fill = document.querySelector('.hp-fill');
      if (fill && d.max_hp > 0) fill.style.width = (d.current_hp / d.max_hp * 100) + '%';
      if (d.active !== wasActive) location.reload();
    }
  };
  es.onerror = function() {
    setTimeout(function() { location.reload(); }, 10000);
  };
})();
