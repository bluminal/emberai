# Authentication

This guide covers how to obtain and configure API keys for each plugin in the Netex suite.

---

## OPNsense

### Getting Your API Key

1. Log in to your OPNsense web interface
2. Navigate to **System > Access > Users**
3. Select the user for API access (or create a dedicated API user)
4. Scroll to **API keys** and click **+** to create a new key
5. Download the `apikey.txt` file containing the key and secret

### Configuration

Set the required environment variables:

```bash
OPNSENSE_HOST=https://10.10.0.1        # Include the scheme
OPNSENSE_API_KEY=your-api-key           # From apikey.txt (first line)
OPNSENSE_API_SECRET=your-api-secret     # From apikey.txt (second line)
```

### Optional Configuration

```bash
OPNSENSE_VERIFY_SSL=false               # Set to "false" for self-signed certs
OPNSENSE_USERNAME=admin                 # Web UI username (for legacy page operations)
OPNSENSE_PASSWORD=your-password         # Web UI password (for legacy page operations)
```

### Optional: Enable Write Operations

```bash
OPNSENSE_WRITE_ENABLED=true
```

### Verify Connection

```bash
opnsense-server --check
```

### Security Notes

- Create a dedicated API user with minimal required permissions
- The API key uses HTTP Basic Auth (key as username, secret as password)
- Write operations require explicit opt-in via `OPNSENSE_WRITE_ENABLED`
- OPNsense separates write (save config) from reconfigure (apply to live) -- both are gated
- Rotate API keys periodically

---

## UniFi

### Getting Your API Key

#### Local Gateway API (Phase 1)

1. Open the UniFi Network web interface on your gateway
2. Navigate to **Settings > System > Advanced**
3. Enable **API Access** if not already enabled
4. Generate a new API key and copy it

#### Cloud V1 / Site Manager (Phase 2)

1. Log in to [account.ui.com](https://account.ui.com)
2. Navigate to **API Keys**
3. Create a new key with appropriate scopes
4. Copy the generated key

### Configuration

Set the required environment variables:

```bash
UNIFI_LOCAL_HOST=192.168.1.1            # IP or hostname of the gateway
UNIFI_LOCAL_KEY=your-local-api-key      # Local Gateway API key
```

For Cloud V1 / Site Manager access (Phase 2):

```bash
UNIFI_API_KEY=your-cloud-api-key        # Cloud V1 / Site Manager key
```

### Optional: Enable Write Operations

```bash
UNIFI_WRITE_ENABLED=true
```

### Verify Connection

```bash
unifi-server --check
```

### Security Notes

- The Local Gateway API key provides full access to the local site
- Cloud V1 keys may have cross-site access depending on account scope
- Write operations require explicit opt-in via `UNIFI_WRITE_ENABLED`
- Place the MCP server on the management VLAN for local gateway access
- See [Connectivity Guide](connectivity.md) for VPN and reverse proxy options

---

## NextDNS

### Getting Your API Key

1. Log in to [my.nextdns.io](https://my.nextdns.io)
2. Click your email address or avatar in the top-right corner to open account settings
3. Scroll to the **API** section at the bottom of the account page
4. Copy your API key

### Configuration

Set the required environment variable:

```bash
NEXTDNS_API_KEY=your-api-key-here
```

### Optional: Enable Write Operations

To allow profile modifications (security settings, blocklists, parental controls, deny/allow lists):

```bash
NEXTDNS_WRITE_ENABLED=true
```

### Verify Connection

```bash
nextdns-server --check
```

### Security Notes

- The API key provides full access to **all** NextDNS profiles on the account
- There is no per-profile key scoping -- anyone with the key can read and (if writes are enabled) modify all profiles
- Write operations require explicit opt-in via `NEXTDNS_WRITE_ENABLED`
- Profile deletion requires an additional `--delete-profile` safety flag beyond the standard write gate
- Log clearing requires an additional `--clear-logs` safety flag beyond the standard write gate
- The API is rate-limited; the plugin respects 429 responses with exponential backoff

---

## Netex (Umbrella)

The netex umbrella plugin does not have its own API credentials. It discovers installed vendor plugins and uses their credentials for cross-vendor operations.

### Configuration

```bash
NETEX_WRITE_ENABLED=true                # Enable cross-vendor write operations
NETEX_CACHE_TTL=300                     # Cache TTL in seconds (default: 300)
```

### Verify Connection

```bash
netex-server --check
```

This will discover all installed vendor plugins and verify their connectivity.

---

## Environment Variable Summary

| Variable | Plugin | Required | Description |
|----------|--------|----------|-------------|
| `OPNSENSE_HOST` | opnsense | Yes | OPNsense instance URL (include scheme) |
| `OPNSENSE_API_KEY` | opnsense | Yes | API key (Basic Auth username) |
| `OPNSENSE_API_SECRET` | opnsense | Yes | API secret (Basic Auth password) |
| `OPNSENSE_VERIFY_SSL` | opnsense | No | Set to `"false"` for self-signed certs |
| `OPNSENSE_USERNAME` | opnsense | No | Web UI username (legacy page operations) |
| `OPNSENSE_PASSWORD` | opnsense | No | Web UI password (legacy page operations) |
| `OPNSENSE_WRITE_ENABLED` | opnsense | No | Enable write operations |
| `UNIFI_LOCAL_HOST` | unifi | Yes | IP/hostname of UniFi local gateway |
| `UNIFI_LOCAL_KEY` | unifi | Yes | API key for local gateway |
| `UNIFI_API_KEY` | unifi | Phase 2 | API key for Cloud V1 / Site Manager |
| `UNIFI_WRITE_ENABLED` | unifi | No | Enable write operations |
| `NEXTDNS_API_KEY` | nextdns | Yes | API key from my.nextdns.io/account |
| `NEXTDNS_WRITE_ENABLED` | nextdns | No | Enable write operations |
| `NETEX_WRITE_ENABLED` | netex | No | Enable cross-vendor write operations |
| `NETEX_CACHE_TTL` | netex | No | Cache TTL override in seconds (default: 300) |
