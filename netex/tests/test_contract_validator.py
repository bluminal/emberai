# SPDX-License-Identifier: MIT
"""Tests for the Contract Validator."""

from __future__ import annotations

import pytest

from netex.registry.contract_validator import (
    ContractValidationReport,
    ContractValidator,
    ValidationLevel,
    ValidationResult,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def validator() -> ContractValidator:
    return ContractValidator()


def _valid_plugin_info() -> dict:
    """A fully valid plugin_info() dict."""
    return {
        "name": "testplugin",
        "version": "1.0.0",
        "description": "A test plugin",
        "vendor": "test",
        "roles": ["edge"],
        "skills": ["topology", "health"],
        "write_flag": "TESTPLUGIN_WRITE_ENABLED",
        "contract_version": "1.0.0",
        "server_factory": lambda: None,
        "tools": {
            "topology": ["testplugin__topology__list_devices"],
        },
    }


# ---------------------------------------------------------------------------
# Valid plugin
# ---------------------------------------------------------------------------

class TestValidPlugin:
    def test_valid_plugin_passes(self, validator: ContractValidator) -> None:
        report = validator.validate(_valid_plugin_info())
        assert report.is_valid
        assert len(report.errors) == 0

    def test_report_plugin_name(self, validator: ContractValidator) -> None:
        report = validator.validate(_valid_plugin_info())
        assert report.plugin_name == "testplugin"

    def test_report_format(self, validator: ContractValidator) -> None:
        report = validator.validate(_valid_plugin_info())
        formatted = report.format_report()
        assert "PASS" in formatted
        assert "testplugin" in formatted


# ---------------------------------------------------------------------------
# Missing required fields
# ---------------------------------------------------------------------------

class TestMissingRequired:
    def test_missing_name(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        del info["name"]
        report = validator.validate(info)
        assert not report.is_valid
        assert any(r.field == "name" for r in report.errors)

    def test_empty_name(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["name"] = ""
        report = validator.validate(info)
        assert not report.is_valid

    def test_missing_version(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        del info["version"]
        report = validator.validate(info)
        assert not report.is_valid

    def test_missing_description(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        del info["description"]
        report = validator.validate(info)
        assert not report.is_valid

    def test_missing_all_required(self, validator: ContractValidator) -> None:
        report = validator.validate({})
        assert not report.is_valid
        assert len(report.errors) >= 3  # name, version, description


# ---------------------------------------------------------------------------
# Name validation
# ---------------------------------------------------------------------------

class TestNameValidation:
    def test_valid_name(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["name"] = "my-plugin"
        report = validator.validate(info)
        assert not any(r.field == "name" and r.level == ValidationLevel.ERROR
                       and "lowercase" in r.message for r in report.results)

    def test_invalid_name_uppercase(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["name"] = "MyPlugin"
        report = validator.validate(info)
        assert any(r.field == "name" and "lowercase" in r.message for r in report.results)

    def test_invalid_name_spaces(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["name"] = "my plugin"
        report = validator.validate(info)
        assert any(r.field == "name" and r.level == ValidationLevel.ERROR for r in report.results)


# ---------------------------------------------------------------------------
# Roles validation
# ---------------------------------------------------------------------------

class TestRolesValidation:
    def test_known_roles(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["roles"] = ["gateway", "edge"]
        report = validator.validate(info)
        assert not any(r.field == "roles" and r.level == ValidationLevel.ERROR for r in report.results)

    def test_unknown_role_warning(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["roles"] = ["unknown_role"]
        report = validator.validate(info)
        assert any(r.field == "roles" and r.level == ValidationLevel.WARNING for r in report.results)

    def test_roles_not_list_error(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["roles"] = "gateway"
        report = validator.validate(info)
        assert any(r.field == "roles" and r.level == ValidationLevel.ERROR for r in report.results)


# ---------------------------------------------------------------------------
# Skills validation
# ---------------------------------------------------------------------------

class TestSkillsValidation:
    def test_known_skills(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["skills"] = ["topology", "firewall"]
        report = validator.validate(info)
        assert not any(r.field == "skills" and r.level == ValidationLevel.ERROR for r in report.results)

    def test_unknown_skill_warning(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["skills"] = ["unknown_skill"]
        report = validator.validate(info)
        assert any(r.field == "skills" and r.level == ValidationLevel.WARNING for r in report.results)


# ---------------------------------------------------------------------------
# Write flag validation
# ---------------------------------------------------------------------------

class TestWriteFlagValidation:
    def test_valid_write_flag(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["write_flag"] = "MYPLUGIN_WRITE_ENABLED"
        report = validator.validate(info)
        assert not any(r.field == "write_flag" and r.level == ValidationLevel.ERROR for r in report.results)

    def test_invalid_write_flag_pattern(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["write_flag"] = "bad_flag"
        report = validator.validate(info)
        assert any(r.field == "write_flag" and r.level == ValidationLevel.WARNING for r in report.results)


# ---------------------------------------------------------------------------
# Contract version validation
# ---------------------------------------------------------------------------

class TestContractVersion:
    def test_valid_contract_version(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["contract_version"] = "1.0.0"
        report = validator.validate(info)
        assert not any(r.field == "contract_version" and r.level == ValidationLevel.ERROR for r in report.results)

    def test_invalid_contract_version(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["contract_version"] = "not-semver"
        report = validator.validate(info)
        assert any(r.field == "contract_version" and r.level == ValidationLevel.ERROR for r in report.results)


# ---------------------------------------------------------------------------
# Tool name validation
# ---------------------------------------------------------------------------

class TestToolNameValidation:
    def test_valid_tool_name(self, validator: ContractValidator) -> None:
        result = validator.validate_tool_name("unifi__topology__list_devices")
        assert result is None

    def test_invalid_tool_name_no_separators(self, validator: ContractValidator) -> None:
        result = validator.validate_tool_name("list_devices")
        assert result is not None
        assert result.level == ValidationLevel.ERROR

    def test_invalid_tool_name_single_underscore(self, validator: ContractValidator) -> None:
        result = validator.validate_tool_name("unifi_topology_list")
        assert result is not None

    def test_invalid_tool_name_uppercase(self, validator: ContractValidator) -> None:
        result = validator.validate_tool_name("Unifi__topology__list")
        assert result is not None

    def test_tool_names_in_plugin_info(self, validator: ContractValidator) -> None:
        info = _valid_plugin_info()
        info["tools"] = {"topology": ["test-plugin__topology__list_devices"]}
        report = validator.validate(info)
        # The hyphen in plugin name is valid in the name field, but the
        # tool name pattern requires lowercase alphanumeric only
        tool_errors = [r for r in report.results if "tool" in r.field.lower() and r.level == ValidationLevel.ERROR]
        # test-plugin has hyphen, which is invalid in tool names
        assert len(tool_errors) > 0


# ---------------------------------------------------------------------------
# SKILL.md frontmatter validation
# ---------------------------------------------------------------------------

class TestSkillMdValidation:
    def test_valid_frontmatter(self, validator: ContractValidator) -> None:
        fm = {
            "name": "opnsense",
            "version": "0.2.0",
            "description": "OPNsense gateway intelligence",
            "netex_vendor": "opnsense",
            "netex_role": ["gateway"],
            "netex_skills": ["firewall", "routing"],
            "netex_contract_version": "1.0.0",
        }
        report = validator.validate_skill_md_frontmatter(fm)
        assert report.is_valid

    def test_missing_required_frontmatter(self, validator: ContractValidator) -> None:
        fm = {"name": "test"}  # missing version and description
        report = validator.validate_skill_md_frontmatter(fm)
        assert not report.is_valid

    def test_invalid_contract_version(self, validator: ContractValidator) -> None:
        fm = {
            "name": "test",
            "version": "1.0.0",
            "description": "desc",
            "netex_contract_version": "invalid",
        }
        report = validator.validate_skill_md_frontmatter(fm)
        assert not report.is_valid

    def test_unknown_role_warning(self, validator: ContractValidator) -> None:
        fm = {
            "name": "test",
            "version": "1.0.0",
            "description": "desc",
            "netex_role": ["unknown_role"],
        }
        report = validator.validate_skill_md_frontmatter(fm)
        assert len(report.warnings) > 0


# ---------------------------------------------------------------------------
# Orchestrator validation
# ---------------------------------------------------------------------------

class TestOrchestratorValidation:
    def test_orchestrator_no_roles_warning(self, validator: ContractValidator) -> None:
        info = {
            "name": "netex",
            "version": "0.3.0",
            "description": "Orchestrator",
            "contract_version": "1.0.0",
            "is_orchestrator": True,
        }
        report = validator.validate(info)
        # Orchestrators should not get warnings about missing roles/skills
        role_warnings = [r for r in report.warnings if r.field == "roles"]
        assert len(role_warnings) == 0


# ---------------------------------------------------------------------------
# ContractValidationReport
# ---------------------------------------------------------------------------

class TestContractValidationReport:
    def test_is_valid_no_errors(self) -> None:
        report = ContractValidationReport(plugin_name="test")
        report.results.append(ValidationResult(
            level=ValidationLevel.WARNING, field="test", message="just a warning",
        ))
        assert report.is_valid

    def test_is_valid_with_errors(self) -> None:
        report = ContractValidationReport(plugin_name="test")
        report.results.append(ValidationResult(
            level=ValidationLevel.ERROR, field="test", message="an error",
        ))
        assert not report.is_valid

    def test_errors_property(self) -> None:
        report = ContractValidationReport(plugin_name="test")
        report.results.append(ValidationResult(level=ValidationLevel.ERROR, field="a", message="err"))
        report.results.append(ValidationResult(level=ValidationLevel.WARNING, field="b", message="warn"))
        assert len(report.errors) == 1
        assert len(report.warnings) == 1

    def test_format_report_includes_status(self) -> None:
        report = ContractValidationReport(plugin_name="test")
        assert "PASS" in report.format_report()

        report.results.append(ValidationResult(level=ValidationLevel.ERROR, field="x", message="fail"))
        assert "FAIL" in report.format_report()
