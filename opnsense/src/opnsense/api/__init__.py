"""OPNsense REST API client modules.

Public API::

    from opnsense.api import OPNsenseClient
    from opnsense.api.response import NormalizedResponse, normalize_response
"""

from opnsense.api.opnsense_client import OPNsenseClient
from opnsense.api.response import NormalizedResponse, normalize_response

__all__ = [
    "NormalizedResponse",
    "OPNsenseClient",
    "normalize_response",
]
