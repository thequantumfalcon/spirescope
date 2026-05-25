// Overlay live updates. Diffs DOM in place rather than full-reloading on every
// SSE tick — the prior reload-every-3s pattern caused constant flicker and
// scroll/focus loss for OBS browser sources.
(function() {
  var player = new URLSearchParams(location.search).get('player') || '0';
  var es = new EventSource('/api/live/stream?player=' + player);
  var lastJson = '';
  var lastActive = null;
  var reloadAt = 0;
  function safeReload() {
    var now = Date.now();
    if (now - reloadAt < 10000) return;
    reloadAt = now;
    location.reload();
  }
  function setText(sel, val) {
    var el = document.querySelector(sel);
    if (el) el.textContent = val;
  }
  es.onmessage = function(e) {
    if (e.data === lastJson) return;
    lastJson = e.data;
    var d;
    try { d = JSON.parse(e.data); } catch (err) { return; }
    if (lastActive !== null && d.active !== lastActive) { safeReload(); return; }
    lastActive = d.active;
    setText('.live-hp', (d.current_hp || 0) + '/' + (d.max_hp || 0));
    setText('.live-gold', d.gold || 0);
    setText('.live-act', 'Act ' + (d.act || 1));
    setText('.live-floor', 'Floor ' + (d.floor || 0));
    setText('.live-cards', (d.deck || []).length);
    setText('.live-relics', (d.relics || []).length);
    setText('.live-potions', (d.potions || []).length);
    var fill = document.querySelector('.hp-fill');
    if (fill && d.max_hp > 0) fill.style.width = (d.current_hp / d.max_hp * 100) + '%';
  };
  var errorTimer = null;
  es.onerror = function() {
    if (errorTimer !== null) clearTimeout(errorTimer);
    errorTimer = setTimeout(safeReload, 5000);
  };
})();
