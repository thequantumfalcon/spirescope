(function() {
  var KEY = 'spirescope_decks';
  function getDecks() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch(e) { return {}; } }
  function saveDecks(d) { localStorage.setItem(KEY, JSON.stringify(d)); }
  function refreshSelect() {
    var sel = document.getElementById('load-deck');
    if (!sel) return;
    var decks = getDecks();
    sel.innerHTML = '<option value="">Load saved deck...</option>';
    Object.keys(decks).sort().forEach(function(name) {
      var o = document.createElement('option'); o.value = name; o.textContent = name + ' (' + decks[name].length + ' cards)';
      sel.appendChild(o);
    });
  }
  function getChecked() {
    return Array.from(document.querySelectorAll('input[name="card_ids"]:checked')).map(function(cb) { return cb.value; });
  }
  function setChecked(ids) {
    document.querySelectorAll('input[name="card_ids"]').forEach(function(cb) { cb.checked = ids.indexOf(cb.value) !== -1; });
  }
  function detectCharacter(ids) {
    var chars = {};
    ids.forEach(function(id) {
      var parts = id.split('.');
      if (parts.length >= 2 && parts[0] === 'CARD') {
        var c = parts[1];
        if (c !== 'COLORLESS' && c !== 'STATUS' && c !== 'CURSE') chars[c] = (chars[c] || 0) + 1;
      }
    });
    var best = ''; var max = 0;
    for (var k in chars) { if (chars[k] > max) { max = chars[k]; best = k; } }
    return best || 'Unknown';
  }
  var saveBtn = document.getElementById('save-deck');
  if (saveBtn) {
    saveBtn.addEventListener('click', function() {
      var ids = getChecked();
      if (!ids.length) { alert('Select cards first.'); return; }
      var character = detectCharacter(ids);
      var name = prompt('Deck name (saving as ' + character + '):');
      if (!name) return;
      var key = character + ' / ' + name;
      var decks = getDecks(); decks[key] = ids; saveDecks(decks);
      refreshSelect();
    });
  }
  var loadSel = document.getElementById('load-deck');
  if (loadSel) {
    loadSel.addEventListener('change', function() {
      var name = this.value; if (!name) return;
      var decks = getDecks();
      if (decks[name]) setChecked(decks[name]);
    });
  }
  var deleteBtn = document.getElementById('delete-deck');
  if (deleteBtn) {
    deleteBtn.addEventListener('click', function() {
      var name = document.getElementById('load-deck').value;
      if (!name) { alert('Select a deck to delete.'); return; }
      var decks = getDecks(); delete decks[name]; saveDecks(decks);
      refreshSelect();
    });
  }
  refreshSelect();
})();
