'use strict';

// Builds the AXIS persona header that appears in every step tooltip.
function _axisShpHead() {
  const logoSvg = `<svg width="18" height="18" viewBox="0 0 78 78" fill="none">
    <path d="M14 66L39 12L64 66" fill="none" stroke="#63AEFF" stroke-width="6"
          stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M24 46 A18 18 0 0 0 54 46" fill="none"
          stroke="rgba(255,255,255,0.65)" stroke-width="4" stroke-linecap="round"/>
    <circle cx="39" cy="55" r="3.5" fill="rgba(255,255,255,0.65)"/>
  </svg>`;

  return `<div class="axis-shp-persona">
    <div class="axis-shp-avatar">${logoSvg}</div>
    <div class="axis-shp-meta">
      <span class="axis-shp-role">AXIS Guide</span>
      <span class="axis-shp-name">Your BI Assistant</span>
    </div>
    <button class="axis-shp-close" onclick="TourManager._cancel()" aria-label="Close tour">&#x2715;</button>
  </div>`;
}

// Builds the message body + progress indicator for a step.
function _axisShpBody(msg, step, total) {
  const dots = Array.from({ length: total }, (_, i) =>
    `<span class="axis-shp-dot${i === step ? ' active' : ''}"></span>`
  ).join('');

  return `<p class="axis-shp-msg">${msg}</p>
<div class="axis-shp-progress">${dots}</div>`;
}

// Composes full step text: persona header + message + progress.
function _axisShpText(msg, step, total) {
  return _axisShpHead() + _axisShpBody(msg, step, total);
}

// Returns the array of step configs for the AXIS product tour.
// `tour` is the Shepherd.Tour instance — passed so button actions can call
// tour.next() / tour.back() / tour.cancel() / tour.complete() directly.
function getAxisTourSteps(tour) {
  const TOTAL = 5;

  return [
    // ── 1 / 5 : Sidebar navigation ──────────────────────────────────────
    {
      id: 'axis-nav',
      attachTo: { element: '#sidebar', on: 'right' },
      text: _axisShpText(
        "Welcome to <strong style=\"color:#1E2D3D\">AXIS</strong>. " +
        "This sidebar is your command center — switch between the Dashboard, " +
        "AI Agent, Charts, and settings with a single click.",
        0, TOTAL
      ),
      buttons: [
        { text: 'Skip Tour',   action: () => tour.cancel(),  classes: 'shepherd-button-secondary' },
        { text: "Let's go →",  action: () => tour.next(),    classes: 'shepherd-button-primary'   },
      ],
    },

    // ── 2 / 5 : Sales dashboard ──────────────────────────────────────────
    {
      id: 'axis-sales',
      attachTo: { element: '.nav-item[data-view="dashboard"]', on: 'right' },
      text: _axisShpText(
        "Let me show you where your deals live. The Dashboard surfaces " +
        "revenue trends, win rates, pipeline stages, and top clients — " +
        "everything you need to stay ahead of your numbers.",
        1, TOTAL
      ),
      when: {
        show() {
          if (typeof navigate === 'function') navigate('dashboard');
          if (typeof switchDashTab === 'function') switchDashTab('crm', false);
        },
      },
      buttons: [
        { text: '← Back',  action: () => tour.back(),  classes: 'shepherd-button-secondary' },
        { text: 'Next →',  action: () => tour.next(),  classes: 'shepherd-button-primary'   },
      ],
    },

    // ── 3 / 5 : Finance & Invoicing tab ─────────────────────────────────
    {
      id: 'axis-invoicing',
      attachTo: { element: '#tab-finance-btn', on: 'bottom' },
      text: _axisShpText(
        "Switch to <strong style=\"color:#1E2D3D\">Finance &amp; Invoicing</strong> to " +
        "follow every TND — what's collected, what's pending, and what's overdue. " +
        "No surprises at month-end.",
        2, TOTAL
      ),
      when: {
        show() {
          if (typeof navigate === 'function') navigate('dashboard');
        },
      },
      buttons: [
        { text: '← Back',  action: () => tour.back(),  classes: 'shepherd-button-secondary' },
        { text: 'Next →',  action: () => tour.next(),  classes: 'shepherd-button-primary'   },
      ],
    },

    // ── 4 / 5 : My Charts ───────────────────────────────────────────────
    {
      id: 'axis-charts',
      attachTo: { element: '.nav-item[data-view="charts"]', on: 'right' },
      text: _axisShpText(
        "Ask the AXIS Agent to build any chart and it lands here in " +
        "<strong style=\"color:#1E2D3D\">My Charts</strong> — interactive, " +
        "filterable, and ready to share with your team.",
        3, TOTAL
      ),
      buttons: [
        { text: '← Back',  action: () => tour.back(),  classes: 'shepherd-button-secondary' },
        { text: 'Next →',  action: () => tour.next(),  classes: 'shepherd-button-primary'   },
      ],
    },

    // ── 5 / 5 : Agent chat ───────────────────────────────────────────────
    {
      id: 'axis-agent',
      attachTo: { element: '.nav-item[data-view="agent"]', on: 'right' },
      text: _axisShpText(
        "And this is where the magic happens. Ask about deals, invoice status, " +
        "client churn risk, or request any analysis — in plain language. " +
        "I'm always here.",
        4, TOTAL
      ),
      buttons: [
        { text: '← Back',       action: () => tour.back(),     classes: 'shepherd-button-secondary' },
        { text: "Let's dive in!", action: () => tour.complete(), classes: 'shepherd-button-primary'   },
      ],
    },
  ];
}
