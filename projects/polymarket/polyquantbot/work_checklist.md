## CrusaderBot Work Checklist

### From Now to Finish

## PRIORITY 1 — Bot Public-Ready Baseline

Ini yang harus beres sekarang dulu.

1. Telegram runtime activation

[ ] pastikan Telegram listener/worker benar-benar aktif di Fly

[ ] pastikan mode runtime jelas: polling atau webhook

[ ] pastikan bot startup otomatis saat app boot

[ ] pastikan /ready truthful terhadap runtime Telegram

[ ] pastikan worker_runtime.active truthful

[ ] pastikan worker_runtime.startup_complete truthful

[ ] tambahkan startup log Telegram yang jelas

[ ] hilangkan silent disabled mode


2. Baseline public commands

[ ] /start reply sukses

[ ] /help reply sukses

[ ] /status reply sukses

[ ] tidak ada response kosong/dummy

[ ] tidak ada timeout/silent fail


3. Public onboarding

[ ] intro user baru jelas

[ ] paper-only state dijelaskan

[ ] capability yang ready dijelaskan

[ ] next step dijelaskan

[ ] unlinked-user flow rapi

[ ] linked-user flow rapi

[ ] fallback onboarding tidak membingungkan


4. Public command set

[ ] /paper

[ ] /about

[ ] /risk

[ ] /account atau /link

[ ] public command dipisah dari admin/operator command

[ ] command yang belum siap disembunyikan


5. UX polish

[ ] welcome copy rapi

[ ] help copy rapi

[ ] status copy singkat dan jelas

[ ] tidak ada raw debug ke user

[ ] formatting Telegram rapi


6. Public-safe boundaries

[ ] no live-trading claim

[ ] no production-capital claim

[ ] paper-only boundary konsisten

[ ] admin/internal path diberi guard


7. Observability baseline

[ ] log startup bot

[ ] log command received

[ ] log command handled

[ ] log reply success/fail

[ ] log missing env / disabled mode


8. End-to-end validation

[ ] deploy latest

[ ] /health OK

[ ] /ready OK

[ ] /start OK

[ ] /help OK

[ ] /status OK

[ ] evidence disimpan


Done condition PRIORITY 1

[ ] bot benar-benar usable sebagai public-ready paper bot baseline



---

PRIORITY 2 — DB, Persistence, Runtime Hardening

Setelah bot bisa dipakai, bikin stabil.

9. Supabase / Postgres integration hardening

[ ] DATABASE_URL final stabil

[ ] sslmode=require dipastikan

[ ] pooled connection dipastikan

[ ] DB health check jalan

[ ] startup tidak crash saat DB lambat


10. Persistence stabilization

[ ] audit state yang masih file/tmp

[ ] pindahkan user/session critical state ke DB

[ ] pindahkan link/account state ke DB

[ ] no split-brain file vs DB

[ ] restart deploy tidak merusak state


11. Runtime config hardening

[ ] env wajib tervalidasi saat boot

[ ] missing secret error jelas

[ ] unsafe default dikurangi

[ ] startup summary aman dan truthful


12. Health/readiness truth hardening

[ ] /health cek proses utama

[ ] /ready cek dependency relevan

[ ] Telegram status masuk readiness

[ ] DB status masuk readiness

[ ] no false green status


13. Error handling & resilience

[ ] graceful shutdown benar

[ ] restart safety baik

[ ] worker crash tidak corrupt state

[ ] retry non-fatal dependency rapi


14. Logging & monitoring hardening

[ ] structured logging konsisten

[ ] startup log informatif

[ ] trace error jelas

[ ] monitoring minimum viable siap


15. Security baseline

[ ] secrets tidak bocor di log

[ ] no hardcoded credential

[ ] admin access aman

[ ] sensitive routes dibatasi


16. Deployment hardening

[ ] Dockerfile bersih

[ ] fly.toml sinkron

[ ] restart policy jelas

[ ] rollback strategy jelas

[ ] smoke test pascadeploy jelas


Done condition PRIORITY 2

[ ] bot tidak cuma hidup, tapi stabil dan persistent



---

PRIORITY 3 — Paper Trading Product Completion

Setelah runtime stabil, bikin produk paper-nya benar-benar siap.

17. Paper account model

[ ] paper balance model

[ ] paper position tracking

[ ] paper PnL tracking

[ ] reset/test flow operator


18. Paper execution engine

[ ] paper order intent flow

[ ] paper entry logic

[ ] paper exit logic

[ ] paper fill assumptions jelas

