# Coturn on the existing EC2 instance

Use this alongside the existing API. The TURN listener uses its own ports; do not route it through the API HTTP proxy or a CDN. An Elastic IP avoids having to reconfigure TURN when the instance's public IP changes.

## Provisioning

These commands target Ubuntu/Debian; confirm the instance OS before running. Install Coturn with `sudo apt-get update` and `sudo apt-get install coturn`. Inspect and preserve any existing `/etc/turnserver.conf` and active TURN service before replacing configuration.

Generate one secret on the server with `openssl rand -hex 32`. Keep it in the server configuration, not source control or browser code. Replace `PUBLIC_IP`, `PRIVATE_IP`, and `SHARED_SECRET` in `turnserver.conf.example`, then install it as `/etc/turnserver.conf` readable only by root and the Coturn service account. Set `WEBRTC_TURN_SECRET` to the identical secret in the backend `.env`.

Set these backend environment values using the instance's real Elastic/public IP:

```dotenv
WEBRTC_TURN_URLS=turn:PUBLIC_IP:3478?transport=udp,turn:PUBLIC_IP:3478?transport=tcp
WEBRTC_TURN_SECRET=THE_SAME_GENERATED_SECRET
WEBRTC_TURN_TTL=3600
```

Keep the existing STUN entry in `WEBRTC_ICE_SERVERS`. Django appends TURN automatically and issues separate credentials for each signed-in user, valid for one hour. The shared secret stays on the server. Keep instance time synchronized so those expiry timestamps agree.

In the EC2 security group and any instance firewall, allow inbound TCP 3478, UDP 3478, and UDP 49160–49260 from callers on the internet. Ensure outbound traffic and any custom network ACL also permit relay traffic and responses. Keep the existing application ports and SSH rules as configured. Coturn's external/private IP mapping must match the instance; both public address and private address are required behind EC2 NAT.

Enable and restart the Coturn service with `sudo systemctl enable --now coturn` and `sudo systemctl restart coturn`, then restart the existing Django API service so it picks up the TURN environment. Check `sudo systemctl status coturn` and `sudo journalctl -u coturn --since '10 minutes ago'` for startup errors. No frontend secret or TURN-specific UI change is needed.

## Verification

Log in, inspect `GET /api/calls/config/`, and confirm STUN plus both TURN URLs, an expiring username, and a credential. The shared secret must not appear. Use a WebRTC ICE gathering test with the temporary credentials and confirm a candidate of type `relay` is produced; do not publish those credentials.

Test voice and video calls between two accounts on different networks (for example Wi-Fi and mobile data), in both directions. Also test decline, hang-up, microphone mute, camera toggle, and that both devices release the microphone/camera after ending. To prove relay connectivity, temporarily test a peer connection with `iceTransportPolicy: 'relay'`; keep the production app's default automatic route selection.

## Restricted networks and TLS

TCP/UDP 3478 covers many networks but may be blocked by corporate firewalls. For a TLS fallback, provide a DNS hostname pointing directly at EC2 and a valid certificate readable by Coturn. Remove `no-tls`, configure `cert`, `pkey`, and `tls-listening-port=5349`, open TCP 5349, and append `turns:YOUR_TURN_HOST:5349?transport=tcp` to `WEBRTC_TURN_URLS`. Certificate renewal must also reload Coturn.

TLS on port 443 helps on networks allowing only HTTPS ports. The existing HTTPS API may already occupy that port on this instance; that requires a separate IP/relay instance or a deliberately configured TCP multiplexer. Do not replace the API's HTTPS listener.

Coturn authentication and NAT settings follow https://github.com/coturn/coturn/blob/master/README.turnserver.
