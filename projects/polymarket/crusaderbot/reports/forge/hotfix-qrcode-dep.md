# WARP•FORGE Report — hotfix-qrcode-dep

Branch: WARP/CRUSADERBOT-HOTFIX-QRCODE-DEP
Date: 2026-05-10 Asia/Jakarta
Validation Tier: MINOR
Claim Level: FOUNDATION
Validation Target: Dependency declaration only — `qrcode[pil]>=7.4.2` added to crusaderbot pyproject.toml so `import qrcode` in `bot/handlers/onboarding.py` resolves at runtime in the Docker image.
Not in Scope: Runtime integration testing of Phase 5H onboarding QR rendering, repo-root requirements.txt (already lists qrcode), projects/polymarket/requirements.txt (PolyQuantBot scope, no qrcode usage).
Suggested Next Step: Merge after WARP🔹CMD review; rebuild fly.io image so Phase 5H onboarding flow can resolve `import qrcode` in production paper deploy.

---

## 1. What was built

Hotfix declaring the missing `qrcode[pil]` runtime dependency for CrusaderBot. PR #937 (Phase 5H onboarding) introduced `import qrcode` in `projects/polymarket/crusaderbot/bot/handlers/onboarding.py:8` for wallet deposit QR code generation but did not add the package to the project's install manifest. The Docker build (`projects/polymarket/crusaderbot/Dockerfile:21`) installs strictly from `pyproject.toml` via `pip install --no-cache-dir /app/`, so absence of the dependency would cause `ModuleNotFoundError: qrcode` in the onboarding flow once Phase 5H ships.

## 2. Current system architecture

Dependency surface unchanged at the runtime/architecture level. CrusaderBot install path:

```
Dockerfile  ->  COPY pyproject.toml /app/
            ->  pip install --no-cache-dir /app/
                  └── reads [project.dependencies] from pyproject.toml
```

`qrcode[pil]` is a leaf-level pure-python dependency (with the Pillow extra) used only by the onboarding handler for binary QR PNG generation. No new pipeline stages, no new modules, no execution path or risk path touched.

## 3. Files created / modified (full repo-root paths)

Modified:
- `projects/polymarket/crusaderbot/pyproject.toml` — added `"qrcode[pil]>=7.4.2"` to `[project.dependencies]` with one-line context comment referencing Phase 5H usage.

Created:
- `projects/polymarket/crusaderbot/reports/forge/hotfix-qrcode-dep.md` — this report.

State files updated:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md` — Last Updated bumped, Known Issues entry resolved/removed (none was present), CHANGELOG entry referenced.
- `projects/polymarket/crusaderbot/state/CHANGELOG.md` — append-only entry for lane closure.

## 4. What is working

- `pyproject.toml` now declares `qrcode[pil]>=7.4.2` so the next image rebuild will resolve `import qrcode` in `bot/handlers/onboarding.py`.
- Existing dependency lines preserved verbatim; no version bumps introduced as side effects.
- Repo-root `requirements.txt` already pins `qrcode[pil]>=7.4.2` (line 28), so contributor-side `pip install -r requirements.txt` workflows remain unaffected.
- No code changes outside the manifest edit — no risk to runtime behavior on existing code paths.

## 5. Known issues

- None introduced by this hotfix.
- The Phase 5H onboarding PR (#937) remains in the "PR open for WARP🔹CMD review" state per `PROJECT_STATE.md`; this hotfix only unblocks the dependency, not the review/merge of Phase 5H itself.
- `projects/polymarket/requirements.txt` (PolyQuantBot scope) is intentionally not modified — it is not on the CrusaderBot install path and does not currently import qrcode.

## 6. What is next

- WARP🔹CMD review and merge of this PR (MINOR tier, no SENTINEL gate).
- Rebuild and redeploy the Fly.io paper image so the onboarding flow can render QR codes once Phase 5H lands.
- No follow-up tasks queued from this lane.
