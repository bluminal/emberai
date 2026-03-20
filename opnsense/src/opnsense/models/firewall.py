"""Firewall models for OPNsense firewall configuration.

Maps from OPNsense API responses for firewall rules, aliases, and NAT rules
to normalized Python representations.
"""

from pydantic import BaseModel, ConfigDict, Field


class FirewallRule(BaseModel):
    """An OPNsense firewall filter rule.

    Returned by ``opnsense__firewall__list_rules()`` and
    ``opnsense__firewall__get_rule(uuid)``.

    API field mapping (``/api/firewall/filter/searchRule``):
        ``uuid``        -> ``uuid``
        ``description`` -> ``description``
        ``action``      -> ``action``
        ``enabled``     -> ``enabled``
        ``direction``   -> ``direction``
        ``ipprotocol``  -> ``protocol``
        ``source_net``  -> ``source``
        ``destination_net`` -> ``destination``
        ``log``         -> ``log``
        ``sequence``    -> ``position``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this firewall rule",
    )
    description: str = Field(
        default="",
        description="Human-readable rule description",
    )
    action: str = Field(
        description="Rule action: 'pass', 'block', or 'reject'",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the rule is administratively enabled",
    )
    direction: str = Field(
        default="in",
        description="Traffic direction: 'in' or 'out'",
    )
    protocol: str = Field(
        default="any",
        alias="ipprotocol",
        description="IP protocol (e.g. 'TCP', 'UDP', 'ICMP', 'any')",
    )
    source: str = Field(
        default="any",
        alias="source_net",
        description="Source address or alias (e.g. '192.168.1.0/24', 'any', alias name)",
    )
    destination: str = Field(
        default="any",
        alias="destination_net",
        description="Destination address or alias",
    )
    log: bool = Field(
        default=False,
        description="Whether matching packets are logged",
    )
    position: int | None = Field(
        default=None,
        alias="sequence",
        description="Rule position in the filter chain (lower = evaluated first)",
    )
    interface: str = Field(
        default="",
        description="Interface this rule applies to (e.g. 'lan', 'wan', 'opt1')",
    )


class Alias(BaseModel):
    """An OPNsense firewall alias (named address/port group).

    Returned by ``opnsense__firewall__list_aliases()``.

    API field mapping (``/api/firewall/alias/searchItem``):
        ``uuid``        -> ``uuid``
        ``name``        -> ``name``
        ``type``        -> ``alias_type``
        ``description`` -> ``description``
        ``content``     -> ``content``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this alias",
    )
    name: str = Field(
        description="Alias name used in firewall rules (e.g. 'trusted_hosts')",
    )
    alias_type: str = Field(
        alias="type",
        description="Alias type: 'host', 'network', 'port', or 'url'",
    )
    description: str = Field(
        default="",
        description="Human-readable alias description",
    )
    content: str = Field(
        default="",
        description="Alias content (comma-separated CIDRs, IPs, ports, or URLs)",
    )


class NATRule(BaseModel):
    """An OPNsense source NAT rule.

    Returned by ``opnsense__firewall__list_nat_rules()``.

    API field mapping (``/api/firewall/s_nat/searchRule``):
        ``uuid``        -> ``uuid``
        ``description`` -> ``description``
        ``interface``   -> ``interface``
        ``ipprotocol``  -> ``protocol``
        ``source_net``  -> ``source``
        ``destination_net`` -> ``destination``
        ``target``      -> ``target``
        ``target_port`` -> ``target_port``
        ``enabled``     -> ``enabled``
    """

    model_config = ConfigDict(strict=True, populate_by_name=True)

    uuid: str = Field(
        description="Unique identifier for this NAT rule",
    )
    description: str = Field(
        default="",
        description="Human-readable NAT rule description",
    )
    interface: str = Field(
        default="",
        description="Interface this NAT rule applies to",
    )
    protocol: str = Field(
        default="any",
        alias="ipprotocol",
        description="IP protocol (e.g. 'TCP', 'UDP', 'any')",
    )
    source: str = Field(
        default="any",
        alias="source_net",
        description="Source address or network",
    )
    destination: str = Field(
        default="any",
        alias="destination_net",
        description="Destination address or network",
    )
    target: str = Field(
        default="",
        description="NAT target address (translated destination)",
    )
    target_port: str = Field(
        default="",
        description="NAT target port (translated port)",
    )
    enabled: bool = Field(
        default=True,
        description="Whether the NAT rule is administratively enabled",
    )
