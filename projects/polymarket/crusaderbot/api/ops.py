"""Operator HTML dashboard at ``GET /ops`` plus kill / resume buttons.

A lightweight, single-page operator console served as inline HTML so it
works from any phone or desktop browser without a JS bundle. The page
auto-refreshes every 30 seconds via ``<meta http-equiv="refresh">``.

Surfaces
--------
GET /ops          single HTML page with system snapshot
POST /ops/kill    flips the kill switch to ACTIVE (pauses new trades)
POST /ops/resume  releases the kill switch (resumes new trades)

The kill / resume actions delegate to ``domain.ops.kill_switch.set_active``
which is the single source of truth shared with the Telegram operator
surface (``/kill`` / ``/resume`` / ``/killswitch``) and the bearer-protected
``/admin/kill`` REST endpoint. Every flip writes one row to
``kill_switch_history`` AND one row to ``audit.log`` (action
``kill_switch_pause`` / ``_resume``) so the full operator timeline is
queryable.

Auth (H1 — cookie session, token out of the URL)
-------------------------------------------------
The dashboard is gated by ``OPS_SECRET``. The secret no longer lives in
the URL: an operator authenticates once via ``POST /ops/login`` (secret in
the request body, over HTTPS), which sets an HttpOnly + Secure +
SameSite=Lax cookie (``ops_session``) holding an HMAC of the secret — not
the secret itself. Subsequent dashboard renders and kill / resume POSTs
authenticate from that cookie, so the secret never appears in the address
bar, browser history, referrer headers, or Fly's access logs.

Resolution for the POST mutators (``/ops/kill`` / ``/ops/resume``), any of:
  * ``X-Ops-Token`` header == ``OPS_SECRET``      (scripts / CI)
  * ``ops_session`` cookie == HMAC(``OPS_SECRET``) (browser, post-login)
  * ``?token=<OPS_SECRET>`` query param           (legacy bookmark — still
    accepted for backward-compatibility so an existing bookmark never
    locks the operator out of the kill switch)

``GET /ops`` renders the login form when unauthenticated (no system data is
exposed to an anonymous visitor) and the full dashboard once the cookie is
present. A legacy ``?token=`` GET is auto-migrated: the cookie is set and
the request is redirected to a clean ``/ops`` so the secret leaves the URL.
``OPS_SECRET`` unset → mutators 503 and the dashboard stays open (it cannot
be gated without a secret). Token rotation = change ``OPS_SECRET`` in the
environment, which invalidates every outstanding cookie (HMAC mismatch).
All comparisons use ``secrets.compare_digest`` to avoid timing oracles.
The bearer-protected ``/admin/kill`` REST endpoint remains the path for CI.
"""
from __future__ import annotations

import hashlib
import hmac
import html
import logging
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import parse_qs, quote

from fastapi import APIRouter, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from .. import audit
from ..config import get_settings, resolve_trading_mode
from ..database import get_pool
from ..domain.ops import kill_switch
from ..integrations.clob import get_clob_breaker
from ..monitoring.health import run_health_checks

logger = logging.getLogger(__name__)

router = APIRouter()

# Captured at module import so the dashboard reports time since process boot.
_PROCESS_START_MONOTONIC: float = time.monotonic()

REFRESH_SECONDS: int = 30
AUDIT_TAIL_LIMIT: int = 10

# Cookie that carries the post-login operator session. Holds an HMAC of
# OPS_SECRET (not the secret itself), HttpOnly + Secure + SameSite=Lax.
_OPS_COOKIE: str = "ops_session"
_OPS_COOKIE_MAX_AGE: int = 7 * 24 * 3600  # 7 days


def _uptime_seconds() -> int:
    return int(time.monotonic() - _PROCESS_START_MONOTONIC)


def _format_uptime(seconds: int) -> str:
    """Render ``seconds`` as ``Xd Yh Zm`` (or ``Yh Zm``, ``Zm Ws``)."""
    if seconds < 60:
        return f"{seconds}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, minutes = divmod(minutes, 60)
    if hours < 24:
        return f"{hours}h {minutes}m"
    days, hours = divmod(hours, 24)
    return f"{days}d {hours}h {minutes}m"


def _resolve_mode() -> str:
    """Paper/live label — delegates to the canonical ``config.resolve_trading_mode``."""
    return resolve_trading_mode(get_settings())


def _resolve_version() -> str:
    s = get_settings()
    v = (s.APP_VERSION or "").strip()
    return v or "unknown"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


