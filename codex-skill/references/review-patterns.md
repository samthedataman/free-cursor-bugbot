# Repo Bugbot Review Patterns

Use these as high-priority checks when a PR touches matching code.

## Public Client Trust Boundaries

- `VITE_*` values are public bundle values, not secrets or authorization controls.
- URL query params such as `checkout=success`, `demo=...`, or `bypass=...` are untrusted.
- Stripe, Twilio, CRM writes, email/SMS sends, and provisioning must be authorized server-side.

## Idempotency

- Phone number provisioning, CRM writebacks, outbound campaign sends, billing updates, and document signing completions must tolerate retries and refreshes.
- React state is not an idempotency boundary after redirects, page reloads, or worker restarts.
- Prefer backend idempotency keys, existing-resource lookups, and ledger tables.

## Reachability

- New components are not product functionality until imported and mounted by a route or parent component.
- New service methods require both frontend call sites and backend routes.
- New public pages require route registration and build/link coverage.

## Fallbacks

- Iframe `onLoad` alone does not mean success; it can load error HTML.
- Fallbacks should handle 401/403/404/5xx, CSP/frame blocking, timeouts, and blank/error documents.
- Public signer/document flows need mobile and desktop rendering paths.

## Artifact Access

- If a workflow saves a generated asset, verify the download/public endpoint allows that asset type.
- Check signed documents, voicemail notes, CRM notes, recordings, and generated PDFs.

## Render / Env

- `render.yaml` changes affect production. Check service names, worker memory, env var placement, public vs secret vars, and deployment order.
- Do not put secret bypass codes or billing gates in frontend env vars.
