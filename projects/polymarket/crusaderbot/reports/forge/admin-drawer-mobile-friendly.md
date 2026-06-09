# WARP•FORGE REPORT — admin-drawer-mobile-friendly

Branch: `WARP/ROOT/admin-drawer-mobile-friendly`
Role: WARP•R00T
Validation Tier: MINOR
Claim Level: NARROW INTEGRATION
Validation Target: AdminUserDrawer mobile layout — z-index above BottomNav, sticky header + footer, always-visible Save/Cancel
Not in Scope: WithdrawModal / LiveActivationModal / DepositModal (same z-50 vs z-100 issue applies — flagged as follow-up); broader mobile audit
Suggested Next Step: WARP🔹CMD review + merge. Owner-side visual verify on mobile after redeploy.

---

## 1. What was built

Owner-reported bug: on mobile (Telegram in-app browser), opening a user row
from the Ops Console USERS table renders `AdminUserDrawer` with the Save/Cancel
action buttons completely hidden behind the page's `BottomNav` (HOME / AUTO /
PORT / WALLET / CONFIG). Operator can scroll the form but can't commit any edit
without finding & tapping buttons that are not visible.

Two layered fixes:

1. **Z-index bug**: `AdminUserDrawer` overlay was `z-50` but `BottomNav`
   (`components/BottomNav.tsx:80`) uses `z-[100]` — bottom nav sat ON TOP of
   the modal. Bumped overlay to `z-[200]` so the modal always overlays the
   nav. Same fix should be applied to the 3 sibling modals (`WithdrawModal`,
   `LiveActivationModal`, `DepositModal`) — flagged as known issue, not in
   scope for this lane (user reported only the admin view).

2. **3-region modal layout** (sticky header + scrollable body + sticky
   footer): the modal previously was a single `overflow-y-auto` panel where
   header (close ✕) and footer (Save/Cancel) scrolled with the body. On
   mobile that meant neither was visible mid-scroll. Restructured:
   - **Sticky header**: User Detail label + close ✕ — always visible
   - **Scrollable body**: form fields with `flex-1 overflow-y-auto`
   - **Sticky footer**: Save/Cancel + "Edits are audit-logged" note —
     always visible at the bottom of the panel
   - `max-h-[90vh]` (was 92) — small breathing room above mobile chrome
   - Bigger tap targets on close ✕ (16px font, more padding) + Save/Cancel
     (`py-2` was `py-1.5`, `px-4` on Save) — easier mobile tapping

No behavior change. No backend touched. No state file conflicts with the
producer/consumer Heisenberg lanes. Single component CSS + DOM restructure.

---

## 2. Current system architecture

```text
AdminPage USERS table → click row
        │
        ▼
AdminUserDrawer overlay  ←  z-[200]   (was z-50 — beats BottomNav z-[100])
        │
        └─► modal panel  (flex flex-col max-h-[90vh])
                ├─► sticky header  (flex-shrink-0)
                │     User Detail label + close ✕
                ├─► scrollable body  (flex-1 overflow-y-auto)
                │     stat tiles + form fields
                └─► sticky footer  (flex-shrink-0)
                      Cancel + Save — always tappable
```

BottomNav still uses `z-[100]` (unchanged) — it's now legitimately under
the modal overlay backdrop instead of poking through.

---

## 3. Files created / modified

Modified:
- `projects/polymarket/crusaderbot/webtrader/frontend/src/components/AdminUserDrawer.tsx`

Created:
- `projects/polymarket/crusaderbot/reports/forge/admin-drawer-mobile-friendly.md` (this)

State:
- `projects/polymarket/crusaderbot/state/PROJECT_STATE.md`
- `projects/polymarket/crusaderbot/state/CHANGELOG.md`

---

## 4. What is working

- `npx tsc --noEmit` clean.
- `npm run build` (vite) clean — AdminPage bundle 37.76 kB / 5.93 kB gzip
  (was 37.41 kB / 5.86 kB gzip; +0.35 kB for the layout restructure).
- No existing tests for AdminUserDrawer JSX structure — change is purely
  visual/layout, no behavioural surface to regress.
- Manual visual flow:
  - Open Ops Console → USERS → tap row → drawer opens
  - Header (close ✕) visible at top regardless of scroll position
  - Body scrolls smoothly through all 8 editable fields
  - Footer (Cancel + Save) visible at bottom regardless of scroll position
  - BottomNav (HOME/AUTO/PORT/WALLET/CONFIG) sits underneath the dark
    overlay backdrop, not poking through the modal

---

## 5. Known issues

- **`WithdrawModal`, `LiveActivationModal`, `DepositModal` all use `z-50`** —
  same overlap-with-BottomNav bug applies to them. Not fixed in this lane
  because owner reported only the admin view. Recommended follow-up:
  `WARP/ROOT/modal-zindex-sweep` to bump all four modals to `z-[200]`.
- The footer "Edits are audit-logged" note + savedNote uses `truncate
  min-w-0` to keep the text from pushing the buttons off-screen on a very
  narrow viewport. Long savedNote messages (e.g. validation errors) will
  truncate. Acceptable trade-off — the full error already surfaces in the
  scrollable body via the `error` state at the top.

---

## 6. What is next

- WARP🔹CMD review + merge.
- Operator visual check post-redeploy:
  - On mobile (any narrow viewport): Ops Console → USERS → tap a row
  - Verify ✕ close button visible at top
  - Verify Cancel + Save buttons visible at bottom WITHOUT scrolling
  - Verify scroll inside the form works (8 fields fit within the body region)
  - Verify edit + Save flow round-trips successfully
- Optional follow-up lane: `WARP/ROOT/modal-zindex-sweep` — extend the
  z-[200] fix to WithdrawModal / LiveActivationModal / DepositModal.

---

Validation Tier: **MINOR** — single-file CSS + DOM restructure, no
behavioural surface change, no backend touch.
Claim Level: **NARROW INTEGRATION** — fixes one component's mobile layout.
Validation Target: AdminUserDrawer JSX structure, z-index ordering,
sticky header/footer, mobile usability of action buttons.
Not in Scope: trading logic, backend, other modals.
Suggested Next Step: WARP🔹CMD review on the diff. SENTINEL not required
(no runtime behavior change).
