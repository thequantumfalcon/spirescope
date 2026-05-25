(function() {
  var el = document.getElementById('live-config');
  if (!el) return;
  var player = parseInt(el.dataset.player, 10) || 0;
  var wasActive = el.dataset.wasActive === 'true';
  var es = new EventSource('/api/live/stream?player=' + player);
  var lastJson = '';
  var lastFloor = null;
  var lastReloadAt = 0;
  function safeReload() {
    // Cooldown 10s between reloads to prevent flap-loop on transient SSE state.
    var now = Date.now();
    if (now - lastReloadAt < 10000) return;
    lastReloadAt = now;
    location.reload();
  }
  es.onmessage = function(e) {
    if (e.data === lastJson) return;
    lastJson = e.data;
    var d;
    try {
      d = JSON.parse(e.data);
    } catch (err) {
      // Malformed payload (server crash mid-write, proxy buffering). Skip
      // this tick; preserve UI rather than freeze on a parse exception.
      return;
    }
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
    if (d.active !== wasActive) { safeReload(); return; }
    if (lastFloor !== null && d.floor !== lastFloor) { safeReload(); return; }
    lastFloor = d.floor;
  };
  var reloadTimer = null;
  es.onerror = function() {
    // Dedup: a flapping SSE connection can fire onerror many times in
    // quick succession. Without cancellation, each fires a 10s reload
    // timer and they pile up. Cancel any pending timer first.
    if (reloadTimer !== null) { clearTimeout(reloadTimer); }
    reloadTimer = setTimeout(function() { location.reload(); }, 10000);
  };
})();
