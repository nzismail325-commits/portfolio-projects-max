# Trae (`trae`)

> Shared behavior: [../POLICY.md](../POLICY.md) §2-§3.

- **Prerequisite:** OAuth/PKCE or paste credentials.
- **Behavior:** catalog discovery always sends `x-uid`; limits only from official
  values (omit when absent); re-pull accounts/balance after login. Daily check-in
  runs at 09/21 and keys its local ledger by the UTC+8 business day (client
  rule, independent of host timezone). A ledger hit is verified against the
  official status when that status is queryable (code 1001 keeps the ledger-only
  fallback); a claim or "already signed" reply is recorded only after the status
  confirms `checked_in`, so a silent non-grant cannot be reported as checked in.
  `last_checkin` is written only for a confirmed/ledger-trusted result.
- **Errors:** 4001->404 and input-too-large->413, no penalty; 401 refresh-retry;
  11102 account x model negative cache; 1005 parks; 4008/6004 cool down;
  empty/no-content streams rotate.
- **Catalog:** filter placeholder/delisted entries; invisible legacy models are
  kept based on local tests.
- **Exclusions:** none channel-specific.
