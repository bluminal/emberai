# Unbound DNS Endpoint Migration (OPNsense 26.x)

**Severity:** critical
**Triggers:** dns, unbound, host override, dns override, domain override, dns forwarder, searchHost, addHost, searchForward

## Summary

OPNsense 26.x moved all Unbound DNS host and domain override endpoints from individual controllers to the unified `settings` controller. Using the old endpoints returns 404.

## Endpoint Changes

| Operation | Pre-26.x Endpoint | 26.x Endpoint |
|-----------|-------------------|---------------|
| List host overrides | `GET /api/unbound/host/searchHost` | `GET /api/unbound/settings/searchHostOverride` |
| Get one host override | `GET /api/unbound/host/getHost/{uuid}` | `GET /api/unbound/settings/getHostOverride/{uuid}` |
| Add host override | `POST /api/unbound/host/addHost` | `POST /api/unbound/settings/addHostOverride` |
| List domain overrides | `GET /api/unbound/forward/searchForward` | `GET /api/unbound/settings/searchDomainOverride` |
| Reconfigure | `POST /api/unbound/service/reconfigure` | **Unchanged** |
| DNS lookup | `GET /api/unbound/diagnostics/lookup/{hostname}` | **Removed in 26.1.5** — see below |

## Write Payload Shape (verified on OPNsense 26.1.5)

The payload key is **`host`**, NOT `host_override`. Earlier guidance in this file
said `host_override`; that returns `{"result":"failed"}` (HTTP 200, no validation
detail) on 26.1.5. Updated 2026-05-18 after live test on the cybertron lab gateway:

```python
# 26.x (verified 26.1.5)
data = {
    "host": {
        "enabled":     "1",
        "hostname":    "nas",
        "domain":      "home.local",
        "rr":          "A",            # selector key — "A" | "AAAA" | "MX" | "TXT"
        "server":      "10.0.0.1",     # the value the record resolves to
        "description": "optional",
    }
}
```

Minimum required fields observed: `hostname`, `domain`, `rr`, `server`. Sending
the alternate key `host_override` (or form-encoded `host_override[…]`) silently
fails with `{"result":"failed"}`.

Successful response shape:
```json
{"result":"saved","uuid":"82df6e75-c7b6-4eb5-9950-91ec88ce2e6e"}
```

## Response Field Addition

26.x responses include an `enabled` field (`"1"` or `"0"`) on each host override row.

## DNS Diagnostic Lookup

The `unbound/diagnostics/lookup/{hostname}` and
`diagnostics/dns/dns_lookup/{hostname}` endpoints both return
`{"errorMessage":"Endpoint not found"}` on 26.1.5. Use OS-level `dig`/`drill`
directly against the OPNsense IP as the verification step instead:

```bash
dig +short <hostname> @<opnsense_host_ip>
```

If a dedicated API replacement is found in a later release, update this file.

## Confirmed Working (OPNsense 26.1.5, cybertron lab gateway)

- `GET  /api/unbound/settings/searchHostOverride` with `?rowCount=-1&current=1`
- `GET  /api/unbound/settings/getHostOverride/{uuid}`
- `POST /api/unbound/settings/addHostOverride` with the `host` payload above
- `GET  /api/unbound/settings/searchDomainOverride` with `?rowCount=-1&current=1`
- `POST /api/unbound/service/reconfigure`

## Known broken on 26.1.5

- `POST /api/unbound/settings/addHostOverride` with the `host_override` payload
  key → `{"result":"failed"}` (HTTP 200; no error body, silent validation reject)
- `GET  /api/unbound/diagnostics/lookup/{hostname}` → Endpoint not found
- `GET  /api/diagnostics/dns/dns_lookup/{hostname}` → Endpoint not found
