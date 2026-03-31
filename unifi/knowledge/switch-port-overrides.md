# UniFi Switch Port Overrides — Destructive PUT Warning

**Severity:** critical
**Triggers:** port override, port profile, poe, switch port, port config, port_overrides, rest/device

## Problem

The UniFi Controller REST API endpoint `PUT /api/s/{site}/rest/device/{id}` with a `port_overrides` array **replaces the entire port override list**, not just the ports specified. If you send a PUT with only one port in the array, all other port overrides (VLAN assignments, PoE settings, port profiles, link aggregation groups) are deleted.

This causes:
- All switch ports to revert to "Default" profile
- VLAN trunk configurations to be wiped
- Link aggregation (LAG) groups to be broken
- PoE settings to revert to defaults
- **Network-wide outage** if trunk ports to other switches or the gateway lose their VLAN configuration

## Correct Approach

**Always read-modify-write.** Before updating any port override:

1. **GET** the full device state: `GET /api/s/{site}/stat/device` or `GET /api/s/{site}/rest/device/{id}`
2. **Extract** the existing `port_overrides` array from the response
3. **Find** the specific port you want to modify in the array
4. **Update** only the fields you need on that port entry (or append a new entry if the port has no override)
5. **PUT** the complete `port_overrides` array back with ALL ports included

### Example — Enabling PoE on Port 4

```python
# WRONG — destroys all other port overrides
await client.put(f"/rest/device/{device_id}", data={
    "port_overrides": [{"port_idx": 4, "poe_mode": "auto"}]
})

# CORRECT — preserves all existing overrides
device = await client.get(f"/rest/device/{device_id}")
overrides = device.get("port_overrides", [])

# Find and update port 4, or add it
found = False
for override in overrides:
    if override.get("port_idx") == 4:
        override["poe_mode"] = "auto"
        found = True
        break
if not found:
    overrides.append({"port_idx": 4, "poe_mode": "auto"})

await client.put(f"/rest/device/{device_id}", data={
    "port_overrides": overrides
})
```

## Additional Safety Measures

- Before writing port overrides, log the current override count and a summary of what will change
- After writing, verify the override count matches expectations
- Never send a `port_overrides` array with fewer entries than what was read (unless intentionally removing overrides with operator confirmation)
- Link aggregation (LAG) groups are defined in port overrides — losing them breaks inter-switch connectivity
- Treat port override changes as **high outage risk** — they affect the physical network fabric

## Applies To

- All UniFi switches (USW, USW-Pro, USW-Lite, USW-Flex, USW-Enterprise)
- All UniFi Controller versions (tested on Network Application 9.x)
- Both Local Gateway API and Cloud V1 API
