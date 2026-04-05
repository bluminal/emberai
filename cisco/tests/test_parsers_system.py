"""Tests for system information CLI parsers.

Covers:
- parse_show_version -- firmware, MAC, HW version
- parse_hostname_from_config -- extract hostname from running-config
"""

from __future__ import annotations

from cisco.parsers.system import parse_hostname_from_config, parse_show_version

# ---------------------------------------------------------------------------
# parse_show_version
# ---------------------------------------------------------------------------


class TestParseShowVersion:
    """Parse show version output."""

    def test_firmware_version(self, show_version_output: str) -> None:
        info = parse_show_version(show_version_output)
        assert info.firmware_version == "3.0.0.37"

    def test_mac_address(self, show_version_output: str) -> None:
        info = parse_show_version(show_version_output)
        assert info.mac_address == "d8:b3:70:c9:e9:07"

    def test_hw_version_in_model(self, show_version_output: str) -> None:
        info = parse_show_version(show_version_output)
        # Model is derived from HW version: "SG-300 V01"
        assert "V01" in info.model

    def test_model_starts_with_sg300(self, show_version_output: str) -> None:
        info = parse_show_version(show_version_output)
        assert info.model.startswith("SG-300")

    def test_default_hostname(self, show_version_output: str) -> None:
        """show version doesn't contain hostname -- defaults to argument."""
        info = parse_show_version(show_version_output)
        assert info.hostname == "unknown"  # Default when not provided

    def test_custom_hostname_passthrough(self, show_version_output: str) -> None:
        info = parse_show_version(show_version_output, hostname="CiscoSG300")
        assert info.hostname == "CiscoSG300"

    def test_serial_number_empty(self, show_version_output: str) -> None:
        """SG-300 show version doesn't include serial number."""
        info = parse_show_version(show_version_output)
        assert info.serial_number == ""

    def test_uptime_seconds_zero(self, show_version_output: str) -> None:
        """SG-300 show version doesn't include uptime."""
        info = parse_show_version(show_version_output)
        assert info.uptime_seconds == 0


# ---------------------------------------------------------------------------
# parse_hostname_from_config
# ---------------------------------------------------------------------------


class TestParseHostnameFromConfig:
    """Extract hostname from running-config."""

    def test_parse_hostname(self, show_running_config_output: str) -> None:
        hostname = parse_hostname_from_config(show_running_config_output)
        assert hostname == "CiscoSG300"

    def test_no_hostname_returns_unknown(self) -> None:
        """If no hostname directive found, return 'unknown'."""
        raw = "!\nvlan database\nvlan 10\nexit\n"
        hostname = parse_hostname_from_config(raw)
        assert hostname == "unknown"

    def test_hostname_with_whitespace(self) -> None:
        raw = "hostname   MySwitch\n!\n"
        hostname = parse_hostname_from_config(raw)
        assert hostname == "MySwitch"
