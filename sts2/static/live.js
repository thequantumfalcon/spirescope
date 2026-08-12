(function() {
  var el = document.getElementById('live-config');
  if (!el) return;
  var player = parseInt(el.dataset.player, 10) || 0;
  var wasActive = el.dataset.wasActive === 'true';
  var es = null;
  var lastJson = '';
  var lastFloor = null;
  var lastReloadAt = 0;
  var reloadTimer = null;
  var reconnectTimer = null;
  function safeReload() {
    // Cooldown 10s between reloads to prevent flap-loop on transient SSE state.
    var now = Date.now();
    if (now - lastReloadAt < 10000) return;
    lastReloadAt = now;
    location.reload();
  }
  function setText(sel, text) {
    var node = document.querySelector(sel);
    if (node) node.textContent = text;
  }
  function renderDanger(danger) {
    var box = document.querySelector('.live-danger');
    if (!box) return;
    if (!danger || !danger.level) { box.textContent = ''; return; }
    var div = document.createElement('div');
    div.className = 'danger-banner danger-' + danger.level;
    div.setAttribute('role', 'alert');
    div.textContent = danger.level === 'critical'
      ? 'CRITICAL: ' + danger.hp_pct + '% HP — find healing immediately!'
      : 'WARNING: ' + danger.hp_pct + '% HP — consider resting or using potions';
    box.textContent = '';
    box.appendChild(div);
  }
  function renderGhost(ghost) {
    if (!ghost || !ghost.info) return;
    setText('.ghost-status', ghost.info.status);
    setText('.ghost-hp-delta', (ghost.info.current_hp_delta > 0 ? '+' : '') + ghost.info.current_hp_delta);
    setText('.ghost-gold-delta', (ghost.info.current_gold_delta > 0 ? '+' : '') + ghost.info.current_gold_delta);
    setText('.ghost-floors-ahead', ghost.info.floors_ahead + '/' + (ghost.info.floors_ahead + ghost.info.floors_behind));
    var box = document.querySelector('.ghost-splits');
    if (box && ghost.splits) {
      box.textContent = '';
      ghost.splits.forEach(function(s) {
        var span = document.createElement('span');
        span.className = 'tag ' + (s.ahead ? 'tag-skill' : 'tag-attack');
        span.textContent = 'F' + s.floor + ': ' + (s.hp_delta > 0 ? '+' : '') + s.hp_delta + ' HP';
        box.appendChild(span);
      });
    }
  }
  function connect() {
    es = new EventSource('/api/live/stream?player=' + player);
    es.onmessage = function(e) {
      // A healthy message means the stream recovered — cancel any reload the
      // error handler scheduled, or a spurious full reload fires 10s later.
      if (reloadTimer !== null) { clearTimeout(reloadTimer); reloadTimer = null; }
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
      setText('.live-gold', d.gold);
      setText('.live-act', 'Act ' + d.act);
      setText('.live-floor', 'Floor ' + d.floor);
      setText('.live-cards', d.deck.length);
      setText('.live-relics', d.relics.length);
      setText('.live-potions', d.potions.length);
      var fill = document.querySelector('.hp-fill');
      if (fill && d.max_hp > 0) fill.style.width = (d.current_hp / d.max_hp * 100) + '%';
      renderDanger(d.danger);
      renderGhost(d.ghost);
      if (d.active !== wasActive) { safeReload(); return; }
      if (lastFloor !== null && d.floor !== lastFloor) { safeReload(); return; }
      lastFloor = d.floor;
    };
    // The server closes an idle stream after 5 minutes. A paused run that
    // later resumes must still reach this page, so reconnect instead of
    // going stale forever — close the dead stream and open a fresh one
    // after a short delay. The reconnectTimer !== null guard means a
    // second 'timeout' (e.g. right after reconnecting into another idle
    // period) can't stack another pending reconnect on top of it.
    es.addEventListener('timeout', function() {
      es.close();
      if (reloadTimer !== null) { clearTimeout(reloadTimer); reloadTimer = null; }
      if (reconnectTimer === null) {
        reconnectTimer = setTimeout(function() {
          reconnectTimer = null;
          connect();
        }, 15000);
      }
    });
    es.onerror = function() {
      // Dedup: a flapping SSE connection can fire onerror many times in
      // quick succession. Without cancellation, each fires a 10s reload
      // timer and they pile up. Cancel any pending timer first.
      if (reloadTimer !== null) { clearTimeout(reloadTimer); }
      reloadTimer = setTimeout(function() { location.reload(); }, 10000);
    };
  }
  connect();
})();
