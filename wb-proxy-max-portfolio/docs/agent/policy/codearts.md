# CodeArts (`codearts`)

> Shared behavior: [../POLICY.md](../POLICY.md) §2-§3.

- **Prerequisite:** Huawei Cloud account; OAuth + PKCE (**portal requires the
  challenge method name `SHA-256`, not `S256`**) + DPoP. The credential is one
  block: temporary AK/SK/STS + refresh token + DPoP private key + PKCE verifier.
  Losing any part makes renewal impossible; re-login is required.
- **Behavior:** SDK-HMAC-SHA256 on every API call (signed headers include
  `X-Security-Token`, `X-Domain-Id`, and the three model headers); canonical URI
  keeps a trailing slash. Credentials refresh 15 minutes before expiry; the
  refresh token rotates, single-flight per account. Each account has 3 upstream
  sessions (local gate returns 409 when full, never cools the account).
  `stream: true` is forced upstream; empty answers count as failures so the
  account rotation chain still triggers; in-stream error envelopes inside HTTP
  200 are treated as failures (insufficient quota -> 403, rate limit -> 429).
- **Catalog:** merge agent / builtin / benefit sources. The agent list
  (`Agent-Type: AgentCenter`) returns top-level `agents` with inline `models`
  (detail is only a fallback); builtin uses `Agent-Type: PromptCenter` and
  returns top-level `builtinModels`. Case-insensitive IDs resolve to the
  upstream true name; trial accounts with no models are not backfilled with
  fabricated entries. Each model's `credit` array carries the official
  multiplier in `ratio_display` (fallback `before_display_ratio`); the panel's
  `credits` field mirrors the first entry, matching the desktop client's
  `getCreditRatio`. Models with an empty `credit` array legitimately show no
  rate. Benefit models send `maas_type: benefit`.
- **Balance:** credit packages use the credit metrics from
  `/snap-manager/v1/statistics/plugin` (`usageTotalPackageCredit`,
  `usageBasicPackageCredit`, `usageOnDemandPackageCredit`,
  `usageBonusPackageCredit`) with `package_credit_amount|used|remain`.
  `usageTokenChatMessages.package_token_amount` is a sentinel `1` on credit
  packages and must never be shown as the balance; it is only a fallback for
  token packages. The welfare token pool is `/api/v1/user/tokens/balance` on
  `opengw.developer.huaweicloud.com` (`CODEARTS_BENEFIT_BASE` overrides),
  wrapped as `{error_code, result}` with `used_amount` / `total_quota`; a
  non-`0000` envelope (HTTP 200) means the pool is unavailable. Credit and
  token-pool units are never summed.
- **Daily check-in:** the desktop client activity center is the authority:
  `GET /v1/ops/delivery?channel=DESKTOP` -> `data.items` with `campaignId`,
  `type` (`USER_LOGIN` daily, `NEW_USER_REGISTER` one-time), `status`
  (`CLAIMED` / `CONFIRMED` / `CONSUMED` all mean already credited),
  `claimable`, and `benefitAmount`. The old `/api/v1/welfare/*` family is a
  different service and returns 404. Claim is `POST /v1/ops/claim` with
  `{campaignId, idempotentKey, channel:"DESKTOP"}`; confirm is
  `POST /v1/ops/confirm` with **both** `campaignId` and `userBenefitId`
  (sending only `userBenefitId`, as the official client does, returns
  `campaignId : 参数无效`). Confirm is best-effort: the claim already credits
  the account and the list may stay `CLAIMED`. Success is verified by
  re-reading the list for the campaign IDs claimed in this run. Auto check-in
  only touches `USER_LOGIN` and `NEW_USER_REGISTER`; invite/student campaigns
  stay manual. Upstream status is the authority for "already signed today";
  the local ledger only throttles writes (>=60 s apart, max 12/day). Claimed
  rewards are package credits and do not top up the welfare token pool. The
  panel labels the action 签到 (not 领取福利).
- **Login:** the current official extension uses the portal route
  `/portal/authorize` (the old `/login` route returns 404) with `client_id`,
  `port`, `code_challenge`, `code_challenge_method=SHA-256`, a local
  `ticket_id`, and `auth_callback_url`. The loopback callback is an ephemeral
  `127.0.0.1` port at `/oauth/callback`; the portal's first callback
  (`secret` + `redirect`) must be answered with a 307 to a trusted
  `huaweicloud.com` host. The portal returns its own `state` (the official
  extension ignores it); trust comes from the ephemeral loopback port plus the
  PKCE verifier, so do not reject a mismatched `state`. The token response has
  `refresh_token` at the top level, next to the nested `credentials`; read both
  places. Paste callback remains the fallback when the loopback callback cannot
  be reached.
- **License:** behavior ported from AgentHub v1.82.2 `proxy/codearts/*`
  (Copyright (c) 2026 沐晖 / HUIdada1, MIT plus additional terms: non-commercial
  self-use only). v1.82.2 is the last AgentHub release that ships the reverse
  proxy; v1.83+ removed API forwarding, so the 1.82.2 snapshot remains the
  protocol reference. This gateway ships an independent Python implementation;
  the upstream notice stays with the snapshot.
- **Exclusions:** AgentHub-specific session store, Electron IPC handlers, and
  welfare preview UI; no bulk account operations.
