# Qoder (`qoder`, `qoder_intl`)

> Shared behavior: [../POLICY.md](../POLICY.md) §2-§3.

- **Prerequisite:** local Qoder client + Node signer bridge (system Node or
  client Electron); per-request signatures, Encode=1/catalog-v6 decryption.
  Update `signer.cjs` when client obfuscation changes.
- **Behavior:** catalog-v6 (CN fallback, no Intl fabrication); machineId
  persisted; refreshToken rotation/pre-refresh; desktop import; OAuth;
  per-package quota; daily claim at 11/14. Login/import persist the userinfo
  identity (email/username when it looks like an email or phone) as
  `meta.loginAccount`; older accounts without it are backfilled once by the
  panel from `/api/v1/userinfo`, with a 24h retry floor. Campaign calls mirror
  the installed client (UA plus `Cosy-Version` from the signer bridge); only
  `CLAIM_BENEFIT` campaigns inside their `startAt`/`endAt` window are claimed,
  and check-in is recorded only when a current-window `CREDITS` campaign is
  claimed or already `CLAIMED` — an empty campaign list or a historical claim
  reports "no claimable campaign" instead of writing `last_checkin`. The
  scheduled run re-checks upstream every time (no local date skip), so a stale
  `last_checkin` cannot block a later claim in the same day. `VIEW_DETAILS`
  never reads as claimed today.
- **Errors:** 401 refresh-retry once then rotate; 402/code116 parks until 04:00
  next day; 429/code10605 uses the upstream-suggested duration (never guess);
  403/code101 and 400 no penalty; 5xx/connect rotates; in-stream errors follow
  the same semantics.
- **Exclusions:** `qoder_intl` static catalog, bulk account operations.
- **License:** `qoder_bridge/` keeps AgentHub copyright and MIT additional terms
  (non-commercial self-use only; no resale/bulk operations); see
  `integrations/qoder_bridge/NOTICE.md`.
