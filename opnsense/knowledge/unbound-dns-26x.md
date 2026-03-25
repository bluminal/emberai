# Unbound DNS Endpoint Migration (OPNsense 26.x)

**Severity:** critical
**Triggers:** dns, unbound, host override, dns override, domain override, dns forwarder, searchHost, addHost, searchForward

## Summary

OPNsense 26.x moved all Unbound DNS host and domain override endpoints from individual controllers to the unified `settings` controller. Using the old endpoints returns 404.

## Endpoint Changes

| Operation | Pre-26.x Endpoint | 26.x Endpoint |
|-----------|-------------------|---------------|
| List host overrides | `GET /api/unbound/host/searchHost` | `GET /api/unbound/settings/searchHostOverride` |
| Add host override | `POST /api/unbound/host/addHost` | `POST /api/unbound/settings/addHostOverride` |
| List domain overrides | `GET /api/unbound/forward/searchForward` | `GET /api/unbound/settings/searchDomainOverride` |
| Reconfigure | `POST /api/unbound/service/reconfigure` | **Unchanged** |
| DNS lookup | `GET /api/unbound/diagnostics/lookup/{hostname}` | **Unchanged** |

## Write Payload Change

The write payload key changed from `host` to `host_override`:

```python
# Pre-26.x
data = {"host": {"hostname": "nas", "domain": "home.local", "server": "10.0.0.1"}}

# 26.x
data = {"host_override": {"hostname": "nas", "domain": "home.local", "server": "10.0.0.1", "enabled": "1"}}
```

## Response Field Addition

26.x responses include an `enabled` field (`"1"` or `"0"`) on each host override row.

## Confirmed Working (OPNsense 26.1.4, SG-4860)

- `/api/unbound/settings/searchHostOverride` with `rowCount=-1&current=1`
- `/api/unbound/settings/addHostOverride` with `host_override` payload
- `/api/unbound/settings/searchDomainOverride` with `rowCount=-1&current=1`
- `/api/unbound/service/reconfigure`
- `/api/unbound/diagnostics/lookup/{hostname}`
