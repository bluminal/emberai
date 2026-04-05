# SG-300 CLI Quirks

**Severity:** informational
**Triggers:** CLI parsing, command syntax, Netmiko

## Overview

The Cisco SG-300 runs "Cisco Small Business" firmware, NOT full Cisco IOS.
Many commands that work on Catalyst or ISR platforms are absent, renamed, or
produce differently-formatted output. This file documents every known
divergence that affects the plugin's SSH parsers and tool behaviour.

## Firmware and Platform

- The firmware identifies as "Cisco Small Business" in `show version` output.
- There is no `enable secret` hierarchy -- a single enable password is used.
- No routing protocol CLIs (OSPF, BGP, EIGRP) unless L3 firmware is loaded.
  The SG-300 is a Layer 2 switch by default; L3 static routing requires a
  firmware variant and is limited in scope.

## Command Differences from IOS

### show vlan
- Output is a **table format**, not the IOS-style "VLAN Name Status Ports" block.
- Column headers and widths differ from Catalyst `show vlan brief`.
- Parser must handle the SG-300 table layout specifically.

### show interfaces status
- Different column layout than IOS `show interfaces status`.
- Port naming uses `gi1`-`gi24` (no slot/module numbering like `gi0/1`).
- This is the closest equivalent to `show ip interface brief`, which does
  NOT exist on the SG-300.

### show interfaces switchport
- Output uses "Port Mode:" instead of "Administrative Mode:" seen on IOS.
- Trunk allowed VLAN list formatting may differ.

### show mac address-table
- Command is `show mac address-table` (space between "mac" and "address").
- Some IOS versions use `show mac-address-table` (hyphenated). The SG-300
  uses the space-separated form.

### show version
- Does NOT include the hostname in its output.
- To get the hostname, parse `show running-config` for the `hostname` line.

### Port naming
- Gigabit ports: `gi1` through `gi24` (no slot/module prefix).
- Fast Ethernet ports: `fa1` through `fa24` (on mixed models).
- Ten Gigabit ports: `te1` through `te4` (on models with 10G uplinks).
- Port channels: `Po1` through `Po8`.
- There is no `Gi0/1` or `GigabitEthernet0/1` style naming.

### Configuration saving
- `write memory` works and is the preferred command.
- `copy running-config startup-config` also works as an alternative.

## Netmiko Configuration

- **device_type must be `"cisco_s300"`** -- NOT `"cisco_ios"`.
- Using `"cisco_ios"` may appear to connect but will produce parsing errors
  and command failures due to prompt detection differences.
- Limited concurrent SSH sessions: typically 2-4 depending on firmware
  version and available memory.
- SSH session timeout is shorter than IOS defaults; set Netmiko timeouts
  accordingly (10-30 seconds for commands).

## Missing Commands

The following IOS commands do NOT exist on the SG-300:

| IOS Command | SG-300 Equivalent | Notes |
|-------------|-------------------|-------|
| `show ip interface brief` | `show interfaces status` | Different output format |
| `show spanning-tree` (IOS format) | `show spanning-tree` | Output format differs |
| `show cdp neighbors` | `show lldp neighbors` | CDP may not be available; use LLDP |
| `show logging` (buffered) | `show logging` | Limited buffer, format differs |
| `show processes cpu` | Not available | Use SNMP for CPU metrics |
| `show environment` | Not available | Use SNMP for temperature |

## Parser Implications

All parsers in `cisco/parsers/` must be written and tested against actual
SG-300 output samples, NOT against IOS reference documentation. When adding
a new parser:

1. Capture real output from the switch via `show` command.
2. Add the raw output as a test fixture.
3. Write the parser to match the SG-300 format specifically.
4. Do NOT assume IOS formatting will work.
