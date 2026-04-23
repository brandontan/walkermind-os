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

    const observer = new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-visible');
            observer.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.12 }
    );

    elements.forEach((el) => observer.observe(el));

    return () => observer.disconnect();
  }, []);

  return (
    <div className="lp" ref={rootRef}>
      <div className="lp-cyber-grid" />
      <nav className="lp-nav glass-panel scroll-reveal is-visible">
        <span className="lp-nav-logo">
          WALKER <span className="lp-nav-logo-accent">AI DEVTRADE TEAM</span>
        </span>
        <button className="lp-btn lp-btn-primary lp-btn-sm" onClick={onLaunch}>
          Launch Planner
        </button>
      </nav>

      <section className="lp-hero glass-panel scroll-reveal is-visible">
        <div className="header-top">
          <span className="badge badge-accent">
            <span className="pulse-dot" />
            PAPER BETA
          </span>
          <span className="badge badge-warn">MULTI-AGENT</span>
        </div>
        <div className="lp-hero-inner">
          <h1 className="header-title lp-hero-title">Multi-Agent AI Build System</h1>
          <p className="header-subtitle lp-hero-subtitle">
            Polymarket · TradingView · MT4/MT5 · Kalshi
          </p>
          <p className="lp-hero-desc">
            A disciplined, repo-truth-driven trading ecosystem where autonomous agents plan,
            build, validate, and report — so capital never moves without full audit trail.
          </p>
        </div>
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
        <div className="section-div scroll-reveal is-visible">01 · Agent Hierarchy</div>
        <div className="lp-grid">
          <article className="glass-panel scroll-reveal delay-1 lp-card">
            <div className="badge badge-accent">Owner</div>
            <h3 className="lp-card-title">Mr. Walker</h3>
            <p className="lp-card-kicker">Owner / Final Decision-Maker</p>
            <p className="lp-card-copy">
              Ultimate authority. Sets direction, priorities, and makes final calls. Mr. Walker
              should only be involved in decisions that genuinely require owner authority — not
              minor issues.
            </p>
          </article>
          <article className="glass-panel scroll-reveal delay-2 lp-card">
            <div className="badge badge-success">Orchestrator</div>
            <h3 className="lp-card-title">COMMANDER</h3>
            <p className="lp-card-kicker">Systems Architect / Gatekeeper / Orchestrator</p>
            <p className="lp-card-copy">
              COMMANDER operates in direct chat with Mr. Walker — this is where decisions,
              reviews, and steering happen. Reads repo truth, identifies active lanes, merges
              adjacent work when safe, routes tasks to FORGE-X / SENTINEL / BRIEFER, reviews
              outputs, auto-merges / closes PRs by own decision.
            </p>
          </article>
          <article className="glass-panel scroll-reveal delay-3 lp-card lp-card-wide">
            <div className="badge badge-warn">NEXUS</div>
            <h3 className="lp-card-title">FORGE-X · SENTINEL · BRIEFER</h3>
            <p className="lp-card-kicker">Multi-Agent Specialist Team</p>
            <p className="lp-card-copy">
              FORGE-X implements, patches, refactors, fixes, updates state/report, and opens PR.
              SENTINEL validates, audits, tests, and enforces safety. BRIEFER produces reports,
              visual summaries, and UI/report transforms from validated data.
            </p>
          </article>
        </div>
      </section>

      <section className="lp-section lp-section-alt">
        <div className="section-div scroll-reveal is-visible">02 · Operating Modes</div>
        <div className="lp-grid lp-grid-2">
          <article className="glass-panel scroll-reveal delay-1 lp-card">
            <div className="badge badge-muted">Default</div>
            <h3 className="lp-card-title">Normal Mode</h3>
            <p className="lp-card-copy">
              Used for reviews, task generation, sync, and validation. Applied whenever scope
              isn't fully clear yet.
            </p>
          </article>
          <article className="glass-panel scroll-reveal delay-2 lp-card">
            <div className="badge badge-danger">Explicit trigger only</div>
            <h3 className="lp-card-title">Degen Mode</h3>
            <p className="lp-card-copy">
              Batches small safe fixes, reduces back-and-forth, skips cosmetic noise, and keeps
              pushing until the lane closes. Does not override AGENTS.md or bypass safety gates.
            </p>
          </article>
        </div>
      </section>

      <section className="lp-section">
        <div className="section-div scroll-reveal is-visible">03 · Workflow Pipeline</div>
        <div className="lp-pipeline">
          {[
            ['01', 'Direction Set', 'Mr. Walker issues direction or task.'],
            ['02', 'Repo Truth Read', 'COMMANDER checks registry, state files, active lane, blockers, tier, and claim level.'],
            ['03', 'Lane Formed', 'Adjacent items are merged into one lane to avoid fragmentation.'],
            ['04', 'Task Routed by Tier', 'MINOR, STANDARD, and MAJOR follow different validation paths.'],
            ['05', 'FORGE-X Implements', 'Work within scope, verify branch, update reports, commit, and open PR.'],
            ['06', 'PR Reviewed', 'COMMANDER reviews files changed, bot comments, branch traceability, and state drift.'],
            ['07', 'COMMANDER Merges', 'COMMANDER auto-merges or closes by own decision and syncs the next lane.'],
          ].map(([step, label, desc], index) => (
            <div key={step} className={`lp-pipeline-row scroll-reveal delay-${Math.min(index + 1, 4)}`}>
              <div className="lp-pipeline-step">
                <div className="lp-pipeline-num">{step}</div>
                {index < 6 ? <div className="lp-pipeline-line" /> : null}
              </div>
              <div className="glass-panel lp-pipeline-content">
                <div className="lp-pipeline-label">{label}</div>
                <div className="lp-pipeline-desc">{desc}</div>
              </div>
            </div>
          ))}
        </div>
      </section>

      <section className="lp-section lp-section-alt">
        <div className="section-div scroll-reveal is-visible">04 · Supported Platforms</div>
        <div className="lp-grid lp-grid-4">
          {[
            ['Polymarket', 'Prediction market execution.', '📈'],
            ['Kalshi', 'Regulated event contract trading.', '🏛️'],
            ['TradingView', 'Pine Script signals and backtesting.', '📊'],
            ['MetaTrader 4/5', 'MQL5 Expert Advisors for FX/CFD automation.', '⚙️'],
          ].map(([name, desc, icon], index) => (
            <article key={name} className={`glass-panel scroll-reveal delay-${index + 1} lp-platform-card`}>
              <div className="lp-platform-icon">{icon}</div>
              <h3 className="lp-card-title">{name}</h3>
              <p className="lp-card-copy">{desc}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="lp-cta glass-panel scroll-reveal">
        <h2 className="lp-cta-title">Ready to plan your launch?</h2>
        <p className="lp-cta-sub">
          Use the AI-powered Launch Planner to turn a rough brief into a structured, actionable
          release plan in seconds.
        </p>
        <button className="lp-btn lp-btn-primary lp-btn-lg" onClick={onLaunch}>
          Open Launch Planner
        </button>
      </section>

      <footer className="lp-footer glass-panel scroll-reveal is-visible">
        <span className="lp-footer-name">Walker AI DevTrade Team</span>
        <span className="lp-footer-sep">·</span>
        <span>v1.0</span>
        <span className="lp-footer-sep">·</span>
        <span className="lp-footer-badge">Paper Beta</span>
      </footer>
    </div>
  );
}
