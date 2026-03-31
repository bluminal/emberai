# Netex Plugin Knowledge Base

Before making changes in a topic area, read any entries whose triggers match your current task. Entries marked **critical** must be read before proceeding.

| Triggers | Severity | File | Summary |
|----------|----------|------|---------|
| port override, switch config, device config, PUT, update device, write operation, bulk update, array replacement | critical | [destructive-api-patterns.md](destructive-api-patterns.md) | Several vendor APIs use PUT endpoints that replace entire config arrays. Always read-modify-write. A partial PUT can cause network-wide outages by wiping switch port profiles, VLAN assignments, and link aggregation groups. |