[ ] paper execution logging jelas


19. Paper portfolio surface

[ ] open paper positions visible

[ ] realized PnL visible

[ ] unrealized PnL visible

[ ] summary via bot/API


20. Paper risk controls

[ ] exposure caps enforced

[ ] drawdown caps enforced

[ ] kill switch enforced

[ ] risk state visible


21. Paper strategy visibility

[ ] strategy state visible

[ ] signal state visible

[ ] enable/disable visibility

[ ] suppressed/blocked reasoning visible


22. Admin/operator paper controls

[ ] runtime paper summary

[ ] readiness paper state

[ ] pause/resume kalau didukung

[ ] admin command separated


23. Public paper UX completion

[ ] user paham ini paper mode

[ ] status paper product visible

[ ] keterbatasan produk visible

[ ] messaging premium


24. Paper validation

[ ] execution test end-to-end

[ ] persistence test

[ ] restart/redeploy test

[ ] logs/evidence stored


Done condition PRIORITY 3

[ ] bot usable sebagai real paper trading product



---

PRIORITY 4 — Wallet Lifecycle Foundation

Ini fondasi untuk layer setelah paper product.

25. Wallet domain model

[ ] wallet entity model final

[ ] ownership model final

[ ] wallet status/state model final


26. Wallet lifecycle

[ ] create/init wallet lifecycle

[ ] link/unlink lifecycle

[ ] activation/deactivation lifecycle

[ ] invalid/blocked state handling


27. Secure wallet persistence

[ ] wallet records persistent

[ ] secret handling aman

[ ] audit trail minimum ada


28. Wallet auth boundary

[ ] ownership verification jelas

[ ] admin vs user wallet access dipisah

[ ] no privilege crossover


29. Wallet surfaces

[ ] wallet status readable

[ ] wallet lifecycle state readable

[ ] link state readable

[ ] user-facing copy aman


30. Wallet recovery & tests

[ ] broken link recovery

[ ] stale wallet recovery

[ ] duplicate wallet handling

[ ] lifecycle tests

[ ] integration tests


Done condition PRIORITY 4

[ ] wallet lifecycle utuh dan stabil



---

PRIORITY 5 — Portfolio Management Logic

Setelah wallet foundation, baru portfolio.

31. Portfolio model

[ ] portfolio entity model

[ ] per-user portfolio model

[ ] per-wallet portfolio relation


32. Exposure aggregation

[ ] aggregate exposure logic

[ ] per-market exposure logic

[ ] per-user exposure logic

[ ] per-wallet exposure logic


33. Allocation logic

[ ] bankroll allocation model

[ ] strategy allocation model

[ ] user/wallet aware allocation


34. PnL logic

[ ] realized PnL computation

[ ] unrealized PnL computation

[ ] portfolio-level summary

[ ] history/snapshot structure


35. Portfolio guardrails

[ ] exposure cap enforcement

[ ] drawdown cap

[ ] concentration cap

[ ] kill switch interaction


36. Portfolio surfaces & validation

[ ] bot/API summary

[ ] admin/operator portfolio surface

[ ] persistence & recovery

[ ] validation

[ ] closure docs sync


Done condition PRIORITY 5

[ ] portfolio dikelola di level sistem, bukan manual/ad hoc



---

PRIORITY 6 — Multi-Wallet Orchestration

Baru setelah wallet + portfolio jelas.

37. Orchestration model

[ ] multi-wallet routing model

[ ] wallet selection rules

[ ] ownership-aware routing


38. Allocation across wallets

[ ] balance-aware allocation

[ ] strategy-aware allocation

[ ] risk-aware allocation

[ ] failover wallet selection


39. Cross-wallet state truth

[ ] unified view across wallets

[ ] no duplicate/conflicting state

[ ] shared exposure truth


40. Cross-wallet controls

[ ] per-wallet enable/disable

[ ] per-wallet health status

[ ] per-wallet risk state

[ ] portfolio-wide control overlay


41. UX/API and recovery

[ ] admin/operator visibility

[ ] safe user summaries if needed

[ ] wallet unavailable handling

[ ] routing conflict handling

[ ] degraded mode behavior


42. Persistence & validation

[ ] orchestration state persistence

[ ] reconciliation traces

[ ] simulations/tests

[ ] closure docs sync


Done condition PRIORITY 6

[ ] system bisa koordinasi lebih dari satu wallet secara truthful dan aman



---

PRIORITY 7 — Settlement, Retry, Reconciliation & Ops Automation

