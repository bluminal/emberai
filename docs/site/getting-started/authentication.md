# Authentication

The unifi plugin supports two API tiers, each with its own authentication mechanism. For most users, the **Local Gateway API** is the recommended starting point — it provides direct access to your UniFi controller without depending on Ubiquiti's cloud services.

## Local Gateway API (Recommended)

The Local Gateway API connects directly to your UniFi controller (Dream Machine, Cloud Key, or self-hosted Network Server) over your local network.

### Step 1: Create a Local API Key

1. Open your UniFi controller's web interface (e.g., `https://192.168.1.1`)
2. Navigate to **Settings > Control Plane > Advanced**
3. Under **API Keys**, click **Create API Key**
4. Give it a descriptive name (e.g., `netex-readonly`)
5. Copy the generated API key — it will not be shown again

!!! warning "API key permissions"
    The API key inherits the permissions of the account that creates it. For
    read-only operations (scanning, health checks, client lookups), a standard
    admin account is sufficient. Write operations require a full admin account.

### Step 2: Set Environment Variables

Create a `.env` file in your project directory or export the variables in your shell:

```bash
# Required — Local Gateway API
UNIFI_LOCAL_HOST=192.168.1.1      # IP or hostname of your UniFi controller
UNIFI_LOCAL_KEY=your-api-key-here  # API key from Step 1
```

Or export directly:

```bash
export UNIFI_LOCAL_HOST=192.168.1.1
export UNIFI_LOCAL_KEY=your-api-key-here
```

### Step 3: Test Connectivity

```bash
unifi-server --check
```

Expected output on success:

```
[INFO] Configuration loaded successfully
[INFO] Local Gateway API: connected (192.168.1.1)
[INFO] Health check passed
```

## Cloud V1 API (Optional)

The Cloud V1 API connects through Ubiquiti's cloud infrastructure. This is useful for managing multiple sites or when the controller is not directly reachable on the local network.

### Create a Cloud API Key

1. Go to [unifi.ui.com](https://unifi.ui.com)
2. Navigate to your account settings
3. Generate an API key under the developer section

### Set the Environment Variable

```bash
UNIFI_API_KEY=your-cloud-api-key-here
```

The cloud API key is used for Cloud V1 endpoints and Site Manager EA endpoints. It is separate from the Local Gateway key.

## Environment Variable Summary

| Variable | Required | Purpose |
|----------|----------|---------|
| `UNIFI_LOCAL_HOST` | Yes (for local API) | IP or hostname of the UniFi controller |
| `UNIFI_LOCAL_KEY` | Yes (for local API) | Local Gateway API key |
| `UNIFI_API_KEY` | No | Cloud V1 / Site Manager API key |
| `UNIFI_WRITE_ENABLED` | No | Set to `"true"` to enable write operations (default: `false`) |
| `NETEX_CACHE_TTL` | No | Cache TTL in seconds (default: `300`) |

For the complete list of environment variables across all plugins, see [Environment Variables](../reference/environment-variables.md).

## Troubleshooting

### "Connection refused" or timeout

- Verify the controller IP is correct and reachable: `ping 192.168.1.1`
- Ensure you are on the same network as the controller, or have a VPN/route configured
- Check that the UniFi controller is running and the API is enabled

### "401 Unauthorized"

- Verify the API key is correct — copy it again from the controller settings
- Check that the API key has not been revoked
- Ensure the API key was created by an account with sufficient permissions

### "SSL certificate verify failed"

The Local Gateway API uses a self-signed certificate by default. The unifi plugin accepts self-signed certificates for local connections. If you see this error, ensure you are connecting to the correct host.

## Next Steps

- [Quick Start](quick-start.md) — run your first network scan
- [Safety & Human Supervision](safety.md) — understand write safety before enabling `UNIFI_WRITE_ENABLED`
