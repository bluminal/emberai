"""Tests for the Cisco SG-300 SSH client.

CRITICAL: This tests against a fully mocked Netmiko ConnectHandler.
Nothing ever runs against a real device.

Covers:
- Connection with correct device_type="cisco_s300"
- Enable mode entry when CISCO_ENABLE_PASSWORD is set
- send_command returns fixture output
- Auto-reconnect on timeout
- Command serialization via asyncio.Lock
- NetmikoAuthenticationException mapped to AuthenticationError
- NetmikoTimeoutException mapped to NetworkError
- Clean disconnection
- get_client() factory reads from env vars
"""

from __future__ import annotations

import asyncio
import os

# Import for type reference in patching
from typing import TYPE_CHECKING
from unittest.mock import MagicMock, patch

import pytest

from cisco.errors import AuthenticationError, NetworkError
from cisco.ssh.client import CiscoSSHClient, get_client

if TYPE_CHECKING:
    from tests.conftest import MockNetmikoDevice

# ---------------------------------------------------------------------------
# Connection
# ---------------------------------------------------------------------------


class TestConnect:
    """SSH connection establishment."""

    @pytest.mark.asyncio
    async def test_connect_creates_handler_with_correct_device_type(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        """ConnectHandler is called with device_type='cisco_s300'."""
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_connect.assert_called_once()
        call_kwargs = mock_netmiko_connect.call_args
        assert call_kwargs.kwargs.get("device_type") == "cisco_s300" or (
            len(call_kwargs.args) == 0
            and call_kwargs[1].get("device_type") == "cisco_s300"
        )

    @pytest.mark.asyncio
    async def test_connect_passes_credentials(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="s3cret",
        )
        await client.connect()

        call_kwargs = mock_netmiko_connect.call_args[1]
        assert call_kwargs["host"] == "192.168.1.2"
        assert call_kwargs["username"] == "admin"
        assert call_kwargs["password"] == "s3cret"


# ---------------------------------------------------------------------------
# Enable mode
# ---------------------------------------------------------------------------


class TestConnectWithEnable:
    """Enable mode entered when CISCO_ENABLE_PASSWORD is set."""

    @pytest.mark.asyncio
    async def test_enable_mode_entered(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
            enable_password="enable_secret",
        )
        await client.connect()

        # The device should have been put into enable mode
        assert mock_netmiko_device._enabled is True

    @pytest.mark.asyncio
    async def test_no_enable_without_password(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        # Enable should NOT have been called
        assert mock_netmiko_device._enabled is False

    @pytest.mark.asyncio
    async def test_enable_password_passed_as_secret(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
            enable_password="enable_secret",
        )
        await client.connect()

        call_kwargs = mock_netmiko_connect.call_args[1]
        assert call_kwargs["secret"] == "enable_secret"


# ---------------------------------------------------------------------------
# send_command
# ---------------------------------------------------------------------------


class TestSendCommand:
    """send_command returns fixture output via mocked Netmiko."""

    @pytest.mark.asyncio
    async def test_send_command_returns_output(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        output = await client.send_command("show vlan")
        assert "default" in output
        assert "Admin" in output

    @pytest.mark.asyncio
    async def test_send_show_version(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        output = await client.send_command("show version")
        assert "3.0.0.37" in output

    @pytest.mark.asyncio
    async def test_send_show_mac_address_table(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        output = await client.send_command("show mac address-table")
        assert "00:08:a2:09:78:fa" in output


# ---------------------------------------------------------------------------
# Auto-reconnect
# ---------------------------------------------------------------------------


class TestAutoReconnect:
    """Simulate timeout, verify reconnect."""

    @pytest.mark.asyncio
    async def test_auto_reconnect_on_stale_connection(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        # First call works
        output1 = await client.send_command("show vlan")
        assert "default" in output1

        # Simulate stale connection -- is_alive() returns False
        # The client should reconnect automatically
        call_count = 0

        def stale_then_alive() -> bool:
            nonlocal call_count
            call_count += 1
            return call_count != 1  # First check: stale, then alive

        mock_netmiko_device.is_alive = stale_then_alive

        # Force the client to think connection is stale
        output2 = await client.send_command("show version")
        assert "3.0.0.37" in output2

        # ConnectHandler should have been called at least twice (initial + reconnect)
        assert mock_netmiko_connect.call_count >= 2


# ---------------------------------------------------------------------------
# Command serialization
# ---------------------------------------------------------------------------


class TestCommandSerialization:
    """Concurrent calls are serialized via asyncio.Lock."""

    @pytest.mark.asyncio
    async def test_commands_are_serialized(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        """Multiple concurrent send_command calls should not interleave."""
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        # Track execution order
        execution_log: list[str] = []
        original_send = mock_netmiko_device.send_command

        def tracked_send(command: str, **kwargs: object) -> str:
            execution_log.append(f"start:{command}")
            result = original_send(command)
            execution_log.append(f"end:{command}")
            return result

        mock_netmiko_device.send_command = tracked_send

        # Launch concurrent commands
        tasks = [
            asyncio.create_task(client.send_command("show vlan")),
            asyncio.create_task(client.send_command("show version")),
            asyncio.create_task(client.send_command("show lldp neighbors")),
        ]
        await asyncio.gather(*tasks)

        # Verify serialization: each start must be followed by its end
        # before the next start
        for i in range(0, len(execution_log), 2):
            start = execution_log[i]
            end = execution_log[i + 1]
            cmd = start.split(":", 1)[1]
            assert end == f"end:{cmd}", "Commands were interleaved"


# ---------------------------------------------------------------------------
# Error mapping
# ---------------------------------------------------------------------------


class TestAuthFailure:
    """NetmikoAuthenticationException mapped to AuthenticationError."""

    @pytest.mark.asyncio
    async def test_auth_failure_raises_authentication_error(self) -> None:
        from netmiko.exceptions import NetmikoAuthenticationException

        with patch(
            "cisco.ssh.client.ConnectHandler",
            side_effect=NetmikoAuthenticationException("bad creds"),
        ):
            client = CiscoSSHClient(
                host="192.168.1.2",
                username="admin",
                password="wrong",
            )
            with pytest.raises(AuthenticationError) as exc_info:
                await client.connect()
            assert "authentication" in exc_info.value.message.lower()


class TestTimeout:
    """NetmikoTimeoutException mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_timeout_raises_network_error(self) -> None:
        from netmiko.exceptions import NetmikoTimeoutException

        with patch(
            "cisco.ssh.client.ConnectHandler",
            side_effect=NetmikoTimeoutException("connection timed out"),
        ):
            client = CiscoSSHClient(
                host="192.168.1.2",
                username="admin",
                password="password",
            )
            with pytest.raises(NetworkError) as exc_info:
                await client.connect()
            assert "timed out" in exc_info.value.message.lower()

    @pytest.mark.asyncio
    async def test_command_timeout_raises_network_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        from netmiko.exceptions import NetmikoTimeoutException

        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_command = MagicMock(
            side_effect=NetmikoTimeoutException("read timeout"),
        )

        with pytest.raises(NetworkError):
            await client.send_command("show vlan")


# ---------------------------------------------------------------------------
# Disconnection
# ---------------------------------------------------------------------------


class TestDisconnect:
    """Clean disconnection."""

    @pytest.mark.asyncio
    async def test_disconnect_calls_netmiko_disconnect(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        assert mock_netmiko_device._connected is True

        await client.disconnect()
        assert mock_netmiko_device._connected is False

    @pytest.mark.asyncio
    async def test_disconnect_clears_connection(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        await client.disconnect()
        assert client._connection is None


# ---------------------------------------------------------------------------
# get_client() factory
# ---------------------------------------------------------------------------


class TestGetClientFactory:
    """get_client() reads from env vars to create singleton."""

    def setup_method(self) -> None:
        """Reset the module-level singleton before each test."""
        import cisco.ssh.client as mod

        mod._client = None

    def test_get_client_reads_env_vars(self) -> None:
        env = {
            "CISCO_HOST": "10.0.0.1",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            client = get_client()
            assert client._host == "10.0.0.1"
            assert client._username == "admin"
            assert client._password == "s3cret"

    def test_get_client_with_enable_password(self) -> None:
        env = {
            "CISCO_HOST": "10.0.0.1",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
            "CISCO_ENABLE_PASSWORD": "enable_s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            client = get_client()
            assert client._enable_password == "enable_s3cret"

    def test_get_client_verify_host_key_default(self) -> None:
        env = {
            "CISCO_HOST": "10.0.0.1",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            client = get_client()
            assert client._verify_host_key is True

    def test_get_client_verify_host_key_disabled(self) -> None:
        env = {
            "CISCO_HOST": "10.0.0.1",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
            "CISCO_VERIFY_SSH_HOST_KEY": "false",
        }
        with patch.dict(os.environ, env, clear=True):
            client = get_client()
            assert client._verify_host_key is False

    def test_get_client_missing_host_raises(self) -> None:
        env = {
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises(
            AuthenticationError, match="CISCO_HOST"
        ):
            get_client()

    def test_get_client_missing_username_raises(self) -> None:
        env = {
            "CISCO_HOST": "10.0.0.1",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises(
            AuthenticationError, match="CISCO_SSH_USERNAME"
        ):
            get_client()

    def test_get_client_missing_password_raises(self) -> None:
        env = {
            "CISCO_HOST": "10.0.0.1",
            "CISCO_SSH_USERNAME": "admin",
        }
        with patch.dict(os.environ, env, clear=True), pytest.raises(
            AuthenticationError, match="CISCO_SSH_PASSWORD"
        ):
            get_client()

    def test_get_client_returns_singleton(self) -> None:
        env = {
            "CISCO_HOST": "10.0.0.1",
            "CISCO_SSH_USERNAME": "admin",
            "CISCO_SSH_PASSWORD": "s3cret",
        }
        with patch.dict(os.environ, env, clear=True):
            client1 = get_client()
            client2 = get_client()
            assert client1 is client2


# ---------------------------------------------------------------------------
# _build_device_params -- verify_host_key=False branch (lines 124-127)
# ---------------------------------------------------------------------------


class TestBuildDeviceParams:
    """Test _build_device_params with verify_host_key=False."""

    def test_verify_host_key_false_adds_params(self) -> None:
        """When verify_host_key=False, extra Paramiko params are set."""
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
            verify_host_key=False,
        )
        params = client._build_device_params()
        assert params["ssh_config_file"] is None
        assert params["allow_auto_change"] is True
        assert params["disabled_algorithms"] == {}

    def test_verify_host_key_true_no_extra_params(self) -> None:
        """When verify_host_key=True (default), no extra params added."""
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
            verify_host_key=True,
        )
        params = client._build_device_params()
        assert "ssh_config_file" not in params
        assert "allow_auto_change" not in params
        assert "disabled_algorithms" not in params


# ---------------------------------------------------------------------------
# _connect_sync -- OSError branch (lines 153-154)
# ---------------------------------------------------------------------------


class TestConnectOSError:
    """OSError during connect mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_os_error_raises_network_error(self) -> None:
        with patch(
            "cisco.ssh.client.ConnectHandler",
            side_effect=OSError("Connection refused"),
        ):
            client = CiscoSSHClient(
                host="192.168.1.2",
                username="admin",
                password="password",
            )
            with pytest.raises(NetworkError) as exc_info:
                await client.connect()
            assert "Connection refused" in exc_info.value.message
            assert exc_info.value.endpoint == "192.168.1.2"


# ---------------------------------------------------------------------------
# disconnect -- error during disconnect (lines 183-184)
# ---------------------------------------------------------------------------


class TestDisconnectError:
    """Error during disconnect is logged but ignored."""

    @pytest.mark.asyncio
    async def test_disconnect_error_ignored(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        # Make disconnect raise an error
        mock_netmiko_device.disconnect = MagicMock(side_effect=OSError("socket error"))

        # Should not raise -- error is swallowed
        await client.disconnect()
        # Connection should still be cleared
        assert client._connection is None


# ---------------------------------------------------------------------------
# connect -- already connected path (lines 173-174)
# ---------------------------------------------------------------------------


class TestConnectAlreadyConnected:
    """Calling connect() when already connected is a no-op."""

    @pytest.mark.asyncio
    async def test_connect_already_connected_is_noop(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        assert mock_netmiko_connect.call_count == 1

        # Second connect should be a no-op
        await client.connect()
        assert mock_netmiko_connect.call_count == 1


# ---------------------------------------------------------------------------
# is_connected / save_config / get_running_config (lines 204-212, 362, 372)
# ---------------------------------------------------------------------------


class TestIsConnected:
    """is_connected() returns connection liveness."""

    @pytest.mark.asyncio
    async def test_is_connected_when_connected(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        assert await client.is_connected() is True

    @pytest.mark.asyncio
    async def test_is_connected_when_not_connected(self) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        # Never called connect
        assert await client.is_connected() is False

    @pytest.mark.asyncio
    async def test_is_connected_when_is_alive_raises(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        # Make is_alive raise an exception
        mock_netmiko_device.is_alive = MagicMock(side_effect=OSError("broken"))
        assert await client.is_connected() is False


class TestSaveConfig:
    """save_config() delegates to send_command('write memory')."""

    @pytest.mark.asyncio
    async def test_save_config_returns_output(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        result = await client.save_config()
        assert "OK" in result


class TestGetRunningConfig:
    """get_running_config() delegates to send_command('show running-config')."""

    @pytest.mark.asyncio
    async def test_get_running_config_returns_output(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()
        result = await client.get_running_config()
        assert len(result) > 0


# ---------------------------------------------------------------------------
# send_command -- OSError and generic Exception paths (lines 281-290)
# ---------------------------------------------------------------------------


class TestSendCommandOSError:
    """OSError during send_command mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_send_command_os_error_raises_network_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_command = MagicMock(
            side_effect=OSError("Connection reset"),
        )

        with pytest.raises(NetworkError) as exc_info:
            await client.send_command("show vlan")
        assert "Connection lost" in exc_info.value.message
        # Connection should be cleared after OSError
        assert client._connection is None


class TestSendCommandGenericError:
    """Generic exception during send_command mapped to SSHCommandError."""

    @pytest.mark.asyncio
    async def test_send_command_generic_error_raises_ssh_command_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        from cisco.errors import SSHCommandError

        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_command = MagicMock(
            side_effect=RuntimeError("unexpected"),
        )

        with pytest.raises(SSHCommandError):
            await client.send_command("show vlan")


# ---------------------------------------------------------------------------
# send_config_set error paths (lines 317-347)
# ---------------------------------------------------------------------------


class TestSendConfigSetTimeout:
    """Timeout during send_config_set mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_send_config_set_timeout_raises_network_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        from netmiko.exceptions import NetmikoTimeoutException

        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_config_set = MagicMock(
            side_effect=NetmikoTimeoutException("config timeout"),
        )

        with pytest.raises(NetworkError):
            await client.send_config_set(["interface gi1", "shutdown"])
        assert client._connection is None


class TestSendConfigSetOSError:
    """OSError during send_config_set mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_send_config_set_os_error_raises_network_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_config_set = MagicMock(
            side_effect=OSError("Connection reset"),
        )

        with pytest.raises(NetworkError):
            await client.send_config_set(["interface gi1", "shutdown"])
        assert client._connection is None


class TestSendConfigSetGenericError:
    """Generic exception during send_config_set mapped to SSHCommandError."""

    @pytest.mark.asyncio
    async def test_send_config_set_generic_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        from cisco.errors import SSHCommandError

        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_config_set = MagicMock(
            side_effect=RuntimeError("unexpected"),
        )

        with pytest.raises(SSHCommandError):
            await client.send_config_set(["interface gi1", "shutdown"])


# ---------------------------------------------------------------------------
# _ensure_connected -- reconnect logic (lines 281-290 area)
# ---------------------------------------------------------------------------


class TestEnsureConnectedReconnect:
    """_ensure_connected reconnects when connection is stale."""

    @pytest.mark.asyncio
    async def test_ensure_connected_reconnects_when_connection_none(
        self, mock_netmiko_connect: MagicMock
    ) -> None:
        """If _connection is None, _ensure_connected should reconnect."""
        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        # Don't call connect() -- _connection is None
        # send_command should trigger _ensure_connected -> reconnect
        output = await client.send_command("show vlan")
        assert "default" in output
        assert mock_netmiko_connect.call_count == 1


# ---------------------------------------------------------------------------
# send_command -- ReadTimeout path
# ---------------------------------------------------------------------------


class TestSendCommandReadTimeout:
    """ReadTimeout during send_command mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_send_command_read_timeout_raises_network_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        from netmiko.exceptions import ReadTimeout

        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_command = MagicMock(
            side_effect=ReadTimeout("read timed out"),
        )

        with pytest.raises(NetworkError):
            await client.send_command("show vlan")
        assert client._connection is None


# ---------------------------------------------------------------------------
# send_config_set -- ReadTimeout path
# ---------------------------------------------------------------------------


class TestSendConfigSetReadTimeout:
    """ReadTimeout during send_config_set mapped to NetworkError."""

    @pytest.mark.asyncio
    async def test_send_config_set_read_timeout_raises_network_error(
        self, mock_netmiko_connect: MagicMock, mock_netmiko_device: MockNetmikoDevice
    ) -> None:
        from netmiko.exceptions import ReadTimeout

        client = CiscoSSHClient(
            host="192.168.1.2",
            username="admin",
            password="password",
        )
        await client.connect()

        mock_netmiko_device.send_config_set = MagicMock(
            side_effect=ReadTimeout("read timed out"),
        )

        with pytest.raises(NetworkError):
            await client.send_config_set(["interface gi1", "shutdown"])
        assert client._connection is None
