# New Site Onboarding

> **Difficulty:** Advanced | **Time:** 45-60 minutes | **Risk:** Write operation

## Problem Statement

You are setting up a brand-new site with OPNsense and UniFi hardware. This workflow walks through the complete onboarding process from bare metal to a fully provisioned, segmented, and audited network.

## Prerequisites

- OPNsense installed on the gateway hardware with basic WAN connectivity
- UniFi controller running and the switch/APs adopted
- Both plugins installed, authenticated, and passing `--check`
- Write access enabled on all three plugins
- Physical access to the hardware (serial console or direct keyboard/monitor)

## Workflow

### Phase 1: Discovery and Assessment

#### Step 1: Verify Plugin Connectivity

```
"netex --check"
```

Confirms both vendor plugins are reachable and authenticated.

#### Step 2: Baseline Topology

```
"netex topology"
```

See the current state: default VLAN only, no segmentation, all devices on a flat network.

#### Step 3: Baseline Health

```
"netex health"
```

Confirm both systems are healthy before making changes. Address any firmware warnings first.

### Phase 2: Plan the Network

#### Step 4: Create the Manifest

Build your site manifest YAML based on your requirements. Start with the key questions:

- How many VLANs do you need? (Common: management, trusted, IoT, cameras, guest)
- Which VLANs can talk to which? (Access policy matrix)
- What WiFi SSIDs do you need? (Typically one per user-facing VLAN)
- What switch port profiles do you need? (Trunk for APs/switches, access for devices)

See the [Neffroad manifest](neffroad-provision.md) for a complete 7-VLAN example.

### Phase 3: Provision

#### Step 5: Dry-Run First

```
"netex network provision-site --manifest site.yaml --dry-run"
```

Review the full plan:
- Outage risk assessment (should be LOW for a new site)
- Security review (the NetworkSecurityAgent checks for isolation gaps)
- Step-by-step execution order
- Rollback plan

#### Step 6: Execute

```
"netex network provision-site --manifest site.yaml --apply"
```

Monitor the execution -- each step reports success/failure.

### Phase 4: Verify

#### Step 7: Policy Verification

```
"netex verify-policy --manifest site.yaml"
```

Run the full test suite:
- All VLANs exist on both layers
- DHCP is active
- Access policy rules are enforced
- WiFi SSIDs are bound correctly
- Port profiles are created

#### Step 8: Security Audit

```
"netex secure audit"
```

Full 10-domain security audit of the newly provisioned network.

#### Step 9: Final Health Check

```
"netex health"
```

Confirm everything is healthy after provisioning.

### Phase 5: Document

Save your manifest YAML in version control. It is now the source of truth for your network configuration. Future changes should be made by updating the manifest and re-running `provision-site` or targeted commands.

## Onboarding Checklist

| Step | Command | Expected Result |
|---|---|---|
| Plugin check | `netex --check` | Both plugins discovered |
| Baseline topology | `netex topology` | Flat network, default VLAN |
| Baseline health | `netex health` | No critical findings |
| Dry-run provision | `provision-site --dry-run` | Plan reviewed, risk LOW |
| Execute provision | `provision-site --apply` | All steps completed |
| Verify policy | `verify-policy --manifest` | All tests PASS |
| Security audit | `secure audit` | No critical findings |
| Final health | `netex health` | All systems healthy |

## Working Safely

This is a full site provisioning operation. Since it is a new site with no existing traffic, the risk is relatively low -- but you should still have physical access to the hardware in case something goes wrong.

> **Required safety notice:** Network changes can result in outages that disconnect you from your ability to correct them. Never make changes to a network you cannot reach through an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN on a different physical interface, or physical access). Netex will assess this risk for you, but it cannot guarantee your recovery path -- only you can verify that.

## Related Workflows

- [Neffroad Provisioning](neffroad-provision.md)
- [Guest WiFi Isolation](guest-wifi-isolation.md)
- [Post-Change Policy Sync](post-change-policy-sync.md)
- [Unified Health Check](unified-health.md)
