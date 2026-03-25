# OPNsense Plugin Knowledge Base

Before making changes in a topic area, read any entries whose triggers match your current task. Entries marked **critical** must be read before proceeding.

| Triggers | Severity | File | Summary |
|----------|----------|------|---------|
| gateway, failover, multi-wan, policy routing, gateway group, wan2 | critical | [multi-wan.md](multi-wan.md) | Multi-WAN gateway groups require firewall advanced settings and gateway monitoring to work. Missing settings cause DNS outages on WAN failure. |
| dns, unbound, host override, dns override, domain override, dns forwarder, searchHost, addHost, searchForward | critical | [unbound-dns-26x.md](unbound-dns-26x.md) | OPNsense 26.x moved Unbound DNS endpoints from host/forward controllers to settings controller. Old endpoints return 404. |
