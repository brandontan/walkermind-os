# keyboards_v2 Migration Guide

## Overview

`keyboards_v2/` is a full redesign of the CrusaderBot Telegram keyboard layer.
It replaces the legacy `keyboards/` module (2166 lines, 21 files, 3 generations mixed).

## What Changed

### Architecture

| Aspect | keyboards/ (old) | keyboards_v2/ (new) |
|---|---|---|
| `__init__.py` | 541 lines, 48 functions | Re-exports only, 0 function defs |
| Shared helpers | 2 competing files (`_common.py` + `mvp/_common.py`) | 1 unified `_common.py` |
| Back button label | 3 variants (`⬅ Back`, `← Back`, `⬅️ Back`) | 1 variant (`⬅ Back`) |
| Callback prefixes | 37 unique prefixes | ~15 domain-scoped prefixes |
| Duplicate functions | 11 collisions | 0 |
| Emergency menu | 7 rows (violates UX rules) | 5 rows max (progressive disclosure) |
| Preset picker | 11 items vertical dump | 2-step: tier picker → preset list |
| MVP layer | Separate parallel tree (`mvp/`) | Integrated into main modules |
| File count | 21 files | 12 files |
| Total lines | ~2166 | ~750 |

### Preset Picker Progressive Disclosure

Old: All 11 presets shown at once in a vertical list.

New: Two-step flow:
1. **Risk tier picker** — Safe (3) / Balanced (3) / Advanced (4) / Aggressive (1)
2. **Preset list** — Only presets in chosen tier (max 4 + nav = 5 rows)

### Emergency Menu Progressive Disclosure

Old: 7 rows with 6 action buttons + back.

New: Two levels:
1. **Primary** — Pause / Pause+Close / System Status / More... / nav (5 rows)
2. **Secondary** — Stop All / Kill Positions / Lock Account / nav (4 rows)

## Migration Steps (for FORGE-X)

### Step 1: Validate keyboards_v2 (no runtime change)

```bash
cd projects/polymarket/crusaderbot
python -c "from bot.keyboards_v2 import *; print('OK')"
```

### Step 2: Update handler imports (file by file)

For each handler file, replace:
```python
# OLD
from ..keyboards import main_menu, dashboard_kb, preset_picker
from ..keyboards.presets import preset_confirm

# NEW
from ..keyboards_v2 import main_menu, dashboard_kb, preset_confirm_kb
from ..keyboards_v2.autotrade import preset_list_kb, preset_tier_kb
```

### Import mapping table

