(function() {
  var KEY = 'spirescope_decks';
  var MAX_QTY = 5;
  var cardQtys = {};

  // Initialize qty map from DOM (picks up server-rendered quantities)
  document.querySelectorAll('.deck-card[data-card-id]').forEach(function(el) {
    var id = el.getAttribute('data-card-id');
    if (!id) return;
    var qtyEl = el.querySelector('.qty-count');
    cardQtys[id] = qtyEl ? parseInt(qtyEl.textContent, 10) || 0 : 0;
  });

  function getDecks() { try { return JSON.parse(localStorage.getItem(KEY)) || {}; } catch(e) { return {}; } }
  function saveDecks(d) { localStorage.setItem(KEY, JSON.stringify(d)); }

  function getSelectedCards() {
    var result = {};
    for (var id in cardQtys) {
      if (cardQtys[id] > 0) result[id] = cardQtys[id];
    }
    return result;
  }

  function totalSelected() {
    var sum = 0;
    for (var id in cardQtys) sum += cardQtys[id];
    return sum;
  }

  function setCardQty(cardId, qty) {
    qty = Math.max(0, Math.min(MAX_QTY, qty));
    cardQtys[cardId] = qty;
    var el = document.querySelector('.deck-card[data-card-id="' + cardId + '"]');
    if (!el) return;
    var qtyEl = el.querySelector('.qty-count');
    if (qtyEl) qtyEl.textContent = qty;
    el.classList.toggle('deck-card--selected', qty > 0);
  }

  function setQuantities(data) {
    // Reset all to 0
    for (var id in cardQtys) setCardQty(id, 0);

    if (Array.isArray(data)) {
      // Old format: array of IDs — count occurrences
      var counts = {};
      data.forEach(function(id) { counts[id] = (counts[id] || 0) + 1; });
      for (var id in counts) {
        if (id in cardQtys) setCardQty(id, counts[id]);
      }
    } else if (data && typeof data === 'object') {
      // New format: {card_id: qty}
      for (var id in data) {
        if (id in cardQtys) setCardQty(id, data[id]);
      }
    }

    // Auto-expand sections with selected cards
    document.querySelectorAll('.deck-section').forEach(function(sec) {
      if (sec.querySelector('.deck-card--selected')) {
        sec.classList.remove('collapsed');
        var h = sec.querySelector('.deck-section-header');
        if (h) h.setAttribute('aria-expanded', 'true');
      }
    });
    updateCounts();
  }

  function detectCharacter(selected) {
    var chars = {};
    var ids = (typeof selected === 'object' && !Array.isArray(selected)) ? selected : {};
    for (var id in ids) {
      var parts = id.split('.');
      if (parts.length >= 2 && parts[0] === 'CARD') {
        var c = parts[1];
        if (c !== 'COLORLESS' && c !== 'STATUS' && c !== 'CURSE') {
          chars[c] = (chars[c] || 0) + ids[id];
        }
      }
    }
    var best = ''; var max = 0;
    for (var k in chars) { if (chars[k] > max) { max = chars[k]; best = k; } }
    return best || 'Unknown';
  }

  function deckCardCount(selected) {
    var sum = 0;
    for (var id in selected) sum += selected[id];
    return sum;
  }

  function refreshSelect() {
    var sel = document.getElementById('load-deck');
    if (!sel) return;
    var decks = getDecks();
    sel.innerHTML = '<option value="">Load saved deck...</option>';
    Object.keys(decks).sort().forEach(function(name) {
      var d = decks[name];
      var count = Array.isArray(d) ? d.length : deckCardCount(d);
      var o = document.createElement('option'); o.value = name; o.textContent = name + ' (' + count + ' cards)';
      sel.appendChild(o);
    });
  }

  var saveBtn = document.getElementById('save-deck');
  if (saveBtn) {
    saveBtn.addEventListener('click', function() {
      var selected = getSelectedCards();
      if (!Object.keys(selected).length) { alert('Select cards first.'); return; }
      var character = detectCharacter(selected);
      var name = prompt('Deck name (saving as ' + character + '):');
      if (!name) return;
      var key = character + ' / ' + name;
      var decks = getDecks(); decks[key] = selected; saveDecks(decks);
      refreshSelect();
    });
  }
  var loadSel = document.getElementById('load-deck');
  if (loadSel) {
    loadSel.addEventListener('change', function() {
      var name = this.value; if (!name) return;
      var decks = getDecks();
      if (decks[name]) setQuantities(decks[name]);
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

  /* ── Qty +/- handlers (event delegation) ── */
  var form = document.querySelector('form[action="/deck/analyze"]');
  if (form) {
    form.addEventListener('click', function(e) {
      var btn = e.target.closest('.qty-btn');
      if (!btn) return;
      var card = btn.closest('.deck-card');
      if (!card) return;
      var cardId = card.getAttribute('data-card-id');
      if (!cardId) return;
      var current = cardQtys[cardId] || 0;
      if (btn.classList.contains('qty-plus')) {
        setCardQty(cardId, current + 1);
      } else if (btn.classList.contains('qty-minus')) {
        setCardQty(cardId, current - 1);
      }
      updateCounts();
    });

    // Form submit: inject hidden inputs for card_ids
    form.addEventListener('submit', function() {
      // Remove any previously injected hidden inputs
      form.querySelectorAll('input[name="card_ids"]').forEach(function(inp) { inp.remove(); });
      for (var id in cardQtys) {
        var qty = cardQtys[id];
        for (var i = 0; i < qty; i++) {
          var inp = document.createElement('input');
          inp.type = 'hidden'; inp.name = 'card_ids'; inp.value = id;
          form.appendChild(inp);
        }
      }
    });
  }

  /* ── Card info popover ── */
  var synergyCache = {};

  function escapeHtml(str) {
    var div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
  }

  function closePopover() {
    var open = document.querySelector('.deck-card--popover-open');
    if (open) open.classList.remove('deck-card--popover-open');
    var existing = document.querySelector('.card-popover');
    if (existing) existing.remove();
    var backdrop = document.querySelector('.card-popover-backdrop');
    if (backdrop) backdrop.remove();
  }

  function createPopover(btn) {
    closePopover();

    var cardId = btn.getAttribute('data-card-id');
    var name = btn.getAttribute('data-card-name');
    var desc = btn.getAttribute('data-card-desc');
    var descUp = btn.getAttribute('data-card-desc-up');
    var type = btn.getAttribute('data-card-type');
    var rarity = btn.getAttribute('data-card-rarity');
    var tier = btn.getAttribute('data-card-tier');
    var cost = btn.getAttribute('data-card-cost');
    var keywords = btn.getAttribute('data-card-keywords');

    var html = '<div class="popover-title">' + escapeHtml(name) + '</div>';

    if (desc) {
      html += '<div class="popover-desc">' + escapeHtml(desc) + '</div>';
    }
    if (descUp && descUp !== desc) {
      html += '<div class="popover-desc"><span style="color:var(--green)">Upgraded:</span> ' + escapeHtml(descUp) + '</div>';
    }

    html += '<div class="popover-meta">';
    if (cost) html += '<span class="tag tag-cost">' + escapeHtml(cost) + '</span>';
    if (type) {
      var typeLower = type.toLowerCase();
      var typeClass = 'tag-' + typeLower;
      if (['attack','skill','power','status','curse'].indexOf(typeLower) === -1) typeClass = '';
      html += '<span class="tag ' + typeClass + '">' + escapeHtml(type) + '</span>';
    }
    if (rarity) {
      var rarityLower = rarity.toLowerCase();
      var rarityClass = 'tag-' + rarityLower;
      if (['common','uncommon','rare','starter'].indexOf(rarityLower) === -1) rarityClass = '';
      html += '<span class="tag ' + rarityClass + '">' + escapeHtml(rarity) + '</span>';
    }
    if (tier) {
      html += '<span class="tag tag-keyword">' + escapeHtml(tier) + '</span>';
    }
    html += '</div>';

    if (keywords) {
      html += '<div class="popover-meta">';
      keywords.split(',').forEach(function(kw) {
        if (kw.trim()) html += '<span class="tag tag-keyword">' + escapeHtml(kw.trim()) + '</span>';
      });
      html += '</div>';
    }

    html += '<div class="popover-synergies" id="popover-synergies">Loading synergies...</div>';
    html += '<div class="popover-link"><a href="/cards/' + encodeURIComponent(cardId) + '">View full details &rarr;</a></div>';

    var popover = document.createElement('div');
    popover.className = 'card-popover';
    popover.innerHTML = html;

    var parent = btn.closest('.deck-card');
    parent.classList.add('deck-card--popover-open');
    parent.appendChild(popover);

    // Viewport flip check
    var rect = popover.getBoundingClientRect();
    if (rect.top < 0) {
      popover.classList.add('card-popover--below');
    }

    // Mobile backdrop
    var backdrop = document.createElement('div');
    backdrop.className = 'card-popover-backdrop';
    backdrop.addEventListener('click', closePopover);
    document.body.appendChild(backdrop);

    // Fetch synergies
    var synEl = popover.querySelector('#popover-synergies');
    if (synergyCache[cardId] !== undefined) {
      renderSynergies(synEl, synergyCache[cardId]);
    } else {
      fetch('/api/cards/' + encodeURIComponent(cardId))
        .then(function(r) { return r.json(); })
        .then(function(data) {
          var syns = data.synergies || [];
          synergyCache[cardId] = syns;
          renderSynergies(synEl, syns);
        })
        .catch(function() {
          synEl.textContent = 'Could not load synergies.';
        });
    }
  }

  function renderSynergies(el, syns) {
    if (!syns.length) {
      el.textContent = 'No known synergies.';
      return;
    }
    var html = '<strong>Synergies:</strong> ';
    syns.slice(0, 5).forEach(function(s, i) {
      if (i > 0) html += ', ';
      html += '<a href="/cards/' + encodeURIComponent(s.id) + '">' + escapeHtml(s.name) + '</a>';
    });
    if (syns.length > 5) html += ' +' + (syns.length - 5) + ' more';
    el.innerHTML = html;
  }

  // Event delegation for info buttons
  document.addEventListener('click', function(e) {
    var btn = e.target.closest('.card-info-btn');
    if (btn) {
      e.preventDefault();
      e.stopPropagation();
      var existing = document.querySelector('.card-popover');
      if (existing && existing.parentNode === btn.closest('.deck-card')) {
        closePopover();
      } else {
        createPopover(btn);
      }
      return;
    }
    if (!e.target.closest('.card-popover')) {
      closePopover();
    }
  });

  document.addEventListener('keydown', function(e) {
    if (e.key === 'Escape') closePopover();
  });

  /* ── Search + filter ── */
  var searchInput = document.getElementById('deck-search');
  var allCards = document.querySelectorAll('.deck-card');
  var activeTypeFilter = '';

  function applyFilters() {
    var query = (searchInput ? searchInput.value : '').toLowerCase().trim();
    var visibleCount = 0;
    allCards.forEach(function(el) {
      var name = el.getAttribute('data-card-name') || '';
      var type = el.getAttribute('data-card-type') || '';
      var matchSearch = !query || name.indexOf(query) !== -1;
      var matchType = !activeTypeFilter || type === activeTypeFilter;
      var show = matchSearch && matchType;
      el.classList.toggle('deck-card--hidden', !show);
      if (show) visibleCount++;
    });
    document.querySelectorAll('.deck-type-group').forEach(function(g) {
      g.classList.toggle('deck-type-group--hidden',
        !g.querySelector('.deck-card:not(.deck-card--hidden)'));
    });
    var noResults = document.getElementById('deck-no-results');
    if (noResults) noResults.style.display = visibleCount === 0 ? '' : 'none';
    if (query) {
      document.querySelectorAll('.deck-section').forEach(function(sec) {
        if (sec.querySelector('.deck-card:not(.deck-card--hidden)')) {
          sec.classList.remove('collapsed');
          var h = sec.querySelector('.deck-section-header');
          if (h) h.setAttribute('aria-expanded', 'true');
        }
      });
    }
  }
  if (searchInput) searchInput.addEventListener('input', applyFilters);

  /* ── Clear search ── */
  var clearBtn = document.getElementById('deck-search-clear');
  if (clearBtn && searchInput) {
    clearBtn.addEventListener('click', function() {
      searchInput.value = '';
      applyFilters();
      searchInput.focus();
    });
  }

  /* ── Type filter buttons ── */
  document.querySelectorAll('.deck-filters button').forEach(function(btn) {
    btn.addEventListener('click', function() {
      document.querySelectorAll('.deck-filters button').forEach(function(b) {
        b.classList.remove('active');
      });
      btn.classList.add('active');
      activeTypeFilter = btn.getAttribute('data-filter-type') || '';
      applyFilters();
    });
  });

  /* ── Collapsible sections ── */
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

  /* ── Expand / Collapse All ── */
  var toggleAllBtn = document.getElementById('deck-toggle-all');
  if (toggleAllBtn) {
    toggleAllBtn.addEventListener('click', function() {
      var sections = document.querySelectorAll('.deck-section');
      var allExpanded = !document.querySelector('.deck-section.collapsed');
      sections.forEach(function(sec) {
        if (allExpanded) {
          sec.classList.add('collapsed');
        } else {
          sec.classList.remove('collapsed');
        }
        var h = sec.querySelector('.deck-section-header');
        if (h) h.setAttribute('aria-expanded', String(!allExpanded));
      });
      toggleAllBtn.textContent = allExpanded ? 'Expand All' : 'Collapse All';
    });
  }

  /* ── Selected card counter ── */
  var countEl = document.getElementById('deck-count');
  function updateCounts() {
    var total = 0;
    document.querySelectorAll('.deck-section').forEach(function(sec) {
      var secTotal = 0;
      sec.querySelectorAll('.deck-card[data-card-id]').forEach(function(card) {
        var id = card.getAttribute('data-card-id');
        secTotal += (cardQtys[id] || 0);
      });
      total += secTotal;
      var el = sec.querySelector('.deck-section-checked');
      if (el) el.textContent = secTotal ? secTotal + ' selected' : '';
    });
    if (countEl) countEl.textContent = total + ' selected';
  }

  /* ── Post-submit restoration (reads from data attribute, CSP-safe) ── */
  var initEl = document.getElementById('deck-init-data');
  if (initEl) {
    try { setQuantities(JSON.parse(initEl.getAttribute('data-selected'))); } catch(e) {}
  }
  updateCounts();

  /* ── "/" keyboard shortcut to focus search ── */
  document.addEventListener('keydown', function(e) {
    if (e.key === '/' && e.target.tagName !== 'INPUT' && e.target.tagName !== 'TEXTAREA') {
      e.preventDefault();
      if (searchInput) searchInput.focus();
    }
  });
})();
