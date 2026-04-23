import { useEffect, useRef } from 'react';

type LandingPageProps = {
  onLaunch: () => void;
};

export function LandingPage({ onLaunch }: LandingPageProps) {
  const rootRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const root = rootRef.current;
    if (!root) return;

    const elements = root.querySelectorAll<HTMLElement>('.scroll-reveal');

    if (!('IntersectionObserver' in window)) {
      elements.forEach((el) => el.classList.add('is-visible'));
      return;
    }

    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) {
          entry.target.classList.add('is-visible');
          observer.unobserve(entry.target);
        }
      });
    }, { threshold: 0.12 });

    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, []);

  return (
    <main className="report-root" ref={rootRef}>
      <div className="cyber-grid" />
      <div className="page-wrap">
        <header className="glass-panel topbar scroll-reveal is-visible">
          <div className="brand-block">
            <div className="brand-title">WALKER <span className="text-accent">AI DEVTRADE TEAM</span></div>
          </div>
          <button className="report-btn report-btn-primary" onClick={onLaunch}>
            Launch Planner
          </button>
        </header>

        <section className="glass-panel hero-panel scroll-reveal is-visible">
          <div className="header-top">
            <span className="badge badge-accent"><span className="pulse-dot" />PAPER BETA</span>
            <span className="badge badge-warn">MULTI-AGENT</span>
          </div>
          <h1 className="hero-title">MULTI-AGENT AI BUILD SYSTEM</h1>
          <p className="hero-subtitle">Polymarket · TradingView · MT4/MT5 · Kalshi</p>
          <p className="hero-copy">
            A disciplined, repo-truth-driven trading ecosystem where autonomous agents plan,
            build, validate, and report — so capital never moves without full audit trail.
          </p>
          <div className="hero-actions">
            <button className="report-btn report-btn-primary report-btn-wide" onClick={onLaunch}>
              Open Launch Planner
            </button>
            <a
              className="report-btn report-btn-secondary report-btn-wide"
              href="https://github.com/bayuewalker/walker-ai-team"
              target="_blank"
              rel="noreferrer"
            >
              Read Docs
            </a>
          </div>
        </section>

        <section className="section-block">
          <div className="section-div scroll-reveal is-visible">01 · AGENT HIERARCHY</div>
          <div className="stack-grid">
            <article className="glass-panel card scroll-reveal delay-1">
              <div className="badge badge-accent">Owner</div>
              <h2 className="card-title">MR. WALKER</h2>
              <div className="card-kicker">Owner / Final Decision-Maker</div>
              <p className="card-copy">
                Ultimate authority. Sets direction, priorities, and makes final calls. Mr. Walker
                should only be involved in decisions that genuinely require owner authority — not
                minor issues.
              </p>
            </article>
            <article className="glass-panel card scroll-reveal delay-2">
              <div className="badge badge-success">Orchestrator</div>
              <h2 className="card-title">COMMANDER</h2>
              <div className="card-kicker">Systems Architect / Gatekeeper / Orchestrator</div>
              <p className="card-copy">
                COMMANDER operates in direct chat with Mr. Walker — this is where decisions,
                reviews, and steering happen. Reads repo truth, identifies active lanes, merges
                adjacent work when safe, routes tasks to FORGE-X / SENTINEL / BRIEFER, reviews
                outputs, auto-merges / closes PRs by own decision.
              </p>
            </article>
            <article className="glass-panel card card-wide scroll-reveal delay-3">
              <div className="badge badge-warn">NEXUS</div>
              <h2 className="card-title">FORGE-X · SENTINEL · BRIEFER</h2>
              <div className="card-kicker">Multi-Agent Specialist Team</div>
              <p className="card-copy">
                FORGE-X implements, patches, refactors, fixes, updates state/report, and opens PR.
                SENTINEL validates, audits, tests, and enforces safety. BRIEFER produces reports,
                visual summaries, and UI/report transforms from validated data.
              </p>
            </article>
          </div>
        </section>

        <section className="section-block alt-band">
          <div className="section-div scroll-reveal is-visible">02 · OPERATING MODES</div>
          <div className="mode-grid">
            <article className="glass-panel card scroll-reveal delay-1">
              <div className="badge badge-muted">Default</div>
              <h2 className="card-title">NORMAL MODE</h2>
              <p className="card-copy">Used for reviews, task generation, sync, and validation.</p>
            </article>
            <article className="glass-panel card scroll-reveal delay-2">
              <div className="badge badge-danger">Explicit trigger only</div>
              <h2 className="card-title">DEGEN MODE</h2>
              <p className="card-copy">
                Batches small safe fixes, reduces back-and-forth, skips cosmetic noise, and keeps
                pushing until the lane closes.
              </p>
            </article>
          </div>
        </section>

        <section className="section-block">
          <div className="section-div scroll-reveal is-visible">03 · WORKFLOW PIPELINE</div>
          <div className="pipeline-list">
            {[
              ['01', 'Direction Set', 'Mr. Walker issues direction or task.'],
              ['02', 'Repo Truth Read', 'COMMANDER checks registry, state files, active lane, blockers, tier, and claim level.'],
              ['03', 'Lane Formed', 'Adjacent items are merged into one lane to avoid fragmentation.'],
              ['04', 'Task Routed by Tier', 'MINOR, STANDARD, and MAJOR follow different validation paths.'],
              ['05', 'FORGE-X Implements', 'Work within scope, verify branch, update reports, commit, and open PR.'],
              ['06', 'PR Reviewed', 'COMMANDER reviews files changed, bot comments, branch traceability, and state drift.'],
              ['07', 'COMMANDER Merges', 'COMMANDER auto-merges or closes by own decision and syncs the next lane.'],
            ].map(([step, label, desc], index) => (
              <div key={step} className={`pipeline-row scroll-reveal delay-${Math.min(index + 1, 4)}`}>
                <div className="pipeline-step">
                  <div className="pipeline-num">{step}</div>
                  {index < 6 ? <div className="pipeline-line" /> : null}
                </div>
                <div className="glass-panel pipeline-card">
                  <div className="pipeline-label">{label}</div>
                  <div className="pipeline-desc">{desc}</div>
                </div>
              </div>
            ))}
          </div>
        </section>

        <section className="section-block alt-band">
          <div className="section-div scroll-reveal is-visible">04 · SUPPORTED PLATFORMS</div>
          <div className="platform-grid">
            {[
              ['Polymarket', 'Prediction market execution.', '📈'],
              ['Kalshi', 'Regulated event contract trading.', '🏛️'],
              ['TradingView', 'Pine Script signals and backtesting.', '📊'],
              ['MetaTrader 4/5', 'MQL5 Expert Advisors for FX/CFD automation.', '⚙️'],
            ].map(([name, desc, icon], index) => (
              <article key={name} className={`glass-panel card platform-card scroll-reveal delay-${index + 1}`}>
                <div className="platform-icon">{icon}</div>
                <h2 className="card-title">{name}</h2>
                <p className="card-copy">{desc}</p>
              </article>
            ))}
          </div>
        </section>

        <section className="glass-panel cta-panel scroll-reveal">
          <h2 className="cta-title">READY TO PLAN YOUR LAUNCH?</h2>
          <p className="cta-copy">Use the AI-powered Launch Planner to turn a rough brief into a structured release plan.</p>
          <button className="report-btn report-btn-primary report-btn-wide" onClick={onLaunch}>
            Open Launch Planner
          </button>
        </section>

        <footer className="glass-panel footer-panel scroll-reveal is-visible">
          <span className="footer-brand">Walker AI DevTrade Team</span>
          <span className="footer-sep">·</span>
          <span>v1.0</span>
          <span className="footer-sep">·</span>
          <span className="footer-badge">Paper Beta</span>
        </footer>
      </div>
    </main>
  );
}
