type LandingPageProps = {
  onLaunch: () => void;
};

export function LandingPage({ onLaunch }: LandingPageProps) {
  return (
    <div className="lp">
      <nav className="lp-nav">
        <span className="lp-nav-logo">
          WALKER <span className="lp-nav-logo-accent">AI DEVTRADE TEAM</span>
        </span>
        <button className="lp-btn lp-btn-primary lp-btn-sm" onClick={onLaunch}>
          Launch Planner
        </button>
      </nav>

      <section className="lp-hero">
        <div className="lp-badge">Paper Beta</div>
        <h1 className="lp-hero-title">Multi-Agent AI Build System</h1>
        <p className="lp-hero-sub">
          Polymarket&nbsp;&middot;&nbsp;TradingView&nbsp;&middot;&nbsp;MT4/MT5&nbsp;&middot;&nbsp;Kalshi
        </p>
        <p className="lp-hero-desc">
          A disciplined, repo-truth-driven trading ecosystem where autonomous agents plan, build,
          validate, and report — so capital never moves without full audit trail.
        </p>
        <div className="lp-hero-ctas">
          <button className="lp-btn lp-btn-primary" onClick={onLaunch}>
            Open Launch Planner
          </button>
          <a
            className="lp-btn lp-btn-ghost"
            href="https://github.com/bayuewalker/walker-ai-team"
            target="_blank"
            rel="noreferrer"
          >
            Read Docs
          </a>
        </div>
      </section>

      <section className="lp-section">
        <h2 className="lp-section-title">Agent Hierarchy</h2>
        <p className="lp-section-sub">
          A strict chain of command where every decision is traceable back to repo truth.
        </p>
        <div className="lp-agents">
          <div className="lp-agent lp-agent-owner">
            <div className="lp-agent-tag">Owner</div>
            <h3 className="lp-agent-name">Mr. Walker</h3>
            <p className="lp-agent-role">Owner / Final Decision-Maker</p>
            <p className="lp-agent-desc">
              Ultimate authority. Sets direction, priorities, and makes final calls. Mr. Walker
              should only be involved in decisions that genuinely require owner authority — not
              minor issues.
            </p>
          </div>

          <div className="lp-agent-arrow">↓</div>

          <div className="lp-agent lp-agent-commander">
            <div className="lp-agent-tag">Orchestrator</div>
            <h3 className="lp-agent-name">COMMANDER</h3>
            <p className="lp-agent-role">Systems Architect / Gatekeeper / Orchestrator</p>
            <p className="lp-agent-desc">
              COMMANDER operates in direct chat with Mr. Walker — this is where decisions,
              reviews, and steering happen. Reads repo truth, identifies active lanes, merges
              adjacent work when safe, routes tasks to FORGE-X / SENTINEL / BRIEFER, reviews
              outputs, auto-merges / closes PRs by own decision. Fixes minor bugs, small errors,
              and cosmetic issues directly — no escalation. Escalates to Mr. Walker only for
              large scope, risk, capital, safety, or decisions requiring owner authority.
            </p>
          </div>

          <div className="lp-agent-arrow">↓</div>

          <div className="lp-nexus">
            <div className="lp-nexus-label">NEXUS — Multi-Agent Specialist Team</div>
            <div className="lp-nexus-grid">
              <div className="lp-agent lp-agent-forge">
                <div className="lp-agent-tag">Builder</div>
                <h3 className="lp-agent-name">FORGE-X</h3>
                <p className="lp-agent-role">Builder / Implementer / Refactor / Fix Specialist</p>
                <p className="lp-agent-desc">
                  Implement, patch, refactor, fix, update state/report, open PR.
                </p>
              </div>
              <div className="lp-agent lp-agent-sentinel">
                <div className="lp-agent-tag">Validator</div>
                <h3 className="lp-agent-name">SENTINEL</h3>
                <p className="lp-agent-role">Validator / Auditor / Safety Enforcer</p>
                <p className="lp-agent-desc">
                  Validate, audit, test, enforce safety. Only active for MAJOR tasks or when
                  COMMANDER explicitly requests audit.
                </p>
              </div>
              <div className="lp-agent lp-agent-briefer">
                <div className="lp-agent-tag">Reporter</div>
                <h3 className="lp-agent-name">BRIEFER</h3>
                <p className="lp-agent-role">Reporter / Visualizer / Communication Layer</p>
                <p className="lp-agent-desc">
                  HTML reports, prompt artifacts, visual summaries, UI/report transforms. Only
                  works from validated data. Runs after required validation path is satisfied.
                </p>
              </div>
            </div>
          </div>
        </div>
      </section>

      <section className="lp-section lp-section-alt">
        <h2 className="lp-section-title">Operating Modes</h2>
        <p className="lp-section-sub">
          Two modes govern execution speed and review depth.
        </p>
        <div className="lp-modes">
          <div className="lp-mode">
            <div className="lp-mode-icon">⬤</div>
            <h3 className="lp-mode-name">Normal Mode</h3>
            <div className="lp-mode-status">Default — always active</div>
            <p className="lp-mode-desc">
              Used for reviews, task generation, sync, and validation. Applied whenever scope
              isn't fully clear yet. Prioritises accuracy and full repo-truth alignment over
              delivery speed.
            </p>
          </div>
          <div className="lp-mode lp-mode-degen">
            <div className="lp-mode-icon">⚡</div>
            <h3 className="lp-mode-name">Degen Mode</h3>
            <div className="lp-mode-status">Explicit trigger by Mr. Walker only</div>
            <p className="lp-mode-desc">
              Batches small safe fixes, reduces back-and-forth, skips cosmetic noise, and keeps
              pushing until the lane closes. Does <strong>not</strong> override AGENTS.md,
              ignore repo truth, or bypass safety and validation gates.
            </p>
          </div>
        </div>
      </section>

      <section className="lp-section">
        <h2 className="lp-section-title">Workflow Pipeline</h2>
        <p className="lp-section-sub">
          Every lane follows the same disciplined sequence — no shortcuts on safety.
        </p>
        <div className="lp-pipeline">
          {[
            { step: '01', label: 'Direction Set', desc: 'Mr. Walker issues direction or task.' },
            {
              step: '02',
              label: 'Repo Truth Read',
              desc: 'COMMANDER checks: PROJECT_REGISTRY.md → active project → state/ files → active lane → blockers → tier → claim level.',
            },
            {
              step: '03',
              label: 'Lane Formed',
              desc: 'Adjacent open items in the same family merged into one lane. Prefer lane closure over fragmented progress.',
            },
            {
              step: '04',
              label: 'Task Routed by Tier',
              desc: 'MINOR → FORGE-X → COMMANDER auto-merge.  STANDARD → FORGE-X → COMMANDER review + merge.  MAJOR → FORGE-X → SENTINEL → COMMANDER validate + merge.',
            },
            {
              step: '05',
              label: 'FORGE-X Implements',
              desc: 'Work within scope, verify actual branch, update forge report + state files, commit and open PR.',
            },
            {
              step: '06',
              label: 'PR Reviewed',
              desc: 'COMMANDER reviews files changed, bot comments, forge report, branch traceability, state drift, and claim vs actual code.',
            },
            {
              step: '07',
              label: 'COMMANDER Merges',
              desc: 'COMMANDER auto-merges or closes by own decision. NEXUS does not merge independently. Post-merge: verify result → sync state files → determine next lane.',
            },
          ].map((item, i, arr) => (
            <div key={item.step} className="lp-pipeline-row">
              <div className="lp-pipeline-step">
                <div className="lp-pipeline-num">{item.step}</div>
                {i < arr.length - 1 && <div className="lp-pipeline-line" />}
              </div>
              <div className="lp-pipeline-content">
                <div className="lp-pipeline-label">{item.label}</div>
                <div className="lp-pipeline-desc">{item.desc}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-section lp-section-alt">
        <h2 className="lp-section-title">Supported Platforms</h2>
        <p className="lp-section-sub">
          Strategy signals flow across four platforms under unified agent governance.
        </p>
        <div className="lp-platforms">
          {[
            {
              name: 'Polymarket',
              desc: 'Prediction market execution — CLOB-based, probability-driven strategies.',
              icon: '📈',
            },
            {
              name: 'Kalshi',
              desc: 'Regulated event contract trading with strict risk controls.',
              icon: '🏛️',
            },
            {
              name: 'TradingView',
              desc: 'Pine Script signals, indicators, and strategy backtesting.',
              icon: '📊',
            },
            {
              name: 'MetaTrader 4/5',
              desc: 'MQL5 Expert Advisors for automated Forex and CFD execution.',
              icon: '⚙️',
            },
          ].map((p) => (
            <div key={p.name} className="lp-platform">
              <div className="lp-platform-icon">{p.icon}</div>
              <h3 className="lp-platform-name">{p.name}</h3>
              <p className="lp-platform-desc">{p.desc}</p>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-cta">
        <h2 className="lp-cta-title">Ready to plan your launch?</h2>
        <p className="lp-cta-sub">
          Use the AI-powered Launch Planner to transform a rough brief into a structured,
          actionable release plan in seconds.
        </p>
        <button className="lp-btn lp-btn-primary lp-btn-lg" onClick={onLaunch}>
          Open Launch Planner
        </button>
      </section>

      <footer className="lp-footer">
        <span className="lp-footer-name">Walker AI DevTrade Team</span>
        <span className="lp-footer-sep">·</span>
        <span>v1.0</span>
        <span className="lp-footer-sep">·</span>
        <span className="lp-footer-badge">Paper Beta</span>
      </footer>
    </div>
  );
}
