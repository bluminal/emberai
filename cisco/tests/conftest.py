"""Shared pytest fixtures for Cisco SG-300 plugin tests.

Provides:
- ``fixture_dir`` -- path to the fixtures/ directory
- Individual fixtures loading each CLI output text file
- ``mock_ssh_client`` -- a fully mocked CiscoSSHClient
- ``mock_netmiko_connect`` -- patches netmiko.ConnectHandler
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from tests.fixtures import load_fixture

FIXTURES_DIR = Path(__file__).parent / "fixtures"


# ---------------------------------------------------------------------------
# Fixture directory
# ---------------------------------------------------------------------------


@pytest.fixture()
def fixture_dir() -> Path:
    """Return the path to the test fixtures directory."""
    return FIXTURES_DIR


# ---------------------------------------------------------------------------
# Raw CLI output fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def show_vlan_output() -> str:
    """Load the ``show vlan`` fixture."""
    return load_fixture("show_vlan.txt")


@pytest.fixture()
def show_vlan_empty_output() -> str:
    """Load the ``show vlan`` empty fixture (only default VLAN)."""
    return load_fixture("show_vlan_empty.txt")


@pytest.fixture()
def show_interfaces_status_output() -> str:
    """Load the ``show interfaces status`` fixture."""
    return load_fixture("show_interfaces_status.txt")


@pytest.fixture()
def show_switchport_trunk_output() -> str:
    """Load the ``show interfaces switchport`` trunk fixture."""
    return load_fixture("show_switchport_trunk.txt")


@pytest.fixture()
def show_switchport_access_output() -> str:
    """Load the ``show interfaces switchport`` access fixture."""
    return load_fixture("show_switchport_access.txt")


@pytest.fixture()
def show_mac_address_table_output() -> str:
    """Load the ``show mac address-table`` fixture."""
    return load_fixture("show_mac_address_table.txt")


@pytest.fixture()
def show_mac_address_table_empty_output() -> str:
    """Load the ``show mac address-table`` empty fixture."""
    return load_fixture("show_mac_address_table_empty.txt")


@pytest.fixture()
def show_lldp_neighbors_output() -> str:
    """Load the ``show lldp neighbors`` fixture."""
    return load_fixture("show_lldp_neighbors.txt")


@pytest.fixture()
def show_lldp_neighbors_empty_output() -> str:
    """Load the ``show lldp neighbors`` empty fixture."""
    return load_fixture("show_lldp_neighbors_empty.txt")


@pytest.fixture()
def show_version_output() -> str:
    """Load the ``show version`` fixture."""
    return load_fixture("show_version.txt")


@pytest.fixture()
def show_running_config_output() -> str:
    """Load the ``show running-config`` fixture."""
    return load_fixture("show_running_config.txt")


# ---------------------------------------------------------------------------
# Mock SSH client
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_ssh_client() -> MagicMock:
    """Create a mock CiscoSSHClient with fixtures as command responses.

    All methods are async mocks.  ``send_command`` returns fixture content
    based on the command string.
    """
    client = MagicMock()
    client.connect = AsyncMock()
    client.disconnect = AsyncMock()
    client.is_connected = AsyncMock(return_value=True)
    client.save_config = AsyncMock(return_value="[OK]")
    client.get_running_config = AsyncMock(
        return_value=load_fixture("show_running_config.txt"),
    )
    client.send_config_set = AsyncMock(return_value="")

    # Route send_command to the correct fixture based on the command
    command_map: dict[str, str] = {
        "show vlan": load_fixture("show_vlan.txt"),
        "show interfaces status": load_fixture("show_interfaces_status.txt"),
        "show mac address-table": load_fixture("show_mac_address_table.txt"),
        "show lldp neighbors": load_fixture("show_lldp_neighbors.txt"),
        "show version": load_fixture("show_version.txt"),
        "show running-config": load_fixture("show_running_config.txt"),
    }

    async def _send_command(command: str) -> str:
        if command in command_map:
            return command_map[command]
        # For switchport commands, check if it's a trunk or access query
        if command.startswith("show interfaces switchport"):
            port = command.rsplit(None, 1)[-1] if " " in command else ""
            if port == "gi24":
                return load_fixture("show_switchport_trunk.txt")
            elif port == "gi3":
                return load_fixture("show_switchport_access.txt")
        return ""

    client.send_command = AsyncMock(side_effect=_send_command)
    return client


# ---------------------------------------------------------------------------
# Mock Netmiko ConnectHandler
# ---------------------------------------------------------------------------


class MockNetmikoDevice:
    """Virtual Cisco SG-300 device for testing.

    Simulates Netmiko's ConnectHandler interface with realistic
    CLI responses loaded from test fixtures.
    """

    def __init__(self, **kwargs: object) -> None:
        self.device_type = kwargs.get("device_type", "cisco_s300")
        self.host = kwargs.get("host", "192.168.1.2")
        self.username = kwargs.get("username", "admin")
        self.password = kwargs.get("password", "password")
        self.secret = kwargs.get("secret")
        self._enabled = False
        self._connected = True

        self._command_map: dict[str, str] = {
            "show vlan": load_fixture("show_vlan.txt"),
            "show interfaces status": load_fixture("show_interfaces_status.txt"),
            "show mac address-table": load_fixture("show_mac_address_table.txt"),
            "show lldp neighbors": load_fixture("show_lldp_neighbors.txt"),
            "show version": load_fixture("show_version.txt"),
            "show running-config": load_fixture("show_running_config.txt"),
            "write memory": "[OK] flash:/config.text was updated successfully\n",
        }

    def enable(self) -> None:
        """Enter enable mode."""
        self._enabled = True

    def send_command(self, command: str, **kwargs: object) -> str:
        """Simulate sending a CLI command."""
        if not self._connected:
            raise OSError("Connection closed")
        return self._command_map.get(command, "% Invalid input detected.\n")

    def send_config_set(self, commands: list[str], **kwargs: object) -> str:
        """Simulate sending a config set."""
        if not self._connected:
            raise OSError("Connection closed")
        return "\n".join(f"({self.host}) #{cmd}" for cmd in commands)

    def is_alive(self) -> bool:
        """Check if the connection is alive."""
        return self._connected

    def disconnect(self) -> None:
        """Disconnect from the device."""
        self._connected = False


@pytest.fixture()
def mock_netmiko_device() -> MockNetmikoDevice:
    """Return a MockNetmikoDevice instance."""
    return MockNetmikoDevice()


@pytest.fixture()
def mock_netmiko_connect(mock_netmiko_device: MockNetmikoDevice):
    """Patch ``netmiko.ConnectHandler`` to return a MockNetmikoDevice.

    The patch targets the import in ``cisco.ssh.client`` so that
    ``ConnectHandler(...)`` returns our virtual device.
    """
    with patch("cisco.ssh.client.ConnectHandler", return_value=mock_netmiko_device) as mock_cls:
        yield mock_cls
