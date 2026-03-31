# UniFi Plugin Knowledge Base

Before making changes in a topic area, read any entries whose triggers match your current task. Entries marked **critical** must be read before proceeding.

| Triggers | Severity | File | Summary |
|----------|----------|------|---------|
| port override, port profile, poe, switch port, port config, port_overrides, rest/device, vlan assignment, link aggregation, LAG | critical | [switch-port-overrides.md](switch-port-overrides.md) | PUT to /rest/device with port_overrides REPLACES the entire array. Always read-modify-write. A bare PUT with one port wipes all other port configs causing network-wide outage. |
