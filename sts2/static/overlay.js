// Overlay live updates. Diffs DOM in place rather than full-reloading on every
// SSE tick — the prior reload-every-3s pattern caused constant flicker and
// scroll/focus loss for OBS browser sources.
(function() {
  var player = new URLSearchParams(location.search).get('player') || '0';
  var es = null;
  var lastJson = '';
  var lastActive = null;
  var reloadAt = 0;
  var errorTimer = null;
  var reconnectTimer = null;
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
  function connect() {
    es = new EventSource('/api/live/stream?player=' + player);
    es.onmessage = function(e) {
      // Data means the stream is healthy: drop any reload an error scheduled.
      if (errorTimer !== null) { clearTimeout(errorTimer); errorTimer = null; }
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
      if (fill && d.max_hp > 0) {
        var pct = d.current_hp / d.max_hp * 100;
        fill.style.width = pct + '%';
        // Unlike live.js this view never reloads on floor change, so the class
        // baked in at render time would otherwise stay for the whole run — a
        // healed player kept a red bar on stream. Thresholds match overlay.html.
        var tone = pct > 60 ? 'hp-healthy' : (pct > 30 ? 'hp-warning' : 'hp-critical');
        fill.className = 'hp-fill ' + tone;
      }
    };
    // The server ends a stream after 5 quiet minutes with a 'timeout' event.
    // Closing here keeps the end of that stream from reaching onerror, which
    // reloaded the whole OBS source after every quiet stretch; reconnect
    // quietly instead (same delay as live.js).
    es.addEventListener('timeout', function() {
      es.close();
      if (errorTimer !== null) { clearTimeout(errorTimer); errorTimer = null; }
      if (reconnectTimer === null) {
        reconnectTimer = setTimeout(function() {
          reconnectTimer = null;
          connect();
        }, 15000);
      }
    });
    es.onerror = function() {
      if (errorTimer !== null) clearTimeout(errorTimer);
      errorTimer = setTimeout(safeReload, 5000);
    };
  }
  connect();
})();
