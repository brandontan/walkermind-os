-- live-mode-truth (WARP/root-live-mode-truth): trading_mode is the single
-- per-user mode truth; paper_mode_override is kept as a synced mirror so the
-- (unwired) is_live_execution_allowed predicate and any legacy reader agree
-- with it. Historic rows could disagree (the old /live/enable wrote
-- trading_mode without clearing the override — the owner's row showed LIVE
-- on one surface and PAPER on another). One-shot sync; idempotent.
UPDATE user_settings
   SET paper_mode_override = (trading_mode IS DISTINCT FROM 'live')
 WHERE paper_mode_override IS DISTINCT FROM (trading_mode IS DISTINCT FROM 'live');
