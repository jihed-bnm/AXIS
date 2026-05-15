'use strict';

// TourManager — manages the AXIS product tour lifecycle.
// Public API:
//   TourManager.start({ username, force })  — auto-trigger (skips if already done)
//   TourManager.reset()                     — clear state + replay from step 1
//   TourManager._cancel()                   — called from the inline ✕ button

const TourManager = (function () {
  const KEY_PREFIX = 'axis_tour_done';

  let _activeTour = null;
  let _activeUsername = null;

  // ── localStorage helpers ──────────────────────────────────────────────────

  function _key(username) {
    return username ? KEY_PREFIX + '_' + username : KEY_PREFIX;
  }

  function _isDone(username) {
    return !!localStorage.getItem(_key(username));
  }

  function _setDone(username) {
    localStorage.setItem(_key(username), '1');
  }

  function _clearDone(username) {
    localStorage.removeItem(_key(username));
  }

  // ── Tour construction ─────────────────────────────────────────────────────

  function _build() {
    if (!window.Shepherd) {
      console.warn('[TourManager] Shepherd.js not loaded — tour unavailable');
      return null;
    }

    const tour = new Shepherd.Tour({
      useModalOverlay: true,
      defaultStepOptions: {
        scrollTo: { behavior: 'smooth', block: 'center' },
        cancelIcon: { enabled: false },
        modalOverlayOpeningPadding: 8,
        modalOverlayOpeningRadius: { topLeft: 10, topRight: 10, bottomLeft: 10, bottomRight: 10 },
        popperOptions: {
          modifiers: [
            { name: 'offset', options: { offset: [0, 16] } },
          ],
        },
      },
    });

    // Steps are defined in shepherd-config.js (loaded before this file)
    getAxisTourSteps(tour).forEach(step => tour.addStep(step));

    return tour;
  }

  // ── Public: start tour (auto-trigger) ─────────────────────────────────────
  // opts.username  — current logged-in username (per-user tracking)
  // opts.force     — bypass the "already done" check (used by reset)

  function start(opts) {
    opts = opts || {};
    const username = opts.username || null;
    const force    = !!opts.force;

    _activeUsername = username;

    if (!force && _isDone(username)) return;

    // Cancel any in-progress tour before rebuilding
    if (_activeTour && _activeTour.isActive()) {
      _activeTour.off('cancel');
      _activeTour.off('complete');
      _activeTour.cancel();
    }

    _activeTour = _build();
    if (!_activeTour) return;

    const onEnd = () => _setDone(username);
    _activeTour.on('complete', onEnd);
    _activeTour.on('cancel',   onEnd);

    // Ensure we start from the dashboard view before opening the tour
    if (typeof navigate === 'function') navigate('dashboard');

    setTimeout(function () { _activeTour.start(); }, 380);
  }

  // ── Public: reset + replay ────────────────────────────────────────────────

  function reset() {
    // Resolve current username from app state (set during login)
    const username = (window.state && state.user) || _activeUsername || null;
    _clearDone(username);
    start({ username: username, force: true });
  }

  // ── Public: inline ✕ cancel (called from onclick in persona header) ────────

  function _cancel() {
    if (_activeTour && _activeTour.isActive()) {
      _activeTour.cancel();
    }
  }

  return { start: start, reset: reset, _cancel: _cancel };
})();