async def _count_users() -> int | None:
    """Return total user count, or ``None`` on DB failure."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            return int(await conn.fetchval("SELECT COUNT(*) FROM users") or 0)
    except Exception as exc:  # noqa: BLE001 — UI degrades to N/A
        logger.warning("ops dashboard: count_users failed: %s", exc)
        return None


async def _fetch_audit_tail(limit: int = AUDIT_TAIL_LIMIT) -> list[dict] | None:
    """Last ``limit`` audit rows, newest first. ``None`` on DB failure."""
    try:
        pool = get_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                "SELECT ts, action, actor_role FROM audit.log "
                "ORDER BY ts DESC LIMIT $1",
                limit,
            )
        return [dict(r) for r in rows]
    except Exception as exc:  # noqa: BLE001 — UI degrades to N/A
        logger.warning("ops dashboard: audit tail fetch failed: %s", exc)
        return None


def _circuit_state_snapshot() -> dict[str, object]:
    """Read-only snapshot of the CLOB circuit breaker.

    Returned shape: ``{"state": str, "failures": int, "threshold": int,
    "seconds_until_half_open": float}`` -- keys the dashboard renderer
    consumes directly. A failure resolving the breaker (e.g. import
    error in a degraded environment) degrades the card to N/A rather
    than 5xx-ing the whole page.
    """
    try:
        snap = get_clob_breaker().snapshot()
    except Exception as exc:  # noqa: BLE001 -- UI degrades to N/A
        logger.warning("ops dashboard: circuit snapshot failed: %s", exc)
        return {
            "state": "N/A",
            "failures": 0,
            "threshold": 0,
            "seconds_until_half_open": 0.0,
        }
    return {
        "state": str(snap.get("state", "N/A")),
        "failures": int(snap.get("failures", 0) or 0),
        "threshold": int(snap.get("threshold", 0) or 0),
        "seconds_until_half_open": float(
            snap.get("seconds_until_half_open", 0.0) or 0.0
        ),
    }


async def _kill_switch_state() -> str:
    """Return ``"ACTIVE"`` (paused) / ``"PAUSED"`` (running) / ``"N/A"``.

    The brief uses the labels ``ACTIVE`` (kill switch engaged → bot paused)
    vs ``PAUSED`` (kill switch released → bot running). We mirror that
    vocabulary in the rendered page so the operator sees identical
    wording across Telegram and the web dashboard.
    """
    try:
        active = await kill_switch.is_active()
    except Exception as exc:  # noqa: BLE001 — UI degrades to N/A
        logger.warning("ops dashboard: kill_switch.is_active failed: %s", exc)
        return "N/A"
    return "ACTIVE" if active else "PAUSED"


def _badge(state: str) -> str:
    """Render a coloured ok / fail / warn badge."""
    state = state.lower()
    if state == "ok":
        cls = "ok"
        label = "ok"
    elif state.startswith("error") or state == "fail":
        cls = "fail"
        label = "fail"
    else:
        cls = "warn"
        label = state
    return f'<span class="badge {cls}">{html.escape(label)}</span>'


def _render_audit_rows(rows: list[dict] | None) -> str:
    if rows is None:
        return '<tr><td colspan="3" class="muted">N/A — data not available</td></tr>'
    if not rows:
        return '<tr><td colspan="3" class="muted">no audit entries yet</td></tr>'
    out: list[str] = []
    for r in rows:
        ts = r.get("ts")
        ts_str = ts.isoformat(timespec="seconds") if ts is not None else "?"
        action = html.escape(str(r.get("action", "")))
        actor = html.escape(str(r.get("actor_role", "")))
        out.append(
            f'<tr><td><code>{html.escape(ts_str)}</code></td>'
            f'<td>{action}</td><td>{actor}</td></tr>'
        )
    return "\n".join(out)


def _render_health_rows(checks: dict[str, str]) -> str:
    out: list[str] = []
    for name in ("database", "telegram", "alchemy_rpc", "alchemy_ws"):
        state = checks.get(name, "N/A")
        out.append(
            f'<tr><td>{html.escape(name)}</td>'
            f'<td>{_badge(state)}</td></tr>'
        )
    return "\n".join(out)


def _render_page(
    *,
    version: str,
    mode: str,
    uptime: str,
    health: dict,
    user_count: int | None,
    kill_state: str,
    circuit: dict[str, object],
    audit_rows: list[dict] | None,
    flash: str | None = None,
) -> str:
    """Compose the HTML page. All variables are escape-controlled at source."""
    user_count_str = "N/A" if user_count is None else str(user_count)
    kill_class = "fail" if kill_state == "ACTIVE" else "ok" if kill_state == "PAUSED" else "warn"
    kill_label = html.escape(kill_state)
    circuit_state = str(circuit.get("state", "N/A"))
    if circuit_state == "CLOSED":
        circuit_class = "ok"
    elif circuit_state in ("OPEN", "HALF_OPEN"):
        circuit_class = "fail" if circuit_state == "OPEN" else "warn"
    else:
        circuit_class = "warn"
    circuit_label = html.escape(circuit_state)
    circuit_failures = int(circuit.get("failures", 0) or 0)
    circuit_threshold = int(circuit.get("threshold", 0) or 0)
    circuit_eta = float(circuit.get("seconds_until_half_open", 0.0) or 0.0)
    if circuit_state == "OPEN":
        circuit_detail = (
            f"{circuit_failures}/{circuit_threshold} failures "
            f"-- half-opens in {int(circuit_eta)}s"
        )
    elif circuit_state == "HALF_OPEN":
        circuit_detail = "trial allowed -- next failure re-opens"
    elif circuit_state == "CLOSED":
        circuit_detail = (
            f"{circuit_failures}/{circuit_threshold} consecutive failures"
        )
    else:
        circuit_detail = "unavailable"
    flash_html = (
        f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    )
    # Auth rides on the HttpOnly ``ops_session`` cookie set at login, so the
    # form actions carry no secret in the URL.
    # The two action forms POST to /ops/kill and /ops/resume; both redirect
    # back to /ops with a flash query param so the operator sees a confirm
    # message after the round trip.
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta http-equiv="refresh" content="{REFRESH_SECONDS}">
<title>CrusaderBot ops</title>
<style>
  :root {{
    --bg:#0d1117; --fg:#e6edf3; --muted:#7d8590;
    --card:#161b22; --border:#30363d;
    --ok:#238636; --fail:#da3633; --warn:#9e6a03;
    --accent:#1f6feb;
  }}
  * {{ box-sizing:border-box; }}
  body {{
    margin:0; padding:1rem; background:var(--bg); color:var(--fg);
    font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
    line-height:1.4;
  }}
  h1 {{ margin:0 0 .25rem 0; font-size:1.4rem; }}
  .meta {{ color:var(--muted); font-size:.85rem; margin-bottom:1rem; }}
  .grid {{
    display:grid; gap:1rem;
    grid-template-columns:repeat(auto-fit,minmax(260px,1fr));
    margin-bottom:1rem;
  }}
  .card {{
    background:var(--card); border:1px solid var(--border);
    border-radius:8px; padding:1rem;
  }}
  .card h2 {{ margin:0 0 .5rem 0; font-size:1rem; color:var(--muted);
              text-transform:uppercase; letter-spacing:.05em; }}
  .big {{ font-size:1.6rem; font-weight:600; }}
  table {{ width:100%; border-collapse:collapse; font-size:.9rem; }}
  td {{ padding:.35rem .25rem; border-bottom:1px solid var(--border); vertical-align:top; }}
  tr:last-child td {{ border-bottom:none; }}
  code {{ font-family:ui-monospace,SFMono-Regular,Menlo,monospace;
          font-size:.85rem; color:var(--muted); }}
  .badge {{
    display:inline-block; padding:.1rem .5rem; border-radius:999px;
    font-size:.75rem; font-weight:600; text-transform:uppercase;
  }}
  .badge.ok   {{ background:var(--ok);   color:#fff; }}
  .badge.fail {{ background:var(--fail); color:#fff; }}
  .badge.warn {{ background:var(--warn); color:#fff; }}
  .actions {{ display:flex; gap:.5rem; flex-wrap:wrap; }}
  button {{
    flex:1; padding:.75rem 1rem; border:1px solid var(--border);
    border-radius:6px; background:var(--card); color:var(--fg);
    font-size:1rem; font-weight:600; cursor:pointer;
  }}
  button.kill   {{ background:var(--fail); border-color:var(--fail); color:#fff; }}
  button.resume {{ background:var(--ok);   border-color:var(--ok);   color:#fff; }}
  .flash {{
    margin:0 0 1rem 0; padding:.75rem 1rem;
    background:#0c2d6b; border:1px solid var(--accent);
    border-radius:6px;
  }}
  .muted {{ color:var(--muted); }}
  form {{ flex:1; margin:0; }}
</style>
</head>
<body>
<h1>CrusaderBot — ops</h1>
<div class="meta">
  Version <code>{html.escape(version)}</code>
  · Mode <code>{html.escape(mode.upper())}</code>
  · Uptime <code>{html.escape(uptime)}</code>
  · {html.escape(_now_iso())}
  · auto-refresh {REFRESH_SECONDS}s
</div>

{flash_html}

<div class="grid">
  <div class="card">
    <h2>Service</h2>
    <div>CrusaderBot</div>
    <div class="muted">FastAPI + Telegram + APScheduler</div>
  </div>
  <div class="card">
    <h2>Active users</h2>
    <div class="big">{html.escape(user_count_str)}</div>
    <div class="muted">total rows in users</div>
  </div>
  <div class="card">
    <h2>Kill switch</h2>
    <div class="big"><span class="badge {kill_class}">{kill_label}</span></div>
    <div class="muted">ACTIVE = paused, PAUSED = running</div>
  </div>
  <div class="card">
    <h2>CLOB circuit</h2>
    <div class="big"><span class="badge {circuit_class}">{circuit_label}</span></div>
    <div class="muted">{html.escape(circuit_detail)}</div>
  </div>
</div>

<div class="grid">
  <div class="card">
    <h2>Health checks</h2>
    <table>
      <tbody>
        {_render_health_rows(health.get("checks") or {})}
      </tbody>
    </table>
  </div>
  <div class="card">
    <h2>Controls</h2>
    <div class="actions">
      <form method="post" action="/ops/kill">
        <button class="kill" type="submit">Kill bot</button>
      </form>
      <form method="post" action="/ops/resume">
        <button class="resume" type="submit">Resume bot</button>
      </form>
    </div>
    <div class="muted" style="margin-top:.75rem;">
      Kill pauses NEW trades only. Existing positions stay open.
    </div>
    <form method="post" action="/ops/logout" style="margin-top:.75rem;">
      <button type="submit" style="flex:none;font-size:.8rem;padding:.4rem .75rem;">Sign out</button>
    </form>
  </div>
</div>

<div class="card">
  <h2>Audit log — last {AUDIT_TAIL_LIMIT}</h2>
  <table>
    <thead>
      <tr><td class="muted">ts</td><td class="muted">action</td><td class="muted">actor</td></tr>
    </thead>
    <tbody>
      {_render_audit_rows(audit_rows)}
    </tbody>
  </table>
</div>
</body>
</html>
"""