43. Settlement workflow

[ ] settlement workflow defined

[ ] status transitions defined

[ ] idempotency model defined


44. Retry engine

[ ] retry rules

[ ] retry caps

[ ] backoff strategy

[ ] fatal vs retryable distinction


45. Batching logic

[ ] settlement batching rules

[ ] queueing model

[ ] partial batch handling

[ ] batch observability


46. Reconciliation logic

[ ] internal vs external reconciliation

[ ] mismatch detection

[ ] stuck state detection

[ ] repair/recovery flow


47. Operator tooling

[ ] settlement status visibility

[ ] retry visibility

[ ] failed batch visibility

[ ] admin intervention paths


48. Persistence, alerts, validation

[ ] settlement events persistent

[ ] retry history persistent

[ ] reconciliation results persistent

[ ] critical alerts

[ ] drift alerts

[ ] validation

[ ] closure docs sync


Done condition PRIORITY 7

[ ] ops flow resilient, observable, and recoverable



---

PRIORITY 8 — Production-Capital Readiness

Ini paling belakang. Jangan dibuka sebelum semua fondasi atas selesai.

49. Capability boundary review

[ ] audit semua paper-only assumptions

[ ] identifikasi semua area belum aman untuk capital

[ ] define exact capital-readiness criteria


50. Capital-mode config model

[ ] capital-mode config defined

[ ] strict feature gating

[ ] explicit enable path

[ ] safeguards default-off


51. Capital risk controls hardening

[ ] position sizing hardening

[ ] max loss hardening

[ ] drawdown hardening

[ ] kill switch hardening

[ ] circuit breaker hardening


52. Live execution readiness

[ ] live execution path audit

[ ] live order flow truth

[ ] external dependency risk review

[ ] failure mode review

[ ] rollback/disable path


53. Security & observability hardening

[ ] secret handling hardened

[ ] permission model hardened

[ ] admin action guardrails hardened

[ ] production-grade alerting

[ ] incident visibility

[ ] runbooks


54. Capital validation & claim review

[ ] dry-run validation

[ ] staged rollout validation

[ ] docs/policy/claim review

[ ] no overclaim

[ ] release decision


Done condition PRIORITY 8

[ ] project bisa truthfully claim production-capital readiness



---

PRIORITY 9 — Final Product Completion, Launch Assets, Handoff

Tahap finish 100%.

55. Public product assets

[ ] README final premium

[ ] docs final sync

[ ] launch summary

[ ] onboarding docs

[ ] support/help docs


56. Ops handoff assets

[ ] deployment guide

[ ] secrets/env guide

[ ] troubleshooting guide

[ ] incident guide

[ ] rollback guide


57. Monitoring/admin surfaces final

[ ] project monitor final

[ ] admin visibility final

[ ] operator checklists final

[ ] release dashboard final


58. Repo hygiene final

[ ] stale docs cleaned

[ ] stale reports clarified/archived

[ ] roadmap final sync

[ ] project state final sync

[ ] misleading checklist removed


59. Validation archive

[ ] FORGE reports organized

[ ] SENTINEL reports organized

[ ] BRIEFER assets organized

[ ] milestone evidence preserved


60. Final acceptance

[ ] runtime stable

[ ] persistence stable

[ ] wallet lifecycle complete

[ ] portfolio complete

[ ] multi-wallet orchestration complete

[ ] settlement/retry/reconciliation complete

[ ] capital readiness complete

[ ] docs and ops complete

[ ] final COMMANDER acceptance


Done condition PRIORITY 9

[ ] project finish 100%



---

Simple execution order

Kerjain berurutan:

[ ] PRIORITY 1 — Public Bot Runtime & Baseline

[ ] PRIORITY 2 — DB, Persistence, Runtime Hardening

[ ] PRIORITY 3 — Paper Trading Product Completion

[ ] PRIORITY 4 — Wallet Lifecycle Foundation

[ ] PRIORITY 5 — Portfolio Management Logic

[ ] PRIORITY 6 — Multi-Wallet Orchestration

[ ] PRIORITY 7 — Settlement / Retry / Reconciliation

[ ] PRIORITY 8 — Production-Capital Readiness

[ ] PRIORITY 9 — Final Completion / Handoff / Launch Assets


Right now

Yang paling dekat dikerjain:

[ ] redeploy/restart Fly dengan env terbaru

[ ] cek startup logs Telegram

[ ] aktifkan Telegram runtime beneran

[ ] test /start

[ ] test /help

[ ] test /status

