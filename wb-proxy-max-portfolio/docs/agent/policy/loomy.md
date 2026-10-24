# Loomy (`loomy`)

> Shared behavior: [../POLICY.md](../POLICY.md) §2-§3.

- **Prerequisite:** iFlytek Loomy account with a mainland-China mobile number.
  Login is two SMS steps: send code (returns `msgid`) -> submit phone + code +
  the same `msgid`. Both calls are HMAC-SHA1 signed on the account domain with
  the client-embedded key pair (a client fingerprint, not a user credential;
  environment-overridable).
- **Session:** the client asks for a 14-day session and the upstream has no
  renewal endpoint. Expiry is a re-login, never a refresh; the account view says
  so explicitly. There is no desktop-import or paste-callback path. Login stores
  the normalized full phone as `meta.loginAccount` so the panel can show and
  copy the login account; `phoneTail` remains the masked display value.
- **Behavior:** the integration gateway is OpenAI-compatible.
  `/api/v1/models` provides the catalog and `/chat/completions` serves SSE
  chat; upstream errors are translated to gateway errors and account state.
- **Catalog:** `GET /api/v1/models` with `token` only. Both a bare array and
  `{data: [...]}` are accepted. The live 0.9.39 catalog carries `protocol`,
  `type`, `name`, `context_length`, `max_output_tokens`, and `capabilities`
  (reasoning, vision, function_calling, input/output modalities); it has no
  top-level `reasoning`, `attachment`, or `limit`. Mapping accepts the client's
  top-level fields and this real shape: `displayName` before `name`;
  `limit.context` over `context_length`/`contextWindow`; `limit.input` over
  `input_token_limit`/`max_input_tokens`; `limit.output` over
  `max_output_tokens`/`max_completion_tokens`; reasoning from
  `reasoning`/`supports_reasoning`/`capabilities.reasoning`; tools from
  `tool_call`/`capabilities.function_calling`; images from `attachment`,
  `modalities.input` (or `capabilities.input_modalities`),
  `capabilities.vision`, and `supports_image_in`/`supports_video_in`.
  `spark-x` keeps the client's `262144` context override even though the
  gateway advertises `1048576`; entries are de-duplicated by id. Every live
  text model advertises `reasoning_efforts` `none/low/medium/high/xhigh` with
  default `low`; the 0.9.39 client ignores that field and hardcodes its own
  `low/medium/high` variants (UI labels 低/中/高, default medium). The proxy
  exposes `supports_reasoning` and passes `reasoning_effort` through rather than
  imposing the client's three-level menu.
- **Protocols and types:** only OpenAI-chat models usable through
  `/chat/completions` are exposed. Entries whose `protocol` resolves to
  `anthropic`/`anthropic_messages` are filtered because this gateway serves only
  the OpenAI endpoint; missing or invalid protocol is treated as OpenAI, like
  the client. `type: "image"` entries and entries whose
  `capabilities.output_modalities` excludes text are filtered because there is
  no image-generation endpoint. No static model fallback: a failed catalog
  fetch keeps the old list and reports failure instead of inventing names.
- **Headers:** catalog, points and first-login calls use `token` only, matching
  the client's `authMode: 'token'` and `PointsService`. Chat also carries
  `Authorization: Bearer` plus `traceparent`, `loomy-version`, `ChatId`,
  `MsgId`, `TurnId`, `InvokeOrigin: user`, and
  `X-Loomy-Request-Purpose: chat.message`. `loomy-version` follows the desktop
  app version (`LOOMY_APP_VERSION`, default `0.9.39`), not the fixed login-base
  `1.0.0`. Missing `traceparent` makes upstream chat hang until timeout.
- **Images:** the 0.9.39 package contains zero occurrences of `image_base64`;
  its vision path sends `image_url` data URLs. A live A/B test on
  DeepSeek-V4.1-Flash confirmed that standard `image_url` answered a two-color
  image correctly using 1 daily point, while the AgentHub `<image_base64>`
  rewrite spent 512 reasoning tokens without producing an answer (2 points).
  The rewrite was removed; the final `open_stream` path then answered the same
  image correctly with `finish=stop` for 1 daily point. Images pass through
  unchanged.
- **Balance:** `GET /api/v2/points/records` with `pageNo=1`, `pageSize=1`,
  `direction=debit`, `granularity=chat`, `token` only. Read the response
  summary from `data` or `data.data`: `balance` (permanent points) and
  `dailyBalance` (daily gift points); `dailyLimitPoints`/`dailyRemainingPoints`
  are optional. Both wallets are displayed and accounted separately. The
  client's points-detail page uses V2; its lightweight balance helper uses V1
  (`/api/v1/points/records?pageNo=1&pageSize=1&recordType=all`). A live session
  confirmed both return HTTP 200 `code=000000` with the same
  `balance`/`dailyBalance` summary; personal accounts did not include the two
  daily-limit fields. Live image calls were deducted from the daily wallet
  (5000 -> 4996) while the permanent wallet stayed at 5000.
- **Daily welfare:** `POST /api/v1/points/first-login` with `{}` and `token`
  only. The client calls it after every successful SMS/WeChat login. AgentHub's
  reverse-engineering says the server refreshes the daily 5000 gift allowance
  once per day and stays idempotent on repeat calls (no separate check-in API
  exists). On 2026-10-22 a first call returned `code=000000` with
  `dailyBalance=5000`; a same-day repeat also returned success and reported the
  current 4997 balance without resetting it, confirming the per-day idempotent
  behavior. Login triggers it so a fresh session starts with the refresh, and
  the scheduler re-runs it at 07/12 without a local "already refreshed today"
  date gate (the endpoint is idempotent); a successful call writes
  `last_checkin`.
- **Errors:** a real invalid session returns HTTP 200 JSON
  `{code: "100002", desc: "登录已失效"}`, not HTTP 401; the account domain also
  uses `020002`. Both mark the session expired regardless of transport status.
  HTTP 429 is surfaced as 429 with account cooldown; an empty stream, or one
  containing only `[DONE]`/role frames, is surfaced as a 502 failure rather than
  a fake success.
- **Verification status:** client-code facts verified against 0.9.39: signature
  path escaping, login envelope, header sets, catalog fields/protocol handling,
  points summary fields, and the `100002` semantics. A live session (2026-10-22)
  confirmed: SMS login; the catalog shape above (13 raw entries, 3 image-only
  filtered); V1/V2 balance summaries (5000 permanent + 5000 daily); a
  `spark-x` chat stream that finished with `stop`, returned content, and
  reported `points_consumed: 0`; first-login and same-day repeat behavior; and a
  DeepSeek image A/B test that led to removing the `<image_base64>` rewrite. An
  invalid token returns HTTP 200 `code=100002` on the catalog/points/chat
  routes. Real 429 and truly empty streams have not been induced (the fake
  upstream covers those adapter paths). One early `reasoning_effort: "none"`
  request timed out, but a retry completed in 3.8s, so the timeout is treated as
  transient.
- **License:** behavior ported from AgentHub v1.82.2 `proxy/loomy/*` (last
  gateway-bearing AgentHub release; v1.83+ removed API forwarding)
  (Copyright (c) 2026 沐晖 / HUIdada1, MIT plus additional terms: non-commercial
  self-use only). This gateway ships an independent Python implementation; the
  upstream notice stays with the snapshot.
- **Exclusions:** desktop credential import, token renewal, static catalog
  fallback, and Electron IPC/UI.
