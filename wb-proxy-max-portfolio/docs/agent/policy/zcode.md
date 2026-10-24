# ZCode (`zcode`)

> Shared behavior: [../POLICY.md](../POLICY.md) §2-§3.

- **Prerequisite:** client login then import, or OAuth CLI/deep link; egress
  proxy required (direct z.ai is TLS-hijacked in CN).
- **Behavior:** Anthropic upstream; coding-plan first, 402 falls back to
  start-plan; official system prefix; dual credentials/deviceMid; model, quota,
  probe, proxy slots.
- **Hard constraints:** coding-plan keys are UID-scoped; never mix header sets;
  control plane requires `X-Device-Mid` (400 if missing); zcodejwt has no
  exp/refresh; `enc:v1` uses `auth/atrest`; portability via `ZCODE_V2_DIR`/
  `ZCODE_CREDENTIAL_SECRET`/`ZCODE_BUNDLE_PATH`.
- **No daily claim:** the channel declares no `checkin` or `scheduler`
  capability, exposes no claim button in the panel, and registers no automatic
  claim task. Do not reintroduce `billing/preview`, `billing/claim`,
  `client/configs`, or campaign version gating without a new policy decision.
- **Exclusions:** local client account switching/credential write-back,
  `adapter-zcode.cjs` usage SQLite.
