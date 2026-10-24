# WorkBuddy (`workbuddy`; realms `intl`, `cn`)

> Shared behavior: [../POLICY.md](../POLICY.md) §2-§3.

- **Prerequisite:** account credentials; local desktop scan/import is supported
  by the core.
- **Behavior:** CN check-in; Intl daily activity. The CN check-in task re-runs
  at 09/21 without a local "already checked in today" date gate, so a
  cross-timezone day boundary cannot lock the day. Replies are classified
  (`checked`/`already`/`pending`/`failed`) by code plus wording: only checked
  and already write `last_checkin`, so "处理中，请勿重复操作" no longer marks the
  day as done and silently drops the retry. Model/service-scoped errors (e.g.
  11158) do not penalize; ordinary 5xx only 500/502/503/504. 11158 is passed
  through unchanged; the PRO label now comes from the catalog tier map. 401
  refreshes and retries the same account; 11140 is a restriction-wave guard.
- **Intl daily activity:** one run is an ordered candidate list plus a
  per-account budget. `daily_chat_models` is tried in order (first entry is
  preferred; empty = built-in model plus the realm's free fallbacks); round
  count is `max(2, candidates)` and every round waits at most the turn cap or
  the remaining `daily_chat_budget` (default 600s, 0 = unlimited). Session
  create / sandbox failures add an exponential pause (base 5s doubling, 30s
  cap, `daily_chat_web_retry_backoff`, 0 = off) charged to the same budget;
  turn-phase failures are not paused again; business rejections are not
  retried. Accounts may run concurrently (1-10, default 1); prompts may be
  drawn from 300 builtin plus up to 200 custom lines (off by default). The
  desktop leg picks the first candidate without a model cooldown and still
  requires a valid stream event before writing `lastDailyChat`.
- **Web conversation lifecycle:** every turn releases its conversation in a
  `finally` (stop on success, stop+delete on failure). A process-local
  registry lets another thread reclaim a conversation whose worker is stuck
  in socket I/O (older than two turn caps); on startup the task also sweeps
  active gateway-owned conversations older than 30 minutes left by a previous
  process. Hitting the 10-active-conversation cap (429/10105) still prunes the
  oldest gateway-owned conversations first and never touches user-authored
  ones.
- **Daily activity execution bound:** the channel runs each account's activity
  in a worker and abandons it after the account budget plus 60s, reclaiming
  its web conversations; abandoned workers are capped at 8. The dailychat task
  declares `startup`, so the scheduler enqueues it once after the startup
  keepalive sweep; the account-level already-done gate prevents duplicates.
- **Model tiers:** `modelTiers` from the product config gates PRO-only models;
  free accounts are neither listed nor selected for them once the map arrives.
  The same map drives the `entitlement` label in `/v1/models` and the panel list
  (one-way: "unavailable on free accounts"; absence means unknown, not usable).
  `models_only_available` (default off) hides models no account can serve in
  both `/v1/models` and the panel model list; readiness/cooldowns are excluded.
- **Membership tier:** the billing summary (`IsPaidUser`,
  `SubscriptionPackageName`, protected-price, trial) is refreshed alongside
  credits and kept on the account as `tier`; a failed or field-less summary
  keeps the previous conclusion instead of recording "free". The panel account
  row shows it as a capsule (package name; `Free` / `体验版` / paid name) whose
  tooltip is the read time, and nothing is drawn before the first summary.
- **Identity:** official CLI/VSCode fingerprints; `WB_CN_CHAT_UPSTREAM`
  override.
- **Keep local derivative behavior:** post-403 fallback keeps rotating,
  `parse_reset` time zone, 429 handling.
- **Keepalive:** renews when expiry is unknown and uses a lead of 48h
  (`WB_KEEPALIVE_LEAD_HOURS`), because the sweep runs once a day and a 2h lead
  missed most expiry times. A failed renewal does not penalize the account.
- **China-only gate:** only `deepseek-v4-pro*` and the explicit `minimax-m3` are
  CN-exclusive; the `minimax-` prefix is not, since the intl exit serves
  `minimax-m3.1-flash`.
- **Do not absorb upstream-only modules:** quota-window probe, update_request,
  pinned routes, balance-summary, auto_switch_products, consume_credit,
  Anthropic tool_result images, CN device-token parsing; the daily-chat random
  minute slots and due-window scheduler, key account allowlist, per-account
  tasksEnabled, identity-version overrides, the portable/external self-update
  installers, cross-realm fallback (default off), update backup/rollback and
  startup-check budget, and mobile dashboard layout changes.
  v1.7.33 fixes adopted locally: ordered daily-chat candidates plus budget,
  stuck-conversation reclaim/orphan sweep, dailychat startup catch-up and
  abandoned-worker bound (the window-probe restore remains excluded).
  v1.7.25-1.7.29 fixes adopted locally: identifier-safe phone redaction and
  assistant-scope identity cleanup.
- **Static catalog:** `wb-proxy/wb_catalog.py` is the superset.
- **Exclusions:** the upstream-only modules listed under "Do not absorb"
  plus AgentHub session/IPC modules; no bulk account operations.