def _render_login_page(flash: str | None = None) -> str:
    """Minimal sign-in page shown when no valid session cookie is present.

    Exposes no system data — just a password field that POSTs the secret to
    ``/ops/login`` over HTTPS. The secret travels in the request body, never
    the URL.
    """
    flash_html = (
        f'<div class="flash">{html.escape(flash)}</div>' if flash else ""
    )
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>CrusaderBot ops — sign in</title>
<style>
  body {{ margin:0; min-height:100vh; display:flex; align-items:center;
          justify-content:center; background:#0d1117; color:#e6edf3;
          font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif; }}
  .box {{ background:#161b22; border:1px solid #30363d; border-radius:8px;
          padding:1.5rem; width:min(92vw,340px); }}
  h1 {{ font-size:1.2rem; margin:0 0 1rem 0; }}
  input {{ width:100%; padding:.75rem; margin-bottom:.75rem; border-radius:6px;
           border:1px solid #30363d; background:#0d1117; color:#e6edf3; font-size:1rem; }}
  button {{ width:100%; padding:.75rem; border:1px solid #1f6feb; border-radius:6px;
            background:#1f6feb; color:#fff; font-size:1rem; font-weight:600; cursor:pointer; }}
  .flash {{ margin:0 0 1rem 0; padding:.6rem .75rem; background:#3d1d1d;
            border:1px solid #da3633; border-radius:6px; font-size:.9rem; }}
  .muted {{ color:#7d8590; font-size:.8rem; margin-top:.75rem; }}
</style>
</head>
<body>
<div class="box">
  <h1>CrusaderBot — ops</h1>
  {flash_html}
  <form method="post" action="/ops/login">
    <input type="password" name="secret" placeholder="Operator secret" autofocus autocomplete="current-password">
    <button type="submit">Sign in</button>
  </form>
  <div class="muted">Authenticated sessions use a secure cookie. The secret is never placed in the URL.</div>
</div>
</body>
</html>
"""


def _ops_secret() -> str:
    """Return the configured ``OPS_SECRET`` (stripped), or ``""`` if unset."""
    return (get_settings().OPS_SECRET or "").strip()


def _session_token(secret: str) -> str:
    """Derive the cookie value from the secret.

    HMAC-SHA256 so the cookie never carries the raw ``OPS_SECRET`` (which is
    also the ``X-Ops-Token`` header value). Rotating ``OPS_SECRET`` changes
    this digest, invalidating every outstanding cookie.
    """
    return hmac.new(
        secret.encode("utf-8"), b"ops-session-v1", hashlib.sha256
    ).hexdigest()


def _matches_secret(provided: str | None, secret: str) -> bool:
    return bool(provided) and secrets.compare_digest(provided, secret)


def _valid_session(cookie: str | None, secret: str) -> bool:
    return bool(cookie) and secrets.compare_digest(cookie, _session_token(secret))


def _is_authenticated(request: Request, *, token: str | None = None) -> bool:
    """True if the request carries valid dashboard credentials.

    Accepts the session cookie OR a legacy ``?token=`` matching the secret.
    Returns False when no secret is configured (cannot authenticate).
    """
    secret = _ops_secret()
    if not secret:
        return False
    cookie = request.cookies.get(_OPS_COOKIE)
    return _valid_session(cookie, secret) or _matches_secret(token, secret)


def _authorize_mutation(
    *, header: str | None, token: str | None, cookie: str | None
) -> None:
    """Gate the POST mutators. 503 if no secret configured; 403 if no
    accepted credential (header, cookie session, or legacy token) matches.
    """
    secret = _ops_secret()
    if not secret:
        raise HTTPException(
            status_code=503,
            detail="ops controls disabled (OPS_SECRET unset)",
        )
    if (
        _matches_secret(header, secret)
        or _matches_secret(token, secret)
        or _valid_session(cookie, secret)
    ):
        return
    raise HTTPException(status_code=403, detail="forbidden")


def _set_session_cookie(response: Response, secret: str) -> None:
    """Attach the HttpOnly + Secure + SameSite=Lax session cookie."""
    response.set_cookie(
        key=_OPS_COOKIE,
        value=_session_token(secret),
        max_age=_OPS_COOKIE_MAX_AGE,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )


@router.get("/ops", response_class=HTMLResponse)
async def ops_dashboard(
    request: Request, flash: str | None = None, token: str | None = None,
) -> Response:
    """Render the operator dashboard, or the sign-in page when unauthenticated.

    Auth is cookie-based (see module docstring). When a secret is configured
    but the caller has no valid session, only the login form is rendered —
    no system data leaks to an anonymous visitor. A legacy ``?token=`` is
    auto-migrated into a cookie and the request is redirected to a clean
    ``/ops`` so the secret leaves the URL.

    Each I/O probe is independent: a DB outage degrades that card to N/A but
    the page still renders so the operator can see the (cached) kill switch
    state and the health badge that explains the failure.
    """
    secret = _ops_secret()

    # Legacy bookmark: ?token=<secret> -> set cookie, strip token from URL.
    if secret and _matches_secret(token, secret):
        resp = RedirectResponse(url=_redirect_url("Signed in."), status_code=303)
        _set_session_cookie(resp, secret)
        return resp

    # Secret configured but no valid session -> login form only (no data).
    if secret and not _is_authenticated(request):
        return HTMLResponse(content=_render_login_page(flash=flash))

    try:
        health = await run_health_checks()
    except Exception as exc:  # noqa: BLE001 — UI degrades
        logger.error("ops dashboard: run_health_checks failed: %s", exc)
        health = {"checks": {}}

    user_count = await _count_users()
    kill_state = await _kill_switch_state()
    audit_rows = await _fetch_audit_tail()
    circuit = _circuit_state_snapshot()
    body = _render_page(
        version=_resolve_version(),
        mode=_resolve_mode(),
        uptime=_format_uptime(_uptime_seconds()),
        health=health,
        user_count=user_count,
        kill_state=kill_state,
        circuit=circuit,
        audit_rows=audit_rows,
        flash=flash,
    )
    return HTMLResponse(content=body)


@router.post("/ops/login")
async def ops_login(request: Request) -> RedirectResponse:
    """Authenticate with ``OPS_SECRET`` and set the session cookie.

    The secret arrives in the urlencoded POST body (over HTTPS), never the
    URL. On success an HttpOnly + Secure + SameSite=Lax cookie is set and the
    operator is redirected to the dashboard. Wrong secret → back to the login
    page with an error flash (no cookie). Unset secret → 503.

    The body is parsed manually (``parse_qs``) rather than via FastAPI's
    ``Form`` so the app does not take a hard dependency on ``python-multipart``
    — a missing optional dep there would otherwise fail at import/boot.
    """
    expected = _ops_secret()
    if not expected:
        raise HTTPException(
            status_code=503, detail="ops controls disabled (OPS_SECRET unset)",
        )
    raw = (await request.body()).decode("utf-8", "ignore")
    provided = parse_qs(raw).get("secret", [""])[0]
    if not _matches_secret(provided, expected):
        return RedirectResponse(url=_redirect_url("Invalid secret."), status_code=303)
    resp = RedirectResponse(url=_redirect_url("Signed in."), status_code=303)
    _set_session_cookie(resp, expected)
    return resp


@router.post("/ops/logout")
async def ops_logout() -> RedirectResponse:
    """Clear the session cookie and return to the sign-in page."""
    resp = RedirectResponse(url=_redirect_url("Signed out."), status_code=303)
    resp.delete_cookie(_OPS_COOKIE, path="/")
    return resp


@router.post("/ops/kill")
async def ops_kill(
    request: Request,
    token: str | None = None,
    x_ops_token: str | None = Header(default=None),
) -> RedirectResponse:
    """Engage the kill switch and redirect back to the dashboard.

    Auth (any of): ``X-Ops-Token`` header, the ``ops_session`` cookie set at
    login, or a legacy ``?token=`` query param — all compared to
    ``OPS_SECRET``. Unset secret → 503; no valid credential → 403.

    Delegates to the shared ``domain.ops.kill_switch.set_active`` so this
    flip writes ``kill_switch_history`` AND emits a ``kill_switch_pause``
    audit row. ``actor_id=None`` because the secret is shared, not
    per-operator; the action label still distinguishes the ops surface from
    a Telegram flip via the ``source`` payload field.
    """
    _authorize_mutation(
        header=x_ops_token, token=token,
        cookie=request.cookies.get(_OPS_COOKIE),
    )
    flash = "Kill switch engaged — new trades blocked."
    try:
        await kill_switch.set_active(
            action="pause",
            actor_id=None,
            reason="ops dashboard kill",
        )
        await audit.write(
            actor_role="operator",
            action="kill_switch_pause",
            payload={
                "source": "ops_dashboard_web",
                "client_host": request.client.host if request.client else None,
            },
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.error("ops dashboard: kill failed: %s", exc)
        flash = f"Kill failed: {type(exc).__name__}"
    resp = RedirectResponse(url=_redirect_url(flash), status_code=303)
    # Establish/refresh the cookie so a legacy ?token= caller transitions to
    # the cookie session and the next GET renders the dashboard.
    if _ops_secret():
        _set_session_cookie(resp, _ops_secret())
    return resp


@router.post("/ops/resume")
async def ops_resume(
    request: Request,
    token: str | None = None,
    x_ops_token: str | None = Header(default=None),
) -> RedirectResponse:
    """Release the kill switch and redirect back to the dashboard.

    Auth contract identical to ``POST /ops/kill`` — see that handler's
    docstring.
    """
    _authorize_mutation(
        header=x_ops_token, token=token,
        cookie=request.cookies.get(_OPS_COOKIE),
    )
    flash = "Kill switch released — bot resumed."
    try:
        await kill_switch.set_active(
            action="resume",
            actor_id=None,
            reason="ops dashboard resume",
        )
        await audit.write(
            actor_role="operator",
            action="kill_switch_resume",
            payload={
                "source": "ops_dashboard_web",
                "client_host": request.client.host if request.client else None,
            },
        )
    except Exception as exc:  # noqa: BLE001 — boundary
        logger.error("ops dashboard: resume failed: %s", exc)
        flash = f"Resume failed: {type(exc).__name__}"
    resp = RedirectResponse(url=_redirect_url(flash), status_code=303)
    if _ops_secret():
        _set_session_cookie(resp, _ops_secret())
    return resp


def _redirect_url(flash: str) -> str:
    """Build the post-action redirect URL back to the dashboard.

    No token is carried in the URL — auth rides on the session cookie.
    """
    return "/ops?flash=" + quote(flash, safe="")
