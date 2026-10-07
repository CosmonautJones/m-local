# Release ingress operations

The release gateway preserves the exact compiled-asset, photo and application
RPC allowlist. Public native `/user/register`, `/user/login`, graph, schema,
documentation and administration routes are refused before forwarding. Native
passwordless provisioning remains an internal server operation. The raw backend
must bind to loopback and must never receive public traffic directly.

## Serialization contract and evidence boundary

`MLOCAL_DEPLOYMENT_TOPOLOGY=single-instance-serialized` opts into one upstream
HTTP request at a time in one gateway process. That includes assets, authenticated
RPCs, internal `/healthz/ready`, the startup `home_feed` check and periodic guest
`current_session` readiness. The lane is retained
until the entire upstream response has ended; receiving headers is insufficient.
A downstream client disconnect removes waiting work, but an active upstream
request is drained through completion before another request starts.

The actual hosted entry always enables catalog admission. On listening, it
checks native metadata and runs exactly one anonymous `home_feed` through this
lane with the existing ordinary 30-second request deadline and full feed DTO
validation. Public RPCs and readiness return 503 until that completes. A failed
catalog check never retries or opens admission; restart requires the coordinated
operator procedure. Assets can be served through the same lane while starting.
Periodic health then checks native metadata plus the exact nine-field guest
`current_session` response under the original overall five-second limit, without
repeating catalog traversal or forwarding a caller's credentials.
The native DTO may include exactly four official string metadata fields:
`_jac_type`, `_jac_id`, `_jac_archetype` and `_jac_type_id`. All nine guest fields
must retain their exact values/types; unknown, partial or malformed metadata is
refused. Health returns only `{ "ready": true }` or `{ "ready": false }`.

A disposable warm database outage on official Jac 0.37.23 showed native metadata
still returned ready while both session and catalog RPCs returned HTTP 500.
The session check detects that tested storage outage. It does not certify graph
schema completeness, every cached/runtime fault, transaction durability, provider
storage or hosted recovery; those separate acceptance gates remain mandatory.

The lane is process-local. Run exactly one gateway and one backend instance,
with no autoscaling, overlapping rolling replacement, direct backend ingress or
background/operator mutations while serving. `threads=1` alone is not the safety
mechanism. The coordinator must bind native simultaneous last-unit claim,
redemption, publication, restart and fault evidence to the exact official Jac
0.37.23 candidate. Node gateway fixtures do not establish durable native commits
or approve a launch topology by themselves.

An active deadline or incomplete upstream response closes the lane permanently
for that gateway process. All later application requests return 503 with
`Retry-After: 1`; `/healthz` returns 503 and only `{ "ready": false }`. There is no
public or private reset operation. An HTTP/socket abort does not establish that
Jac stopped finalizing an already accepted write. A complete upstream 5xx is
reported and releases the lane normally; it is not automatically replayed.

Downstream delivery is bounded independently from native completion. A paused
browser cannot prevent upstream draining: at most 8 MiB per response and 16 MiB
across all clients may wait for delivery. Overflow or a delivery deadline closes
only that client response while draining continues. It does not latch the
application lane closed. Incomplete upstream execution retains the fail-closed
policy above. Paused 1/2/16 MiB assets and aggregate budget regression checks
passed in the corrected 40-check focused suite.

After a closed-lane incident, the release operator must:

1. Remove public traffic and stop both gateway and backend, confirming neither
   backend nor serving child remains. Do not restart only the gateway.
2. Preserve private state and incident timestamps. Reconcile the uncertain
   operation against durable state before retrying it, preserving publication
   keys, saved claims, identity roots and redemption outcomes.
3. Restart the selected exact candidate with the same durable storage and key
   material using the hosting package's coordinated commands.
4. Check meaningful gateway readiness, existing-user sign-in and the relevant
   operation's durable result before restoring traffic.

## Bounds and configuration

| Setting | Default | Meaning |
|---|---:|---|
| `deploymentTopology` / `MLOCAL_DEPLOYMENT_TOPOLOGY` | empty in development | Select `single-instance-serialized` for the proposed release topology. Unknown values refuse construction. Production startup must require the selected topology. |
| `maxQueuedRequests` | 32 | At most 32 fully received requests wait; constructor accepts 0–128. Saturation returns 503 without forwarding. |
| `queueWaitMs` | 10000 | A waiting request expires without forwarding; constructor accepts 1–30000 ms. |
| Ordinary upstream deadline | 30000 ms | Absolute full-response deadline. Timeout closes serialization. |
| Website import deadline | 75000 ms | Existing bounded website import budget; other requests may expire while waiting. |
| `readinessDeadlineMs` | 5000 ms | Shared public readiness deadline. Expiry cancels waiting probes; an active probe remains serialized until it finishes or its lane deadline closes the lane. |
| `maxConnections` | 96 | Maximum accepted gateway sockets, including keepalive and partially received bodies; constructor accepts 1–256. |
| Header / request receipt | 10000 / 15000 ms | Bounds incomplete header/body receipt. RPC bodies also have a 15-second receipt deadline. |
| Ordinary / photo RPC body | 65536 / 1400000 bytes | Declared and chunked oversized bodies are rejected before joining the lane or reaching the backend. |
| Response / shared delivery budget | 8 / 16 MiB | Bounds slow downstream delivery; overflow closes that client and continues upstream draining. |
| `MLOCAL_INGRESS_EVENT_LOG` | unset in development | `stderr` selects structured redacted JSON failure events. The production launcher validates this choice. |
| `secureProductionIngress` | false | The hosting launcher sets true only after validating the intended HTTPS edge; it enables HSTS. Caller forwarding headers cannot enable it. |