| Old import | New import |
|---|---|
| `keyboards.main_menu` | `keyboards_v2.main_menu` |
| `keyboards.main_menu_keyboard` | `keyboards_v2.main_menu` |
| `keyboards.dashboard_kb` | `keyboards_v2.dashboard_kb` |
| `keyboards.dashboard_nav` | `keyboards_v2.dashboard_kb` |
| `keyboards.p5_dashboard_kb` | `keyboards_v2.dashboard_kb` |
| `keyboards.portfolio_kb` | `keyboards_v2.portfolio_home_kb` |
| `keyboards.preset_picker` | `keyboards_v2.preset_tier_kb` (new flow) |
| `keyboards.presets.preset_picker` | `keyboards_v2.preset_tier_kb` (new flow) |
| `keyboards.presets.preset_confirm` | `keyboards_v2.preset_confirm_kb` |
| `keyboards.presets.preset_status` | `keyboards_v2.preset_status_kb` |
| `keyboards.preset_confirm_kb` | `keyboards_v2.preset_confirm_kb` |
| `keyboards.preset_active_kb` | `keyboards_v2.preset_status_kb` |
| `keyboards.mvp_risk_kb` | `keyboards_v2.risk_picker_kb` |
| `keyboards.risk_picker` | `keyboards_v2.risk_picker_kb` |
| `keyboards.emergency_p5_kb` | `keyboards_v2.emergency_home_kb` |
| `keyboards.emergency_confirm_p5_kb` | `keyboards_v2.emergency_confirm_kb` |
| `keyboards.emergency_done_p5_kb` | `keyboards_v2.emergency_done_kb` |
| `keyboards.emergency_menu` | `keyboards_v2.emergency_home_kb` |
| `keyboards.emergency_confirm` | `keyboards_v2.emergency_confirm_kb` |
| `keyboards.close_position_kb` | `keyboards_v2.position_close_kb` |
| `keyboards.close_confirm_kb` | `keyboards_v2.close_confirm_kb` |
| `keyboards.trades_kb` | `keyboards_v2.trades_home_kb` |
| `keyboards.trades_empty_kb` | `keyboards_v2.trades_empty_kb` |
| `keyboards.wallet_p5_kb` | `keyboards_v2.wallet_copy_kb` |
| `keyboards.wallet_menu` | `keyboards_v2.wallet_home_kb` |
| `keyboards.admin_menu` | `keyboards_v2.admin_menu_kb` |
| `keyboards.settings.settings_hub_kb` | `keyboards_v2.settings_hub_kb` |
| `keyboards.settings.tp_preset_kb` | `keyboards_v2.tp_picker_kb` |
| `keyboards.settings.sl_preset_kb` | `keyboards_v2.sl_picker_kb` |
| `keyboards.settings.capital_preset_kb` | `keyboards_v2.capital_picker_kb` |
| `keyboards.settings.settings_mode_picker` | `keyboards_v2.mode_picker_kb` |
| `keyboards.settings.autoredeem_settings_picker` | `keyboards_v2.redeem_picker_kb` |
| `keyboards.insights_kb` | `keyboards_v2.insights_kb` |
| `keyboards.chart_kb` | `keyboards_v2.chart_kb` |
| `keyboards.nav_row` | `keyboards_v2.back_home_row` |
| `keyboards.grid_rows` | `keyboards_v2.grid_rows` |
| `keyboards.mvp._common.main_menu_kb` | `keyboards_v2.main_menu` |
| `keyboards.mvp._common.BACK` | `keyboards_v2.BACK` |
| `keyboards.mvp._common.HOME` | `keyboards_v2.HOME` |

### Step 3: New handler for preset tier picker

The preset picker flow changed from 1-step to 2-step. Handlers need:

```python
# New callback: "preset:tiers" → show tier picker
# New callback: "preset:tier:{safe|balanced|advanced|aggressive}" → show presets in tier
# Existing callback: "preset:pick:{key}" → show preset detail (unchanged)
```

### Step 4: New handler for emergency progressive disclosure

```python
# New callback: "emergency:more" → show secondary actions
# New callback: "emergency:home" → return to primary actions
# Existing callbacks: "emergency:ask:*", "emergency:confirm:*" → unchanged
```

### Step 5: Update dispatcher callback patterns

Verify these patterns still match:
- `preset:` — now includes `preset:tiers` and `preset:tier:*`
- `emergency:` — now includes `emergency:more` and `emergency:home`
- All other patterns are backward-compatible

### Step 6: Archive old keyboards/

```bash
# After all handlers migrated and tests pass:
mv bot/keyboards bot/keyboards/_archive_legacy
mv bot/keyboards_v2 bot/keyboards
```

### Step 7: Delete MVP parallel tree

The `mvp/` subdirectory is fully merged into the new module.
No separate MVP tree needed.

## Callback Data Compatibility

Most callback_data values are preserved for backward compatibility.
New values added:

| New callback_data | Purpose |
|---|---|
| `preset:tiers` | Open risk tier picker |
| `preset:tier:safe` | Show Safe presets |
| `preset:tier:balanced` | Show Balanced presets |
| `preset:tier:advanced` | Show Advanced presets |
| `preset:tier:aggressive` | Show Aggressive presets |
| `emergency:more` | Show secondary emergency actions |
| `emergency:home` | Return to primary emergency actions |
| `emergency:status` | Show system status (renamed from confirm) |

## Files NOT migrated (keep in separate modules)

These files have complex wizard state and should migrate separately:

- `keyboards/copy_trade.py` (368 lines, 26 functions) — copy trade wizard
- `keyboards/signal_following.py` (45 lines) — signal subscription list
- `keyboards/market_card.py` (24 lines) — market card display

They can import `_common` helpers from `keyboards_v2._common` during transition.
