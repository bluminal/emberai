# SPDX-License-Identifier: MIT
"""Security posture agent -- orchestrates audit and compare tools.

Composes MCP tool calls with OX formatters to produce operator-ready
markdown reports for security audits and profile comparisons.
"""

from __future__ import annotations

from nextdns.output import (
    Finding,
    ProfileDiff,
    Severity,
    format_profile_comparison,
    format_security_posture,
)
from nextdns.tools.security_posture import (
    nextdns__security_posture__audit,
    nextdns__security_posture__compare,
)


async def security_audit(profile_id: str | None = None) -> str:
    """Run a security audit and format results as a severity-tiered report.

    Args:
        profile_id: Audit a single profile, or all profiles if None.
    """
    raw_findings = await nextdns__security_posture__audit(profile_id)

    findings = [
        Finding(
            severity=Severity(f["severity"]),
            title=f["title"],
            detail=f["detail"],
            recommendation=f.get("recommendation"),
        )
        for f in raw_findings
    ]

    return format_security_posture(findings)


async def security_compare(profile_id_a: str, profile_id_b: str) -> str:
    """Compare two profiles and format results as a side-by-side diff.

    Args:
        profile_id_a: First profile identifier.
        profile_id_b: Second profile identifier.
    """
    raw_diff = await nextdns__security_posture__compare(profile_id_a, profile_id_b)

    # Convert list pairs back to tuples for ProfileDiff
    diff = ProfileDiff(
        profile_a_name=raw_diff["profile_a_name"],
        profile_b_name=raw_diff["profile_b_name"],
        security_diff={k: tuple(v) for k, v in raw_diff["security_diff"].items()},
        privacy_diff={k: tuple(v) for k, v in raw_diff["privacy_diff"].items()},
        parental_diff={k: tuple(v) for k, v in raw_diff["parental_diff"].items()},
        settings_diff={k: tuple(v) for k, v in raw_diff["settings_diff"].items()},
    )

    return format_profile_comparison(diff)
