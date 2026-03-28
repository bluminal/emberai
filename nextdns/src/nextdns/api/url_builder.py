# SPDX-License-Identifier: MIT
"""URL construction utilities for NextDNS API endpoints.

Builds URL paths for the NextDNS REST API's nested resource pattern.
Profiles are the top-level resource, with sub-resources accessed via
dotted path notation that maps to slash-separated URL segments.

Examples::

    profile_url("abc123")
    # => "/profiles/abc123"

    sub_resource_url("abc123", "security")
    # => "/profiles/abc123/security"

    sub_resource_url("abc123", "privacy.blocklists")
    # => "/profiles/abc123/privacy/blocklists"

    array_child_url("abc123", "denylist", "bad.com")
    # => "/profiles/abc123/denylist/bad.com"
"""

from __future__ import annotations


def profile_url(profile_id: str) -> str:
    """Return the URL path for a profile.

    Args:
        profile_id: The NextDNS profile identifier (e.g. ``"abc123"``).

    Returns:
        URL path: ``/profiles/{id}``
    """
    return f"/profiles/{profile_id}"


def sub_resource_url(profile_id: str, path: str) -> str:
    """Build a sub-resource URL from a dotted path.

    Dots in the path are converted to URL path separators, enabling
    a compact notation for nested API resources.

    Args:
        profile_id: The NextDNS profile identifier.
        path: Dotted path to the sub-resource (e.g. ``"security"``,
            ``"privacy.blocklists"``, ``"parentalControl.services"``).

    Returns:
        URL path: ``/profiles/{id}/{path_segments}``

    Examples::

        sub_resource_url("abc", "security")
        # => "/profiles/abc/security"

        sub_resource_url("abc", "privacy.blocklists")
        # => "/profiles/abc/privacy/blocklists"

        sub_resource_url("abc", "parentalControl.services")
        # => "/profiles/abc/parentalControl/services"
    """
    segments = path.split(".")
    return f"/profiles/{profile_id}/{'/'.join(segments)}"


def array_child_url(profile_id: str, path: str, item_id: str) -> str:
    """Build URL for a specific item in an array sub-resource.

    Combines :func:`sub_resource_url` with an item identifier to address
    individual entries in list-type sub-resources (denylist, allowlist,
    blocklists, etc.).

    Args:
        profile_id: The NextDNS profile identifier.
        path: Dotted path to the array sub-resource.
        item_id: Identifier of the specific item (e.g. a domain name
            or blocklist ID).

    Returns:
        URL path: ``/profiles/{id}/{path_segments}/{item_id}``

    Examples::

        array_child_url("abc", "denylist", "bad.com")
        # => "/profiles/abc/denylist/bad.com"

        array_child_url("abc", "privacy.blocklists", "oisd")
        # => "/profiles/abc/privacy/blocklists/oisd"
    """
    base = sub_resource_url(profile_id, path)
    return f"{base}/{item_id}"
