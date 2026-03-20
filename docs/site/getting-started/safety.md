# Safety & Human Supervision

!!! warning "Netex is an assistant, not an autonomous agent"
    Netex is an assistant, not an autonomous agent. It will always ask before
    changing anything on your network. Every write operation requires explicit
    operator confirmation.

Netex is explicitly designed as an **assistant**, not an autonomous agent. This is a deliberate architectural decision driven by the blast radius of network changes: a misconfigured firewall rule or VLAN reconfiguration can disconnect the operator from the very system they are trying to manage.

## Why This Matters

Unlike code changes that can be reverted with `git checkout`, network changes can sever the connection you need to undo them. Consider:

- A bad firewall rule can lock you out of the management interface
- A VLAN reconfiguration can move your session to an unreachable subnet
- A routing change can black-hole the path between you and the controller

Netex is built around this reality. It will never make a network change without your explicit approval.

## The Three-Phase Confirmation Model

Netex does not ask for confirmation before every individual API call. Instead, it follows a structured three-phase process:

### Phase 1: Gather and Resolve Assumptions

Before building a change plan, Netex identifies genuine ambiguities — values that cannot be determined from the API. It asks only questions that would change the plan if answered differently.

- Facts determinable from current system state are resolved via read-only API calls, not questions
- Questions are batched into a single prompt with clear implications: "If X, the plan will do A; if Y, it will do B"
- Standard defaults implied by the chosen command are not asked about

### Phase 2: Build and Present the Plan

Netex constructs the full ordered change plan and presents it in a structured format:

1. **Outage Risk Assessment** — from the OutageRiskAgent (see below)
2. **Security Review** — from the NetworkSecurityAgent
3. **Change Plan** — numbered steps in execution order
4. **Rollback Plan** — what will be reversed if execution fails

The plan is informational only at this stage. No changes are made.

### Phase 3: Single Confirmation

The operator reviews the complete plan and either confirms or cancels. One confirmation covers all steps — Netex does not ask again mid-execution unless a step fails.

## Write Safety Gate

Every write operation across all Netex plugins is protected by a three-step gate. All three conditions must be met:

| Step | What it requires | Purpose |
|------|-----------------|---------|
| 1. Environment variable | `UNIFI_WRITE_ENABLED=true` (or `OPNSENSE_WRITE_ENABLED`, `NETEX_WRITE_ENABLED`) | Prevents accidental writes in read-only environments |
| 2. `--apply` flag | The command must include the `--apply` flag | Ensures the operator explicitly requested a write, not just a dry run |
| 3. Operator confirmation | The operator must confirm the presented change plan | Final human-in-the-loop gate |

If any step is missing, the operation stops safely:

- **Env var disabled:** The tool returns an error explaining that write operations are not enabled
- **No `--apply` flag:** The tool presents what it *would* do (dry run) without executing
- **No confirmation:** The plan is presented but nothing is executed until the operator confirms

For the full technical reference, see [Write Safety](../reference/write-safety.md).

## OutageRiskAgent

Before every write plan, the OutageRiskAgent assesses whether the proposed changes could disrupt the operator's own connection to the network. It follows these steps:

1. Determine the operator's session source IP
2. Map the path from that IP to the management interface
3. Identify the switch port, VLAN, and route carrying the session
4. Check whether the change plan modifies any component in that path

### Risk Tiers

| Risk Tier | Criteria | What Happens |
|-----------|----------|-------------|
| **CRITICAL** | Change directly modifies the interface, VLAN, or route the operator's session traverses | Netex requires the operator to explicitly state they have out-of-band access. A generic "yes" is not sufficient. |
| **HIGH** | Change is in the same subsystem; partial disruption is possible | Netex presents the risk and asks the operator to confirm they are prepared for potential brief disruption |
| **MEDIUM** | Change could cause indirect disruption (DNS, DHCP, routing loop) | Presented as an informational callout in the change plan |
| **LOW** | Change does not touch any infrastructure in the operator's session path | Standard write-gate confirmation only |

If the session path cannot be determined, the risk defaults to **HIGH** with an explanation of why.

## NetworkSecurityAgent

The NetworkSecurityAgent runs in parallel with the OutageRiskAgent before every change plan. It reviews proposed changes for security implications:

- Does this plan introduce or worsen security vulnerabilities?
- Are firewall rules being loosened unnecessarily?
- Does a VLAN configuration create unintended cross-VLAN access?

Findings are severity-ranked and presented with concrete alternative approaches when applicable.

## Out-of-Band Access

For **CRITICAL** operations — changes that directly modify the network path between you and the controller — Netex requires you to confirm out-of-band access before proceeding.

Out-of-band access means a separate path to the management interface that does not depend on the network being changed:

- **Serial console** connected directly to the controller
- **IPMI or iDRAC** on the server hosting the controller
- **Separate management VLAN** on a different physical interface
- **Physical access** to the controller or switch

Netex will assess the outage risk for you, but it cannot guarantee your recovery path. Only you can verify that your out-of-band access works.

!!! danger "Required reading for all write operations"
    Network changes can result in outages that disconnect you from your ability
    to correct them. Never make changes to a network you cannot reach through
    an out-of-band path (serial console, IPMI/iDRAC, a separate management VLAN
    on a different physical interface, or physical access). Netex will assess
    this risk for you, but it cannot guarantee your recovery path — only you can
    verify that.

## Mid-Execution Failures

If a step fails during execution, Netex:

1. **Stops immediately** — no subsequent steps are executed
2. **Reports exactly** which steps completed and which failed
3. **Asks the operator**: "Should I attempt rollback, or leave the current state for you to assess manually?"

Netex never attempts automatic rollback without asking. The operator always decides how to proceed after a failure.

## Summary

| Principle | Implementation |
|-----------|---------------|
| Never change without asking | Three-phase confirmation model |
| Prevent accidental writes | Three-step write safety gate |
| Assess self-disconnection risk | OutageRiskAgent with four risk tiers |
| Review security implications | NetworkSecurityAgent on every change plan |
| Handle failures safely | Stop, report, ask — never auto-rollback |
| Require recovery path for critical changes | Out-of-band access confirmation |
