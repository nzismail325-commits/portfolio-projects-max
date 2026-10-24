# Agent Policy

> Shared project policy and channel index. Per-channel policy lives in
> `policy/<id>.md`; load only the channel you are changing. Exact model lists,
> endpoints, and error constants live in code and smoke tests; do not copy
> volatile values into this file.

## 1. Upstream decisions

- **workbuddy2api-hub** — primary upstream. `wb-proxy/` is derived from v1.4.3;
  `wb-proxy-max/` is fused to the current snapshot in `FACTS.md`. Sync future
  versions into max only.
- **AgentHub** — reference upstream. Trae/Qoder/ZCode/CodeArts/Loomy are
  adopted; each port is an independent implementation.
- **QoderFarm** — not integrated (evaluation snapshot). Do not import its code,
  license, or data without a separate decision.
- Snapshots keep only the latest; the sync order is in `AGENTS.md` §5.

## 2. Shared behavior

- **Chat streaming:** reopen the same request once before the first client byte;
  record egress success only after the stream is fully read. Interrupted streams
  are transient; a later successful retry does not cancel the earlier signal.
  Responses read-retry is not covered.
- **Network:** classify by errno/winerror; retry transient resets; local outage
  (DNS/NIC/route) does not penalize accounts; `ECONNREFUSED` is an egress/account
  fault. Private CA: `WB_CA_BUNDLE`/`SSL_CERT_FILE`.
- **Output:** one streaming reply carries exactly one chunk id (the gateway's
  own), so clients that key stream state by id never wait on a half that never
  ends; usage is a separate choices-less tail frame; interrupted streams
  estimate usage from emitted text.
- **Streaming keepalive:** Chat and Responses streams write an SSE comment
  frame after 15s of upstream silence, from a background thread that shares the
  write lock with normal frames (a pre-read check cannot cover a blocking read).
- **Reasoning-only Responses:** streaming emits `response.failed`; non-stream
  returns 502.
- **Privacy:** mask mainland-China 11-digit phone numbers in logs and panel
  payloads; never touch order IDs or long IDs. Identifier keys (`uid`, `id`,
  `accountId`, `machineId`, `sessionId`, `token`, ...) are returned verbatim:
  masking a uid makes the panel send back an id the pool does not know.
  `loginAccount` is also verbatim: it is the email/phone the operator copies to
  sign in, so masking it would break the copy action; every other field keeps
  the normal phone masking.
- **Account identity:** panel account rows show `loginAccount` (email/phone)
  instead of the nickname, falling back to nickname only when no identity is
  known; long values are ellipsized and can be copied. Sources are persisted
  account `meta`, per-channel token/profile resolvers, and for Qoder a
  throttled `/api/v1/userinfo` backfill when an older account has no identity.
- **Request cleanup:** neutralize 11-128 identity sentences in
  system/developer/assistant (user/tool untouched); normalize roles/tool
  declarations and repair tool-call pairing.
- **Model catalog:** `/v1/models` and the panel model list are full by default;
  `filter_models_by_key=true` filters by the current key's allowlist
  (unrestricted keys unaffected). `models_only_available=true` hides models no
  enabled account can serve in both surfaces (PRO-only models need a paid
  account). Entries may carry `entitlement`, derived one-way from the catalog
  tier map (`source=catalog`, `required=standard`, ingest time): it says
  "unavailable on free accounts" and never claims usability; no label means
  unknown.
- **Dispatch settings (`account_max_concurrent`, `affinity_stable_key_enabled`):**
  the per-account concurrency cap (0 = unlimited, 1-10) reserves a slot when an
  account is selected and returns it when the request ends, so a candidate
  abandoned during account rotation gives its slot back at once rather than
  holding it; saturated accounts are skipped in selection, a session bound to a
  saturated account spills to another account without losing its binding, and an
  all-saturated realm answers 429 naming the cap. The affinity switch (default
  off) derives the conversation key from the message head (system + first user,
  plus the first assistant reply once the conversation is past two messages) for
  clients that send no conversation id, so one conversation stays on one account
  and earns the account-level prompt cache; off = pure rotation, unchanged. The
  upstream hub derives that key unconditionally; here it sits behind the switch
  so an existing install keeps rotating until asked otherwise.
