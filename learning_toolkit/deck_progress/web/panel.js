function renderDeckProgress(payload) {
  const id = 'deck-progress-panel';
  let host = document.getElementById(id);
  if (!payload.html) {
    host?.remove();
    return;
  }
  const heatmaps = document.querySelectorAll('.rh-container');
  const heatmap = heatmaps[heatmaps.length - 1];
  const today = document.getElementById('studiedToday');
  if (!host) {
    host = document.createElement('section');
    host.id = id;
    host.setAttribute('aria-label', 'Deck progress');
    // The heatmap has its own streak summary: append after the whole module.
    // Anki's bottom navigation lives in a separate webview, so it is untouched.
    if (heatmap) heatmap.after(host);
    else if (today?.parentElement) today.parentElement.append(host);
    else return; // A third-party home replacement may not offer a safe anchor.
    host.addEventListener('click', event => {
      const button = event.target.closest('button');
      if (!button || !host.contains(button) || typeof pycmd !== 'function') return;
      if (button.dataset.dpEdit) pycmd('deck_progress:edit:' + button.dataset.dpEdit);
      else if (button.dataset.dpAction) pycmd('deck_progress:' + button.dataset.dpAction);
    });
  }
  let style = document.getElementById('deck-progress-style');
  if (!style) {
    style = document.createElement('style');
    style.id = 'deck-progress-style';
    document.head.append(style);
  }
  style.textContent = payload.css;
  // Keep a keyboard user's focus when a background count refreshes the tiles.
  const focused = host.contains(document.activeElement) ? document.activeElement : null;
  const focusKey = focused?.dataset.dpEdit;
  const focusAction = focused?.dataset.dpAction;
  host.innerHTML = payload.html;
  if (focusKey || focusAction) {
    const next = Array.from(host.querySelectorAll('button')).find(button =>
      focusKey ? button.dataset.dpEdit === focusKey : button.dataset.dpAction === focusAction);
    next?.focus({ preventScroll: true });
  }
}
