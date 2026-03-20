# Authentication

Each plugin in the Netex suite uses its own authentication mechanism. This page covers setup for both the **unifi** plugin (UniFi networks) and the **opnsense** plugin (OPNsense firewalls). Configure only the plugins you use -- they are fully independent.

---

## UniFi Plugin

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

### UniFi Environment Variable Summary

| Variable | Required | Purpose |
|----------|----------|---------|
| `UNIFI_LOCAL_HOST` | Yes (for local API) | IP or hostname of the UniFi controller |
| `UNIFI_LOCAL_KEY` | Yes (for local API) | Local Gateway API key |
| `UNIFI_API_KEY` | No | Cloud V1 / Site Manager API key |
| `UNIFI_WRITE_ENABLED` | No | Set to `"true"` to enable write operations (default: `false`) |

### UniFi Troubleshooting

**"Connection refused" or timeout:**

- Verify the controller IP is correct and reachable: `ping 192.168.1.1`
- Ensure you are on the same network as the controller, or have a VPN/route configured
- Check that the UniFi controller is running and the API is enabled

**"401 Unauthorized":**

- Verify the API key is correct — copy it again from the controller settings
- Check that the API key has not been revoked
- Ensure the API key was created by an account with sufficient permissions

**"SSL certificate verify failed":**

The Local Gateway API uses a self-signed certificate by default. The unifi plugin accepts self-signed certificates for local connections. If you see this error, ensure you are connecting to the correct host.

---

## OPNsense Plugin

The opnsense plugin connects to your OPNsense firewall's local REST API using HTTP Basic Authentication with an API key and secret pair.

### Step 1: Create an API Key and Secret

1. Log into your OPNsense web interface (e.g., `https://192.168.1.1`)
2. Navigate to **System > Access > Users**
3. Click the edit icon next to the user you want to create an API key for (or create a dedicated API user)
4. Scroll to the **API keys** section
5. Click the **+** button to generate a new key pair
6. A file will be downloaded containing the API key and secret -- save it securely
7. The key and secret will not be shown again

!!! warning "API key privileges"
    The API key inherits the **Effective Privileges** of the user that owns it.
    For read-only operations (scanning, health checks, audits), the user needs
    read access to the relevant OPNsense modules (Interfaces, Firewall, Routes,
    VPN, Services, Diagnostics, Firmware). Write operations require corresponding
    write privileges.

    Check the user's effective privileges at **System > Access > Users >
    [user] > Effective Privileges**.

!!! tip "Dedicated API user"
    Create a dedicated user (e.g., `netex-api`) for the opnsense plugin rather
    than using a personal admin account. This makes it easier to manage
    privileges and audit API access.

### Step 2: Set Environment Variables

Create a `.env` file in your project directory or export the variables in your shell:

```bash
# Required — OPNsense API
OPNSENSE_HOST=https://192.168.1.1       # URL of your OPNsense instance (include https://)
OPNSENSE_API_KEY=your-api-key-here       # API key (used as Basic Auth username)
OPNSENSE_API_SECRET=your-api-secret-here # API secret (used as Basic Auth password)
```

Or export directly:

```bash
export OPNSENSE_HOST="https://192.168.1.1"
export OPNSENSE_API_KEY="your-api-key-here"
export OPNSENSE_API_SECRET="your-api-secret-here"
```

!!! note "Include the scheme"
    `OPNSENSE_HOST` must include the URL scheme (`https://`). OPNsense requires
    HTTPS for API access.

### Step 3: SSL Verification for Self-Signed Certificates

OPNsense uses a self-signed TLS certificate by default. If you have not installed a trusted certificate, the plugin will fail with an SSL verification error.

To disable SSL verification for self-signed certs:

```bash
export OPNSENSE_VERIFY_SSL="false"
```

!!! warning "Security consideration"
    Disabling SSL verification means the connection is still encrypted but
    the server's identity is not verified. This is acceptable for local
    network connections to a known OPNsense instance. For production
    deployments, install a trusted certificate on OPNsense and keep
    verification enabled.

### Step 4: Test Connectivity

```bash
opnsense-server --check
```

Expected output on success:

```
[INFO] Configuration loaded successfully
[INFO] OPNsense API: connected (https://192.168.1.1)
[INFO] Health check passed
```

### OPNsense Environment Variable Summary

| Variable | Required | Purpose |
|----------|----------|---------|
| `OPNSENSE_HOST` | Yes | URL of the OPNsense instance (include `https://`) |
| `OPNSENSE_API_KEY` | Yes | API key (Basic Auth username) |
| `OPNSENSE_API_SECRET` | Yes | API secret (Basic Auth password) |
| `OPNSENSE_WRITE_ENABLED` | No | Set to `"true"` to enable write operations (default: `false`) |
| `OPNSENSE_VERIFY_SSL` | No | Set to `"false"` for self-signed certs (default: `true`) |

### OPNsense Troubleshooting

**"Connection refused" or timeout:**

- Verify the OPNsense IP is correct and reachable: `ping 192.168.1.1`
- Ensure the web UI is accessible at the same URL in a browser
- Check that the OPNsense API is not disabled (it is enabled by default)

**"401 Unauthorized":**

- Verify the API key and secret are correct -- re-download the key file from OPNsense if needed
- Check that the API key has not been revoked or the owning user disabled
- Ensure you are using the API key as the username and the API secret as the password (not reversed)

**"403 Forbidden":**

- The API key owner lacks Effective Privileges for the requested resource
- Navigate to **System > Access > Users > [user] > Effective Privileges** and grant access to the required modules
- The error response typically indicates which resource was denied

**"SSL certificate verify failed":**

- Set `OPNSENSE_VERIFY_SSL=false` for self-signed certificates
- Or install a trusted certificate on OPNsense (System > Trust > Certificates)

---

## Shared Environment Variables

| Variable | Purpose |
|----------|---------|
| `NETEX_CACHE_TTL` | Cache TTL in seconds (default: `300`). Applies to all plugins. |

For the complete list of environment variables across all plugins, see [Environment Variables](../reference/environment-variables.md).

## Next Steps

- [Quick Start](quick-start.md) — run your first network scan
- [Safety & Human Supervision](safety.md) — understand write safety before enabling write operations
