"""Contract Validator -- validates vendor plugin compliance with the
Vendor Plugin Contract v1.0.0.

Checks that a plugin's metadata (from ``plugin_info()``) and optional
SKILL.md frontmatter conform to the contract requirements.

Validation levels:
    - REQUIRED: Missing field causes a validation failure.
    - RECOMMENDED: Missing field triggers a warning but not failure.
    - OPTIONAL: Missing field is noted but does not affect validation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ValidationLevel(StrEnum):
    """Severity of a validation check."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class ValidationResult:
    """Result of a single validation check."""

    level: ValidationLevel
    field: str
    message: str
    value: Any = None


@dataclass
class ContractValidationReport:
    """Complete validation report for a single plugin."""

    plugin_name: str
    contract_version: str = "1.0.0"
    results: list[ValidationResult] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Whether the plugin passes contract validation (no errors)."""
        return not any(r.level == ValidationLevel.ERROR for r in self.results)

    @property
    def errors(self) -> list[ValidationResult]:
        """All error-level results."""
        return [r for r in self.results if r.level == ValidationLevel.ERROR]

    @property
    def warnings(self) -> list[ValidationResult]:
        """All warning-level results."""
        return [r for r in self.results if r.level == ValidationLevel.WARNING]

    @property
    def info(self) -> list[ValidationResult]:
        """All info-level results."""
        return [r for r in self.results if r.level == ValidationLevel.INFO]

    def format_report(self) -> str:
        """Format the validation report as a human-readable string."""
        lines: list[str] = [
            f"Contract Validation Report: {self.plugin_name}",
            f"Contract version: {self.contract_version}",
            f"Status: {'PASS' if self.is_valid else 'FAIL'}",
            "",
        ]

        for level in (ValidationLevel.ERROR, ValidationLevel.WARNING, ValidationLevel.INFO):
            items = [r for r in self.results if r.level == level]
            if not items:
                continue

            label = level.value.upper()
            lines.append(f"[{label}]")
            for result in items:
                lines.append(f"  - {result.field}: {result.message}")
                if result.value is not None:
                    lines.append(f"    Value: {result.value!r}")
            lines.append("")

        return "\n".join(lines)


# ---------------------------------------------------------------------------
# Known valid values
# ---------------------------------------------------------------------------

KNOWN_ROLES = frozenset({
    "gateway", "edge", "wireless", "overlay", "dns", "monitoring",
})

KNOWN_SKILL_GROUPS = frozenset({
    "topology", "health", "wifi", "clients", "traffic",
    "security", "config", "multisite", "interfaces", "firewall",
    "routing", "vpn", "services", "diagnostics", "firmware",
})

# Tool name pattern: {plugin}__{skill}__{operation}
TOOL_NAME_PATTERN = re.compile(r"^[a-z][a-z0-9]*__[a-z][a-z0-9_]*__[a-z][a-z0-9_]*$")


# ---------------------------------------------------------------------------
# Validator
# ---------------------------------------------------------------------------

class ContractValidator:
    """Validates vendor plugin metadata against the Vendor Plugin Contract.

    Usage::

        validator = ContractValidator()
        report = validator.validate(plugin_info_dict)
        if not report.is_valid:
            print(report.format_report())
    """

    def validate(self, info: dict[str, Any]) -> ContractValidationReport:
        """Validate a plugin's metadata dict against the contract.

        Parameters
        ----------
        info:
            Plugin metadata dict as returned by ``plugin_info()``.

        Returns
        -------
        ContractValidationReport
            Complete validation report.
        """
        name = info.get("name", "<unknown>")
        report = ContractValidationReport(plugin_name=name)

        self._validate_required_fields(info, report)
        self._validate_name(info, report)
        self._validate_version(info, report)
        self._validate_roles(info, report)
        self._validate_skills(info, report)
        self._validate_write_flag(info, report)
        self._validate_contract_version(info, report)
        self._validate_tools(info, report)
        self._validate_recommended_fields(info, report)

        return report

    def validate_skill_md_frontmatter(
        self,
        frontmatter: dict[str, Any],
    ) -> ContractValidationReport:
        """Validate SKILL.md YAML frontmatter against the contract.

        Parameters
        ----------
        frontmatter:
            Parsed YAML frontmatter from a plugin's SKILL.md file.

        Returns
        -------
        ContractValidationReport
            Complete validation report for the frontmatter.
        """
        name = frontmatter.get("name", "<unknown>")
        report = ContractValidationReport(plugin_name=name)

        # Required frontmatter fields
        required_fields = ["name", "version", "description"]
        for f in required_fields:
            if f not in frontmatter or not frontmatter[f]:
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field=f"frontmatter.{f}",
                    message=f"Required frontmatter field '{f}' is missing or empty",
                ))

        # Validate netex_contract_version
        contract_ver = frontmatter.get("netex_contract_version")
        if contract_ver is not None:
            if not isinstance(contract_ver, str) or not re.match(r"^\d+\.\d+\.\d+$", contract_ver):
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field="frontmatter.netex_contract_version",
                    message="Must be a semver string (e.g., '1.0.0')",
                    value=contract_ver,
                ))

        # Validate netex_vendor (if present and not orchestrator)
        vendor = frontmatter.get("netex_vendor")
        if vendor is not None:
            if not isinstance(vendor, str) or not vendor.strip():
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field="frontmatter.netex_vendor",
                    message="Must be a non-empty string",
                    value=vendor,
                ))

        # Validate netex_role (if present)
        roles = frontmatter.get("netex_role")
        if roles is not None:
            if isinstance(roles, str):
                roles = [roles]
            if isinstance(roles, list):
                for role in roles:
                    if role not in KNOWN_ROLES:
                        report.results.append(ValidationResult(
                            level=ValidationLevel.WARNING,
                            field="frontmatter.netex_role",
                            message=f"Unknown role '{role}'. Known: {sorted(KNOWN_ROLES)}",
                            value=role,
                        ))

        # Validate netex_skills (if present)
        skills = frontmatter.get("netex_skills")
        if skills is not None:
            if isinstance(skills, list):
                for skill in skills:
                    if skill not in KNOWN_SKILL_GROUPS:
                        report.results.append(ValidationResult(
                            level=ValidationLevel.WARNING,
                            field="frontmatter.netex_skills",
                            message=f"Unknown skill group '{skill}'. Known: {sorted(KNOWN_SKILL_GROUPS)}",
                            value=skill,
                        ))

        return report

    def validate_tool_name(self, tool_name: str) -> ValidationResult | None:
        """Validate a single tool name against the naming convention.

        Tool names must follow: ``{plugin}__{skill}__{operation}``

        Returns ``None`` if valid, or a ``ValidationResult`` if invalid.
        """
        if not TOOL_NAME_PATTERN.match(tool_name):
            return ValidationResult(
                level=ValidationLevel.ERROR,
                field="tool_name",
                message=(
                    f"Tool name '{tool_name}' does not match the required pattern "
                    f"{{plugin}}__{{skill}}__{{operation}} (lowercase, double underscore separators)"
                ),
                value=tool_name,
            )
        return None

    # ------------------------------------------------------------------
    # Internal validation methods
    # ------------------------------------------------------------------

    def _validate_required_fields(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Check that all required fields are present and non-empty."""
        required = ["name", "version", "description"]
        for f in required:
            if f not in info:
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field=f,
                    message=f"Required field '{f}' is missing",
                ))
            elif not info[f]:
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field=f,
                    message=f"Required field '{f}' is empty",
                    value=info[f],
                ))

    def _validate_name(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Validate plugin name format."""
        name = info.get("name")
        if name and not re.match(r"^[a-z][a-z0-9_-]*$", name):
            report.results.append(ValidationResult(
                level=ValidationLevel.ERROR,
                field="name",
                message="Plugin name must be lowercase alphanumeric with optional hyphens/underscores",
                value=name,
            ))

    def _validate_version(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Validate version string format (semver)."""
        version = info.get("version")
        if version and not re.match(r"^\d+\.\d+\.\d+", version):
            report.results.append(ValidationResult(
                level=ValidationLevel.WARNING,
                field="version",
                message="Version should follow semantic versioning (e.g., '1.0.0')",
                value=version,
            ))

    def _validate_roles(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Validate roles list."""
        roles = info.get("roles")
        is_orchestrator = info.get("is_orchestrator", False)

        if roles is None and not is_orchestrator:
            report.results.append(ValidationResult(
                level=ValidationLevel.WARNING,
                field="roles",
                message="Vendor plugins should declare at least one role",
            ))
            return

        if roles is not None:
            if not isinstance(roles, list):
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field="roles",
                    message="'roles' must be a list of strings",
                    value=roles,
                ))
                return

            for role in roles:
                if role not in KNOWN_ROLES:
                    report.results.append(ValidationResult(
                        level=ValidationLevel.WARNING,
                        field="roles",
                        message=f"Unknown role '{role}'. Known roles: {sorted(KNOWN_ROLES)}",
                        value=role,
                    ))

    def _validate_skills(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Validate skills list."""
        skills = info.get("skills")
        is_orchestrator = info.get("is_orchestrator", False)

        if skills is None and not is_orchestrator:
            report.results.append(ValidationResult(
                level=ValidationLevel.WARNING,
                field="skills",
                message="Vendor plugins should declare at least one skill",
            ))
            return

        if skills is not None:
            if not isinstance(skills, list):
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field="skills",
                    message="'skills' must be a list of strings",
                    value=skills,
                ))
                return

            for skill in skills:
                if skill not in KNOWN_SKILL_GROUPS:
                    report.results.append(ValidationResult(
                        level=ValidationLevel.WARNING,
                        field="skills",
                        message=f"Unknown skill group '{skill}'. Known: {sorted(KNOWN_SKILL_GROUPS)}",
                        value=skill,
                    ))

    def _validate_write_flag(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Validate write_flag naming convention."""
        write_flag = info.get("write_flag")
        is_orchestrator = info.get("is_orchestrator", False)

        if write_flag is None and not is_orchestrator:
            report.results.append(ValidationResult(
                level=ValidationLevel.WARNING,
                field="write_flag",
                message="Vendor plugins should declare a write_flag (e.g., 'PLUGIN_WRITE_ENABLED')",
            ))
            return

        if write_flag is not None:
            if not isinstance(write_flag, str):
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field="write_flag",
                    message="'write_flag' must be a string",
                    value=write_flag,
                ))
            elif not re.match(r"^[A-Z][A-Z0-9_]*_WRITE_ENABLED$", write_flag):
                report.results.append(ValidationResult(
                    level=ValidationLevel.WARNING,
                    field="write_flag",
                    message="write_flag should follow pattern '{PLUGIN}_WRITE_ENABLED'",
                    value=write_flag,
                ))

    def _validate_contract_version(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Validate contract_version field."""
        version = info.get("contract_version")
        if version is None:
            report.results.append(ValidationResult(
                level=ValidationLevel.WARNING,
                field="contract_version",
                message="Plugins should declare their contract_version",
            ))
            return

        if not isinstance(version, str):
            report.results.append(ValidationResult(
                level=ValidationLevel.ERROR,
                field="contract_version",
                message="'contract_version' must be a string",
                value=version,
            ))
        elif not re.match(r"^\d+\.\d+\.\d+$", version):
            report.results.append(ValidationResult(
                level=ValidationLevel.ERROR,
                field="contract_version",
                message="'contract_version' must be a semver string (e.g., '1.0.0')",
                value=version,
            ))

    def _validate_tools(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Validate tool names follow the naming convention."""
        tools = info.get("tools")
        if tools is None:
            return

        if not isinstance(tools, dict):
            report.results.append(ValidationResult(
                level=ValidationLevel.ERROR,
                field="tools",
                message="'tools' must be a dict mapping skill groups to tool name lists",
                value=type(tools).__name__,
            ))
            return

        plugin_name = info.get("name", "")

        for skill_group, tool_names in tools.items():
            if not isinstance(tool_names, list):
                report.results.append(ValidationResult(
                    level=ValidationLevel.ERROR,
                    field=f"tools.{skill_group}",
                    message=f"Tool names for skill group '{skill_group}' must be a list",
                    value=type(tool_names).__name__,
                ))
                continue

            for tool_name in tool_names:
                # Check naming convention
                result = self.validate_tool_name(tool_name)
                if result is not None:
                    report.results.append(result)

                # Check plugin prefix matches
                if plugin_name and not tool_name.startswith(f"{plugin_name}__"):
                    report.results.append(ValidationResult(
                        level=ValidationLevel.WARNING,
                        field=f"tools.{skill_group}",
                        message=(
                            f"Tool '{tool_name}' does not start with plugin prefix "
                            f"'{plugin_name}__'"
                        ),
                        value=tool_name,
                    ))

    def _validate_recommended_fields(
        self, info: dict[str, Any], report: ContractValidationReport,
    ) -> None:
        """Check for recommended but not required fields."""
        is_orchestrator = info.get("is_orchestrator", False)

        if not is_orchestrator:
            if "vendor" not in info:
                report.results.append(ValidationResult(
                    level=ValidationLevel.INFO,
                    field="vendor",
                    message="Consider declaring 'vendor' for clearer plugin identification",
                ))

            if "server_factory" not in info:
                report.results.append(ValidationResult(
                    level=ValidationLevel.INFO,
                    field="server_factory",
                    message="Consider providing 'server_factory' for embedded server instantiation",
                ))
