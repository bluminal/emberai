# Connectivity Deployment Guide

This guide covers how to connect the Netex plugins to your OPNsense gateway and UniFi controller. The core challenge: the plugins run as MCP servers inside Claude Code, but your network devices are on your local network behind a firewall.

## Architecture

```
+------------------+     Internet      +------------------+
|  Claude / AI     |  <------------>   |  Your Network    |
|  (MCP host)      |                   |                  |
|  +------------+  |                   |  +------------+  |
|  | netex      |  |      API calls    |  | OPNsense   |  |
|  | opnsense   |  | ----------------> |  | gateway    |  |
|  | unifi      |  |                   |  +------------+  |
|  +------------+  |                   |  +------------+  |
|                  |      API calls    |  | UniFi      |  |
|                  | ----------------> |  | controller |  |
+------------------+                   +------------------+
```

## Option 1: VPN Tunnel (Recommended)

The most secure option. The MCP server connects to your network via a VPN tunnel, gaining direct Layer 3 access to your OPNsense and UniFi management interfaces.

### WireGuard (Preferred)

1. **Set up a WireGuard server on OPNsense.** See the [WireGuard Peer workflow](../opnsense/workflows/wireguard-peer.md) for detailed instructions.

2. **Configure the tunnel subnet** to include routes to your management VLAN:
   ```ini
   [Interface]
   PrivateKey = <mcp-server-private-key>
   Address = 10.200.0.2/32
   DNS = 10.10.0.1

   [Peer]
   PublicKey = <opnsense-public-key>
   Endpoint = your-public-ip:51820
   AllowedIPs = 10.10.0.0/24, 10.20.0.0/24
   PersistentKeepalive = 25
   ```

3. **Set environment variables** on the MCP server:
   ```bash
   OPNSENSE_HOST=https://10.10.0.1
   OPNSENSE_API_KEY=your-api-key
   OPNSENSE_API_SECRET=your-api-secret
   OPNSENSE_VERIFY_SSL=false  # if using self-signed cert

   UNIFI_LOCAL_HOST=10.10.0.2
   UNIFI_LOCAL_KEY=your-unifi-api-key
   ```

4. **Firewall rules:** Ensure the VPN subnet can reach OPNsense API (port 443) and UniFi controller (port 8443 or 443).

### IPSec or OpenVPN

Similar setup, but WireGuard is preferred for its simplicity and performance. The key requirement is the same: the MCP server needs Layer 3 reachability to your management IPs.

## Option 2: Reverse Proxy

If you cannot set up a VPN, expose the OPNsense and UniFi APIs through a reverse proxy with strong authentication.

### Caddy Example

```
opnsense-api.yourdomain.com {
    reverse_proxy https://10.10.0.1:443 {
        transport http {
            tls_insecure_skip_verify  # if OPNsense uses self-signed
        }
    }
    basicauth {
        mcp-server $2a$14$hashed-password
    }
    tls {
        dns cloudflare {env.CF_API_TOKEN}
    }
}

unifi-api.yourdomain.com {
    reverse_proxy https://10.10.0.2:8443 {
        transport http {
            tls_insecure_skip_verify
        }
    }
    basicauth {
        mcp-server $2a$14$hashed-password
    }
}
```

### Nginx Example

```nginx
server {
    listen 443 ssl;
    server_name opnsense-api.yourdomain.com;

    ssl_certificate /etc/ssl/certs/opnsense-api.pem;
    ssl_certificate_key /etc/ssl/private/opnsense-api.key;

    auth_basic "MCP Access";
    auth_basic_user_file /etc/nginx/.htpasswd;

    location / {
        proxy_pass https://10.10.0.1;
        proxy_ssl_verify off;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

### Security Considerations

- Always use TLS (HTTPS) for the reverse proxy
- Use strong authentication (client certificates preferred over basic auth)
- Restrict access by source IP if possible
- Consider rate limiting
- Monitor access logs for unauthorized attempts

## Option 3: Cloudflare Tunnel / Site Magic

If you use Cloudflare, you can expose internal services via Cloudflare Tunnel (formerly Argo Tunnel) without opening ports on your firewall.

### Setup

1. Install `cloudflared` on a host on your management VLAN
2. Create a tunnel: `cloudflared tunnel create netex-access`
3. Configure routes to your management IPs:

```yaml
# ~/.cloudflared/config.yml
tunnel: <tunnel-id>
credentials-file: /root/.cloudflared/<tunnel-id>.json

ingress:
  - hostname: opnsense-api.yourdomain.com
    service: https://10.10.0.1
    originRequest:
      noTLSVerify: true
  - hostname: unifi-api.yourdomain.com
    service: https://10.10.0.2:8443
    originRequest:
      noTLSVerify: true
  - service: http_status:404
```

4. Add DNS records in Cloudflare pointing to the tunnel
5. Configure Cloudflare Access policies to restrict who can reach these endpoints

### Advantages

- No inbound ports opened on your firewall
- Cloudflare handles TLS termination
- Cloudflare Access provides identity-based access control
- Built-in DDoS protection

## Environment Variable Reference

| Variable | Plugin | Description | Example |
|---|---|---|---|
| `OPNSENSE_HOST` | opnsense | OPNsense URL (include scheme) | `https://10.10.0.1` |
| `OPNSENSE_API_KEY` | opnsense | API key (Basic Auth username) | `+mIZ...` |
| `OPNSENSE_API_SECRET` | opnsense | API secret (Basic Auth password) | `X8Wf...` |
| `OPNSENSE_VERIFY_SSL` | opnsense | SSL verification | `false` for self-signed |
| `UNIFI_LOCAL_HOST` | unifi | UniFi local gateway IP | `10.10.0.2` |
| `UNIFI_LOCAL_KEY` | unifi | Local gateway API key | `ulp_...` |
| `UNIFI_API_KEY` | unifi | Cloud V1 / Site Manager key | `UA_...` |
| `NETEX_WRITE_ENABLED` | netex | Enable cross-vendor writes | `true` |

## Verifying Connectivity

After setting up connectivity, run the health check for each plugin:

```bash
# Check opnsense connectivity
opnsense-server --check

# Check unifi connectivity
unifi-server --check

# Check netex umbrella (discovers installed plugins)
netex-server --check
```

All three should report PASS. If any fail, check:
1. Network reachability (can the MCP server reach the management IPs?)
2. Credentials (are the API keys correct?)
3. Firewall rules (is the management API port open from the MCP server's IP?)
4. TLS issues (is SSL verification failing on self-signed certs?)

## Security Best Practices

1. **Principle of least privilege:** Create dedicated API keys for the MCP server with minimal required permissions
2. **Network segmentation:** Place the MCP server's VPN endpoint on the management VLAN, not the trusted/general VLAN
3. **Rotate credentials:** Rotate API keys periodically
4. **Monitor access:** Check OPNsense and UniFi logs for unusual API activity
5. **Restrict write access:** Only enable `*_WRITE_ENABLED` when actively making changes
