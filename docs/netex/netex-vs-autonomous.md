# Netex vs. Autonomous Network Automation

> **Netex is an assistant, not an autonomous agent. It will always ask before changing anything on your network.**

## The Fundamental Difference

Autonomous network automation platforms (Ansible, Terraform, Salt, custom scripts) execute predefined playbooks without human review at execution time. The operator writes the automation, reviews it during development, then lets it run unattended.

Netex takes the opposite approach: **every change is a conversation.** The operator describes intent in natural language, netex builds a specific plan, and the operator reviews and confirms before anything executes.

## Comparison

| Aspect | Autonomous Automation | Netex |
|---|---|---|
| **Execution model** | Run playbook, walk away | Three-phase conversation (resolve, plan, confirm) |
| **Change approval** | Implicit (approved when playbook was written) | Explicit (approved at execution time) |
| **Risk assessment** | Manual (operator must anticipate risks) | Automatic (OutageRiskAgent classifies every change) |
| **Security review** | Manual or separate tool | Built-in (NetworkSecurityAgent reviews every plan) |
| **Rollback** | Must be explicitly coded | Automatically derived and presented |
| **State management** | Declarative state files (Terraform) or imperative scripts | Queries live state, no state files |
| **Multi-vendor** | Separate modules per vendor | Unified plugin registry, abstract data model |
| **Operator skill** | Must know YAML/HCL/Python | Natural language |
| **Audit trail** | Playbook run logs | Conversation history with full plan and confirmation |
| **Error handling** | Script-level error handling | Workflow state machine with rollback on failure |

## When to Use Netex

Netex is the right choice when:

- **You are the operator.** You are directly managing the network and want intelligence and safety checks, not unattended automation.
- **Changes are infrequent.** Home networks, small businesses, and lab environments where changes happen weekly or monthly, not hourly.
- **Safety matters more than speed.** Production networks where an outage means losing your management session.
- **You want cross-vendor intelligence.** Your network spans multiple platforms (OPNsense + UniFi) and you want a unified view.
- **You want to learn.** Netex explains what it is doing and why, helping you understand your network.

## When to Use Autonomous Automation

Autonomous automation is the right choice when:

- **You have a dedicated NetOps team.** Multiple operators, change management process, CI/CD pipeline.
- **Changes are frequent and repetitive.** Hundreds of devices, same configuration deployed across many sites.
- **Speed is critical.** Provisioning must happen in seconds, not minutes of conversation.
- **You have a testing pipeline.** Playbooks are tested in staging before production.
- **You already know what you want.** The plan is already reviewed -- you just need execution.

## The Safety Model

### OutageRiskAgent

Before every write plan, the OutageRiskAgent assesses whether the proposed changes could sever your management session:

| Risk Tier | Meaning | What Happens |
|---|---|---|
| **CRITICAL** | Change directly modifies your session path | Netex requires out-of-band access confirmation |
| **HIGH** | Change is in the same subsystem; disruption possible | Netex warns and requires confirmation |
| **MEDIUM** | Indirect disruption possible (DNS, DHCP) | Netex notes the risk |
| **LOW** | No intersection with your session path | Normal confirmation |

### NetworkSecurityAgent

Every change plan is reviewed for security issues across seven categories:

1. VLAN isolation gaps
2. Overly broad firewall rules
3. Rule ordering risks
4. VPN split-tunnel exposure
5. Unencrypted VLANs for sensitive traffic
6. Management plane exposure
7. DNS security posture

### Write Safety Gate

Every write operation requires three steps:

1. **Environment variable:** `NETEX_WRITE_ENABLED=true` must be set
2. **Apply flag:** `--apply` must be passed
3. **Operator confirmation:** The operator must review and confirm the plan

This three-step gate ensures no changes happen accidentally, even if the AI model hallucinates a command.

## Coexistence

Netex and autonomous automation can coexist. Common pattern:

1. Use **netex** for interactive operations: troubleshooting, auditing, one-off changes, new site provisioning
2. Use **Ansible/Terraform** for repeatable infrastructure: multi-site deployments, CI/CD-driven configuration
3. Use **netex policy sync** to verify that autonomous changes match your intended policy

Netex reads live state -- it does not conflict with configuration management tools that manage the same devices.

---

> **Remember:** Netex is an assistant, not an autonomous agent. It will always ask before changing anything on your network. This is a deliberate design choice, not a limitation.