The internal `upstreamDeadlineMs` fixture override accepts at most 80000 ms. It
exists to exercise timeout safety and must not be used to widen production
budgets. These options are passed to `createShareProxy`; deployment configuration
and exact startup commands belong to the hosting package.

## Response and request policy

The gateway reapplies policy after merging upstream headers, preventing upstream
responses from replacing it. All ordinary gateway responses use `nosniff`,
`strict-origin-when-cross-origin`, `camera=(self)` with microphone/geolocation
disabled, `no-store`, `X-Frame-Options: DENY` and CSP `frame-ancestors 'none'`.
Runtime `Server` and `X-Powered-By` headers are removed. HSTS is enabled only for
the verified secure production edge and does not use `includeSubDomains` or
preload on a shared hosting domain.

CSP permits same-origin scripts and connections. Jac's inline compiled bootstrap
and React Native Web's inline styling remain allowed; this is an explicit
compatibility concession, not a claim of nonce-based XSS protection. Local fonts,
Google font resources, HTTPS website photo previews, local saved photos,
data images and blob/camera previews remain usable. A real browser run through
the compiled gateway must confirm no required resource or changed student flow
is blocked before hosting acceptance.

Only a configured trusted edge may supply client identity for network limits.
Direct mode ignores caller-supplied Cloudflare/forwarding IP headers. Funnel
accepts one valid overwritten address only from its loopback daemon. Keep the
existing twelve-send/minute, thirty-send/hour shared-network limits and separate
backend per-email/challenge/global budgets.

## Monitoring and named responsibility

Travis is the release owner. Before a hosted rollout, he names the deployment
operator responsible for the platform log sink, retention and incident response,
and the backup operator responsible for the coordinated recovery receipt. Those
names and access are hosting approval gates; this package creates no external
service, account, email alert or spending commitment.

With `MLOCAL_INGRESS_EVENT_LOG=stderr`, failure events contain only a fixed event
kind/code, an allowlisted RPC name or fixed route category, HTTP status and UTC
timestamp. They omit IPs, emails, tokens, cookies, query strings, request bodies,
QR credentials and raw exceptions. `proxy.ingressStatus()` supplies fixed-size
failure counters and lane state to in-process operations tooling; no public
metrics endpoint is added. A failing log callback cannot stop gateway serving.

The operator configures the selected platform to retain these stderr events and
alert on `UPSTREAM_DEADLINE`, `UPSTREAM_FAILURE` or `SERIALIZATION_CLOSED` together
with readiness 503. Sustained `UPSTREAM_5XX` requires application investigation;
`QUEUE_FULL`/`QUEUE_DEADLINE` indicate the supported single-lane capacity has been
exceeded, and must not trigger unapproved autoscaling. `BODY_TOO_LARGE`,
`BODY_DEADLINE`, `ROUTE_DENIED` and `ONBOARDING_RATE_LIMITED` are bounded refusal
signals. `DELIVERY_LIMIT` and `DELIVERY_DEADLINE` close a client response while upstream draining continues; they do not justify restarting the backend. Investigate oversized assets/responses and slow clients. Test the chosen sink with disposable events and record operator
acknowledgement without sending real mail or exposing private accounts.

## Isolated checks

Run in WSL Bash from the candidate checkout:

```bash
node --test tests/tooling/release-ingress.test.mjs \
  tests/tooling/hosted-gateway.test.mjs tests/tooling/phone-share.test.mjs \
  tests/tooling/photo-ingress.test.mjs tests/tooling/onboarding-ingress.test.mjs
```

The initial failing-first run reproduced weak upstream header overrides and
overlap after response headers, including readiness bypass. The corrected run
passes 40 checks on isolated loopback HTTP servers: twenty-one release regressions
and nineteen retained hosted, onboarding, photo and sharing checks. The release
regressions cover full response completion, readiness serialization, saturation,
waiting expiry, queued/active client aborts, incomplete upstream failure, latched
timeouts, complete upstream errors, redacted events, security-header authority,
opt-in development behavior and chunked rejection. Native runtime and actual
browser evidence must be recorded separately against the combined candidate.