- **Settings card "Identity & Model Catalog":** global key filtering plus
  WorkBuddy `identity.private_data` (`auto/true/false`; true = private; explicit
  values override `X-Private-Data`; invalid -> 400).

## 3. Responses protocol

Aligned with primary upstream v1.5.0->v1.7.29; all chat channels share one
translation chain (zero adapter changes). Core files: `core/protocol.py`,
`streaming.py`, `proxy_api.py`, `tools_compat.py`.

- **Request/response:** roles/instructions/reasoning/function_call/
  custom_tool_call/orphan function_call_output/agent_message, additional_tools,
  namespace dedup, text.format (off by default), max_output_tokens catalog
  fallback; restore namespace/custom and echo tools/tool_choice/
  parallel_tool_calls.
- **Streaming/non-streaming:** created/in_progress first round only, reasoning
  summary, function/custom events, DSML fallback, web_search_call card,
  sequence_number, no premature completion; aggregation/usage semantics, length
  -> incomplete, drop half-written tool arguments, estimate missing usage,
  normalize empty finish_reason.
- **Local additions:** in-stream errors emit `response.failed` (upstream silently
  completes); non-stream in-stream errors return 502; abnormal termination
  emits a terminal `upstream_stream_error` frame (chat: data error object;
  Responses: `event: error`) and closes without `[DONE]` (upstream v1.7.20).
- **Not supported:** `previous_response_id` (400 per upstream), `store`,
  `background`, `conversation`, `include`, `prompt` templates, automatic
  `truncation`; `metadata` always `{}`; non-`length` stops are still completed;
  `WB_PRESERVE_REQUEST_CONTRACT` only preserves fields/data, not JSON Schema
  validation or `tool_choice` execution.

## 4. Channel policy

Per-channel prerequisites, behavior, hard constraints, exclusions, and license
notes live in one file per channel. Shared behavior is in §2-§3 and must not be
duplicated in channel files. `tools/agent_doc.py --check` enforces the required
labels and an 8 KB budget per file.

| Channel | Realms | Policy file | Scope |
|---|---|---|---|
| `workbuddy` | `intl`, `cn` | [policy/workbuddy.md](policy/workbuddy.md) | Primary upstream; CN check-in / Intl daily activity |
| `trae` | `trae` | [policy/trae.md](policy/trae.md) | OAuth/PKCE and catalog discovery |
| `qoder` | `qoder`, `qoder_intl` | [policy/qoder.md](policy/qoder.md) | Local signer bridge and per-package quota |
| `codearts` | `codearts` | [policy/codearts.md](policy/codearts.md) | OAuth + DPoP, HMAC signing, credits/check-in |
| `loomy` | `loomy` | [policy/loomy.md](policy/loomy.md) | SMS session, dual-header OpenAI gateway |
| `zcode` | `zcode` | [policy/zcode.md](policy/zcode.md) | Anthropic coding plan and dual credentials |

## 5. Enforcement notes

- **Channel isolation:** enforced by `tools/agent_doc.py --check` (no concrete
  channel imports outside `integrations/`); the rule itself is in `AGENTS.md` §1.
- **Policy freshness:** `tools/agent_doc.py --check` validates `FACTS.md`, update
  baselines against snapshots, this index, each channel policy file's required
  labels (`Prerequisite`, `Behavior`, `Exclusions`), the 8 KB size budget, and
  the smoke baseline. Orphan policy files are rejected.
- **Rules that matter beyond documentation** should become lint/tests/guards;
  prose alone is not enforcement.
