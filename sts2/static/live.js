(function() {
  var el = document.getElementById('live-config');
  if (!el) return;
  var player = parseInt(el.dataset.player, 10) || 0;
  var wasActive = el.dataset.wasActive === 'true';
  var es = null;
  var lastJson = '';
  var lastFloor = null;
  // Content revision (deck, upgrades, enchantments, relics, potions, ...)
  // of what the server rendered. Counters are patched in place below, but
  // the card/item lists and deck analysis are server-rendered, so a
  // same-floor change to them needs a reload just like a floor change.
  var pageRevision = el.dataset.revision || '';
  var lastRevision = null;
  var lastReloadAt = 0;
  var reconnectTimer = null;
  // A stream that fails or drops is retried after 5 s, doubling to a 60 s
  // cap, and given up after RETRY_LIMIT attempts in a row (about 5 minutes).
  // A message resets the count. Reloading the page instead, as this used to,
  // never got past a refused stream (a 429 is not retried by EventSource)
  // and replaced the page with the browser's error page once the server
  // stopped.
  var RETRY_BASE_MS = 5000;
  var RETRY_MAX_MS = 60000;
  var RETRY_LIMIT = 8;
  var retries = 0;
  var statusEl = document.getElementById('live-connection');
  function showStatus(text) {
    if (!statusEl) return;
    statusEl.textContent = text;
    statusEl.hidden = !text;
  }
  function safeReload() {
    // Cooldown 10s between reloads to prevent flap-loop on transient SSE state.
    var now = Date.now();
    if (now - lastReloadAt < 10000) return;
    lastReloadAt = now;
    try {
      var focused = document.activeElement;
      sessionStorage.setItem('spirescope-live-view', JSON.stringify({
        x: window.scrollX, y: window.scrollY, id: focused && focused.id,
        start: focused && focused.selectionStart, end: focused && focused.selectionEnd
      }));
    } catch (err) { /* Storage and selection APIs are optional. */ }
    location.reload();
  }
  function firstReloadFor(rev) {
    // The first message is compared with the rendered page, which may be
    // older than the stream. Reload at most once per revision (remembered
    // across the reload) so a page and stream that persistently disagree
    // cannot loop. No storage means no first-message reload at all.
    try {
      var key = 'spirescope-live-revision-reload';
      if (window.sessionStorage.getItem(key) === rev) return false;
      window.sessionStorage.setItem(key, rev);
      return true;
    } catch (err) {
      return false;
    }
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
      // A healthy message means the stream recovered.
      retries = 0;
      if (statusEl && !statusEl.hidden) showStatus('');
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
      if (d.revision) {
        if (lastRevision === null) {
          if (pageRevision && d.revision !== pageRevision && firstReloadFor(d.revision)) {
            safeReload(); return;
          }
        } else if (d.revision !== lastRevision) {
          // lastRevision is left as-is, so if the reload cooldown swallowed
          // this one the next message retries it.
          safeReload(); return;
        }
        lastRevision = d.revision;
      }
    };
    // The server closes an idle stream after 5 minutes. A paused run that
    // later resumes must still reach this page, so reconnect instead of
    // going stale forever — close the dead stream and open a fresh one
    // after a short delay. The reconnectTimer !== null guard means a
    // second 'timeout' (e.g. right after reconnecting into another idle
    // period) can't stack another pending reconnect on top of it.
    es.addEventListener('timeout', function() {
      es.close();
      if (reconnectTimer === null) {
        reconnectTimer = setTimeout(function() {
          reconnectTimer = null;
          connect();
        }, 15000);
      }
    });
    // Fires for a refused or dropped connection, and for the server's own
    // 'error' event, which carries a reason. Closing first stops the
    // browser's built-in retry so the schedule above is the only one.
    es.onerror = function(e) {
      es.close();
      if (reconnectTimer !== null) return;
      var reason = '';
      if (typeof e.data === 'string') {
        try { reason = JSON.parse(e.data).reason || ''; } catch (err) { /* no reason given */ }
      }
      if (reason === 'too_many') {
        // Retrying cannot help until another live page closes.
        showStatus('Live updates are off: too many live pages are open. Close another Spirescope tab, then reload this page.');
        return;
      }
      if (retries >= RETRY_LIMIT) {
        showStatus('Live updates stopped: Spirescope could not be reached. Reload the page to try again.');
        return;
      }
      var delay = Math.min(RETRY_BASE_MS * Math.pow(2, retries), RETRY_MAX_MS);
      retries++;
      showStatus('Lost the connection to Spirescope. Retrying in ' + Math.round(delay / 1000) + ' s.');
      reconnectTimer = setTimeout(function() {
        reconnectTimer = null;
        connect();
      }, delay);
    };
  }
  try {
    var saved = JSON.parse(sessionStorage.getItem('spirescope-live-view') || 'null');
    sessionStorage.removeItem('spirescope-live-view');
    if (saved) {
      window.scrollTo(saved.x, saved.y);
      var focused = saved.id && document.getElementById(saved.id);
      if (focused) {
        focused.focus({preventScroll: true});
        if (focused.setSelectionRange && saved.start !== null) focused.setSelectionRange(saved.start, saved.end);
      }
    }
  } catch (err) { /* Preserve normal startup when storage is unavailable. */ }
  connect();
})();
