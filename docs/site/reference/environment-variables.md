# Environment Variables

All environment variables used across the three Netex plugins. Variables can be set in a `.env` file in the project directory, exported in your shell, or configured through your deployment environment.

## UniFi Plugin

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `UNIFI_LOCAL_HOST` | Yes | — | IP or hostname of the UniFi local gateway (e.g., `192.168.1.1`) |
| `UNIFI_LOCAL_KEY` | Yes | — | API key for the UniFi Local Gateway API |
| `UNIFI_API_KEY` | No | — | API key for UniFi Cloud V1 and Site Manager EA APIs |
| `UNIFI_WRITE_ENABLED` | No | `false` | Set to `"true"` to enable write operations. See [Write Safety](write-safety.md). |

## OPNsense Plugin

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `OPNSENSE_HOST` | Yes | — | OPNsense instance URL, including scheme (e.g., `https://10.0.0.1`) |
| `OPNSENSE_API_KEY` | Yes | — | API key (used as HTTP Basic Auth username) |
| `OPNSENSE_API_SECRET` | Yes | — | API secret (used as HTTP Basic Auth password) |
| `OPNSENSE_VERIFY_SSL` | No | `true` | Set to `"false"` to accept self-signed TLS certificates |
| `OPNSENSE_WRITE_ENABLED` | No | `false` | Set to `"true"` to enable write operations. See [Write Safety](write-safety.md). |

## Netex Umbrella

| Variable | Required | Default | Purpose |
|----------|----------|---------|---------|
| `NETEX_WRITE_ENABLED` | No | `false` | Set to `"true"` to enable cross-vendor write operations. See [Write Safety](write-safety.md). |
| `NETEX_CACHE_TTL` | No | `300` | Cache TTL in seconds for API responses. Set to `0` to disable caching. |

## Notes

### Write Safety Variables

The three write-enable variables (`UNIFI_WRITE_ENABLED`, `OPNSENSE_WRITE_ENABLED`, `NETEX_WRITE_ENABLED`) are independent. Enabling writes on one plugin does not enable them on another.

Even with the environment variable set to `"true"`, write operations still require the `--apply` flag and operator confirmation. The environment variable is the first of three gates — see [Write Safety](write-safety.md) for the full model.

### Cache TTL

The `NETEX_CACHE_TTL` variable controls how long API responses are cached in memory. This reduces load on the UniFi controller and OPNsense instance during repeated queries. The default of 300 seconds (5 minutes) is appropriate for most use cases.

Set to `0` to disable caching entirely — useful during debugging or when you need real-time data for every query.

### Self-Signed Certificates

Both UniFi controllers and OPNsense instances commonly use self-signed TLS certificates. The unifi plugin accepts self-signed certificates for local connections by default. For OPNsense, set `OPNSENSE_VERIFY_SSL=false` explicitly.

!!! warning "Production environments"
    Disabling SSL verification is acceptable for local lab and home network
    management. For production or remote access scenarios, configure proper
    TLS certificates on your controller and firewall.
