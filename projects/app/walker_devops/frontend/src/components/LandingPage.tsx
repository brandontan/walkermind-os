import { useEffect, useRef, useState } from 'react';

type LandingPageProps = { onLaunch: () => void };

export function LandingPage({ onLaunch }: LandingPageProps) {
  const [booting, setBooting] = useState(true);
  const [activeTab, setActiveTab] = useState('overview');
  const preRef = useRef<HTMLPreElement>(null);

  useEffect(() => {
    const lines = [
      'INITIALIZING WALKER_AI OS...',
      'LOADING AGENT NEURAL WEIGHTS........... [OK]',
      'CONNECTING TO POLYMARKET CLOB.......... [OK]',
      'CONNECTING TO KALSHI API............... [OK]',
      'VALIDATING RISK PARAMETERS............. [OK]',
      'LOADING COMMANDER ORCHESTRATOR......... [OK]',
      '',
      'SYSTEM READY.',
      'ACCESSING WALKER AI DEVTRADE TEAM DASHBOARD.',
    ];
    const text = lines.join('\n');
    let idx = 0;
    let lastTime = 0;
    const INTERVAL = 22;
    const pre = preRef.current;
    if (!pre) return;

    let raf: number;
    function step(ts: number) {
      if (idx > text.length) {
        setTimeout(() => setBooting(false), 400);
        return;
      }
      if (ts - lastTime >= INTERVAL) {
        if (pre) pre.textContent = text.substring(0, idx);
        idx++;
        lastTime = ts;
      }
      raf = requestAnimationFrame(step);
    }

    const t = setTimeout(() => { raf = requestAnimationFrame(step); }, 80);
    const failsafe = setTimeout(() => setBooting(false), 7000);

    return () => { clearTimeout(t); clearTimeout(failsafe); cancelAnimationFrame(raf); };
  }, []);

  return (
    <div className="page-root">
      <div className="cyber-grid" />

      {booting && (
        <div id="boot-screen">
          <div className="boot-inner">
            <pre id="boot-text" ref={preRef} />
            <span className="boot-cursor" />
          </div>
        </div>
      )}

      {!booting && (
        <div id="dashboard">
          <div className="container">

            {/* ── HEADER ── */}
            <header className="glass-panel">
              <div className="header-top">
                <span className="badge badge-accent"><span className="pulse-dot" />PAPER BETA</span>
                <span className="badge badge-warn">MULTI-AGENT</span>
              </div>
              <h1 className="header-title">Walker AI <span className="text-accent">Trading</span></h1>
              <p className="header-subtitle">
                Walker DevTrade Team // COMMANDER Orchestrated // Multi-Platform Execution
              </p>
              <div className="meta-data">
                <p><span className="text-muted">OWNER:</span> <span className="text-accent">Mr. Walker</span></p>
                <p><span className="text-muted">DATE:</span> <span>2025 — Active Development</span></p>
                <p><span className="text-muted">STATUS:</span> <span className="text-success">Paper Beta · System Ready</span></p>
              </div>
            </header>

            {/* ── TABS NAV ── */}
            <nav className="tabs-nav" role="tablist">
              {[
                ['overview', '01_OVERVIEW'],
                ['agents', '02_AGENTS'],
                ['workflow', '03_WORKFLOW'],
                ['platforms', '04_PLATFORMS'],
              ].map(([id, label]) => (
                <button
                  key={id}
                  className={`tab-btn${activeTab === id ? ' active' : ''}`}
                  onClick={() => setActiveTab(id)}
                  role="tab"
                  aria-selected={activeTab === id}
                >
                  {label}
                </button>
              ))}
            </nav>

            {/* ── TAB 1: OVERVIEW ── */}
            {activeTab === 'overview' && (
              <div className="tab-content active" role="tabpanel">
                <div className="glass-panel">
                  <h2 style={{ fontSize: 15, marginBottom: 10 }}>
                    <span className="text-accent">///</span> SYSTEM OVERVIEW
                  </h2>
                  <p style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.6, marginBottom: 10 }}>
                    Walker AI DevTrade Team is a disciplined, repo-truth-driven multi-agent trading ecosystem.
                    Autonomous agents plan, build, validate, and report — so capital never moves without a full audit trail.
                  </p>
                  <p style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.6 }}>
                    Every decision flows through COMMANDER who orchestrates FORGE-X, SENTINEL, and BRIEFER under
                    strict tier-based routing. Normal Mode handles reviews and sync. Degen Mode is explicit-trigger only.
                  </p>
                  <div className="notice-box notice-warn">
                    ⚠ Paper Beta: All execution is simulated. No real capital is at risk during this phase.
                  </div>
                </div>

                <div className="grid-2">
                  <div className="metric-card accent">
                    <span className="m-label">Agents Active</span>
                    <span className="m-val">4</span>
                    <span className="m-note">Owner, COMMANDER, FORGE-X, SENTINEL</span>
                  </div>
                  <div className="metric-card success">
                    <span className="m-label">Execution Mode</span>
                    <span className="m-val" style={{ fontSize: 18 }}>PAPER</span>
                    <span className="m-note">Simulated — no live capital</span>
                  </div>
                  <div className="metric-card warn">
                    <span className="m-label">Supported Markets</span>
                    <span className="m-val">4</span>
                    <span className="m-note">Polymarket · Kalshi · TradingView · MT4/5</span>
                  </div>
                  <div className="metric-card success">
                    <span className="m-label">Audit Trail</span>
                    <span className="m-val" style={{ fontSize: 18 }}>100%</span>
                    <span className="m-note">Every action logged to repo</span>
                  </div>
                </div>

                <div className="glass-panel">
                  <h2 style={{ fontSize: 14, marginBottom: 12, letterSpacing: '0.08em' }}>RISK CONTROLS (ALWAYS ON)</h2>
                  <div className="grid-2">
                    <div className="metric-card success">
                      <span className="m-label">Kelly Fraction (α)</span>
                      <span className="m-val" style={{ fontSize: 16 }}>0.25</span>
                      <span className="m-note">Fractional only — no full Kelly</span>
                    </div>
                    <div className="metric-card success">
                      <span className="m-label">Max Position Size</span>
                      <span className="m-val" style={{ fontSize: 16 }}>10%</span>
                      <span className="m-note">Hard cap per trade</span>
                    </div>
                    <div className="metric-card warn">
                      <span className="m-label">Daily Loss Limit</span>
                      <span className="m-val" style={{ fontSize: 16 }}>$2K</span>
                      <span className="m-note">Hard stop — auto-halt</span>
                    </div>
                    <div className="metric-card warn">
                      <span className="m-label">Drawdown Circuit-Breaker</span>
                      <span className="m-val" style={{ fontSize: 16 }}>8%</span>
                      <span className="m-note">Triggers full system halt</span>
                    </div>
                  </div>
                </div>

                <div style={{ marginTop: 16, textAlign: 'center' }}>
                  <button className="cta-btn" onClick={onLaunch}>Open Launch Planner</button>
                </div>
              </div>
            )}

            {/* ── TAB 2: AGENTS ── */}
            {activeTab === 'agents' && (
              <div className="tab-content active" role="tabpanel">
                <div className="glass-panel">
                  <h2 style={{ fontSize: 15, marginBottom: 10 }}>
                    <span className="text-accent">///</span> AGENT HIERARCHY
                  </h2>

                  <div className="section-div" style={{ marginTop: 14 }}>TIER 0 — OWNER</div>
                  <div className="metric-card accent" style={{ marginBottom: 10 }}>
                    <span className="m-label">MR. WALKER</span>
                    <span className="m-val" style={{ fontSize: 18, color: 'var(--accent)' }}>Owner / Final Decision-Maker</span>
                    <span className="m-note">
                      Ultimate authority. Sets direction, priorities, and makes final calls. Mr. Walker
                      should only be involved in decisions that genuinely require owner authority — not minor issues.
                    </span>
                  </div>

                  <div className="section-div">TIER 1 — ORCHESTRATOR</div>
                  <div className="metric-card success" style={{ marginBottom: 10 }}>
                    <span className="m-label">COMMANDER</span>
                    <span className="m-val" style={{ fontSize: 18, color: 'var(--success)' }}>Systems Architect / Gatekeeper / Orchestrator</span>
                    <span className="m-note">
                      COMMANDER operates in direct chat with Mr. Walker — this is where decisions, reviews, and steering happen.
                      Reads repo truth, identifies active lanes, merges adjacent work when safe, routes tasks to FORGE-X / SENTINEL / BRIEFER,
                      reviews outputs, auto-merges / closes PRs by own decision.
                    </span>
                  </div>

                  <div className="section-div">TIER 2 — SPECIALIST AGENTS</div>
                  <div className="grid-2">
                    <div className="metric-card warn">
                      <span className="m-label">FORGE-X</span>
                      <span className="m-val" style={{ fontSize: 16, color: 'var(--warn)' }}>Builder</span>
                      <span className="m-note">
                        Implements, patches, refactors, fixes, updates state/report, and opens PR.
                      </span>
                    </div>
                    <div className="metric-card danger">
                      <span className="m-label">SENTINEL</span>
                      <span className="m-val" style={{ fontSize: 16, color: 'var(--danger)' }}>Validator</span>
                      <span className="m-note">
                        Validates, audits, tests, and enforces safety. Blocks unsafe merges.
                      </span>
                    </div>
                  </div>
                  <div className="metric-card" style={{ marginTop: 10, borderColor: 'var(--muted)' }}>
                    <span className="m-label">BRIEFER</span>
                    <span className="m-val" style={{ fontSize: 16, color: 'var(--text-main)' }}>Reporter</span>
                    <span className="m-note">
                      Produces reports, visual summaries, and UI/report transforms from validated data.
                    </span>
                  </div>
                </div>

                <div className="glass-panel">
                  <h2 style={{ fontSize: 14, marginBottom: 12, letterSpacing: '0.08em' }}>OPERATING MODES</h2>
                  <div className="grid-2">
                    <div className="metric-card" style={{ borderColor: 'var(--muted)' }}>
                      <span className="m-label">NORMAL MODE</span>
                      <span className="m-val" style={{ fontSize: 14, color: 'var(--text-main)' }}>Default</span>
                      <span className="m-note">
                        Used for reviews, task generation, sync, and validation. Applied whenever scope isn't fully clear yet.
                      </span>
                    </div>
                    <div className="metric-card danger">
                      <span className="m-label">DEGEN MODE</span>
                      <span className="m-val" style={{ fontSize: 14, color: 'var(--danger)' }}>Explicit Trigger Only</span>
                      <span className="m-note">
                        Batches small safe fixes, reduces back-and-forth. Does not override AGENTS.md or bypass safety gates.
                      </span>
                    </div>
                  </div>
                </div>
              </div>
            )}

            {/* ── TAB 3: WORKFLOW ── */}
            {activeTab === 'workflow' && (
              <div className="tab-content active" role="tabpanel">
                <div className="glass-panel">
                  <h2 style={{ fontSize: 15, marginBottom: 14 }}>
                    <span className="text-accent">///</span> 7-STEP EXECUTION PIPELINE
                  </h2>
                  <div className="scroll-x">
                    <div className="pipeline">
                      <div className="pipe-node pipe-active">01_DIRECTION</div>
                      <span className="text-muted">→</span>
                      <div className="pipe-node pipe-active">02_REPO_TRUTH</div>
                      <span className="text-muted">→</span>
                      <div className="pipe-node pipe-active">03_LANE_FORM</div>
                      <span className="text-muted">→</span>
                      <div className="pipe-node pipe-warn">04_TIER_ROUTE</div>
                      <span className="text-muted">→</span>
                      <div className="pipe-node pipe-active">05_FORGE-X</div>
                      <span className="text-muted">→</span>
                      <div className="pipe-node pipe-success">06_PR_REVIEW</div>
                      <span className="text-muted">→</span>
                      <div className="pipe-node pipe-success">07_MERGE</div>
                    </div>
                  </div>
                </div>

                <div className="glass-panel">
                  <h3 style={{ fontSize: 14, marginBottom: 14, letterSpacing: '0.06em' }}>PIPELINE STEPS</h3>
                  <ul className="data-list">
                    <li>
                      <span><strong className="text-accent">01</strong> · Direction Set</span>
                      <span className="text-dim-small">Mr. Walker issues direction or task.</span>
                    </li>
                    <li>
                      <span><strong className="text-accent">02</strong> · Repo Truth Read</span>
                      <span className="text-dim-small">COMMANDER checks registry, state files, active lane, blockers, tier, and claim level.</span>
                    </li>
                    <li>
                      <span><strong className="text-accent">03</strong> · Lane Formed</span>
                      <span className="text-dim-small">Adjacent items merged into one lane to avoid fragmentation.</span>
                    </li>
                    <li>
                      <span><strong className="text-accent">04</strong> · Task Routed by Tier</span>
                      <span className="text-dim-small">MINOR, STANDARD, and MAJOR follow different validation paths.</span>
                    </li>
                    <li>
                      <span><strong className="text-accent">05</strong> · FORGE-X Implements</span>
                      <span className="text-dim-small">Work within scope, verify branch, update reports, commit, and open PR.</span>
                    </li>
                    <li>
                      <span><strong className="text-accent">06</strong> · PR Reviewed</span>
                      <span className="text-dim-small">COMMANDER reviews files changed, bot comments, branch traceability, and state drift.</span>
                    </li>
                    <li style={{ borderBottom: 'none' }}>
                      <span><strong className="text-accent">07</strong> · COMMANDER Merges</span>
                      <span className="text-dim-small">Auto-merges or closes by own decision and syncs the next lane.</span>
                    </li>
                  </ul>
                </div>

                <div className="glass-panel">
                  <h3 style={{ fontSize: 14, marginBottom: 14, letterSpacing: '0.06em' }}>SENTINEL VALIDATION GATES</h3>
                  <div className="scroll-x">
                    <table>
                      <thead>
                        <tr>
                          <th>TIER</th>
                          <th>VALIDATION</th>
                          <th>SENTINEL REQUIRED</th>
                          <th style={{ textAlign: 'right' }}>AUTO-MERGE</th>
                        </tr>
                      </thead>
                      <tbody>
                        <tr>
                          <td className="font-mono td-muted">MINOR</td>
                          <td>Style, docs, copy</td>
                          <td className="td-muted">Optional</td>
                          <td className="td-success td-right font-mono">YES</td>
                        </tr>
                        <tr style={{ background: 'var(--surface2)' }}>
                          <td className="font-mono td-muted">STANDARD</td>
                          <td><strong>Logic, API, feature</strong></td>
                          <td className="td-muted">Required</td>
                          <td className="td-success td-right font-mono" style={{ fontWeight: 'bold' }}>YES</td>
                        </tr>
                        <tr>
                          <td className="font-mono td-muted">MAJOR</td>
                          <td>Architecture, capital flow</td>
                          <td className="td-muted">Required + Owner</td>
                          <td className="td-warn td-right font-mono">OWNER APPROVAL</td>
                        </tr>
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            )}

            {/* ── TAB 4: PLATFORMS ── */}
            {activeTab === 'platforms' && (
              <div className="tab-content active" role="tabpanel">
                <div className="glass-panel">
                  <h2 style={{ fontSize: 15, marginBottom: 10 }}>
                    <span className="text-accent">///</span> SUPPORTED PLATFORMS
                  </h2>
                  <p style={{ fontSize: 12, color: 'var(--text-dim)', lineHeight: 1.6 }}>
                    The Walker AI system is built to execute across four distinct trading platforms, each with
                    dedicated agent modules, risk controls, and execution pipelines.
                  </p>
                </div>

                <div className="grid-2">
                  <div className="metric-card accent">
                    <span className="m-label">Polymarket</span>
                    <span className="m-val" style={{ fontSize: 16 }}>CLOB</span>
                    <span className="m-note">On-chain prediction market execution via REST + WebSocket API.</span>
                  </div>
                  <div className="metric-card success">
                    <span className="m-label">Kalshi</span>
                    <span className="m-val" style={{ fontSize: 16 }}>REGULATED</span>
                    <span className="m-note">CFTC-regulated event contract trading. Full order lifecycle support.</span>
                  </div>
                  <div className="metric-card warn">
                    <span className="m-label">TradingView</span>
                    <span className="m-val" style={{ fontSize: 16 }}>PINE</span>
                    <span className="m-note">Pine Script signal generation, backtesting, and webhook routing.</span>
                  </div>
                  <div className="metric-card" style={{ borderColor: 'var(--muted)' }}>
                    <span className="m-label">MetaTrader 4/5</span>
                    <span className="m-val" style={{ fontSize: 16 }}>MQL5</span>
                    <span className="m-note">Expert Advisor automation for FX and CFD instruments.</span>
                  </div>
                </div>

                <div className="glass-panel" style={{ borderLeft: '2px solid var(--success)' }}>
                  <h3 style={{ fontSize: 14, marginBottom: 12, letterSpacing: '0.06em' }} className="text-success">
                    INTEGRATION ARCHITECTURE
                  </h3>
                  <ul className="data-list">
                    <li><span>Signal Source</span><strong className="text-accent">TradingView Pine Alerts</strong></li>
                    <li><span>Signal Router</span><strong className="text-success">COMMANDER → FORGE-X</strong></li>
                    <li><span>Risk Gate</span><strong className="text-warn">SENTINEL — Pre-execution</strong></li>
                    <li><span>Execution</span><strong className="text-accent">Polymarket / Kalshi / MT5</strong></li>
                    <li style={{ borderBottom: 'none' }}><span>Kill Switch</span><strong className="text-success">Telegram-accessible</strong></li>
                  </ul>
                </div>

                <div style={{ marginTop: 16, textAlign: 'center' }}>
                  <button className="cta-btn" onClick={onLaunch}>Open Launch Planner</button>
                </div>
              </div>
            )}

            {/* ── FOOTER ── */}
            <div className="report-footer">
              WALKER AI TRADING TEAM · Walker DevTrade Team · COMMANDER<br />
              2025 — Active Development · Owner: Mr. Walker<br /><br />
              <span style={{ opacity: 0.6 }}>
                Paper Beta. All execution simulated. No real capital at risk. System under active development.
              </span>
            </div>

          </div>
        </div>
      )}
    </div>
  );
}
