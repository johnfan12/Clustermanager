# FRP for Simple Clustermanager

The simplified platform uses one `frps` service on the VPS.

- Node APIs can be exposed to the VPS by each Servermanager node.
- User-created TCP tunnels bind public ports on this same `frps`.
- Container visitors and GPU-specific FRP services are not used in this branch.

Install `frps`:

```bash
cd frp
bash install.sh
```

Edit `/etc/frp/frps.ini`, then start the service:

```bash
sudo systemctl enable frps
sudo systemctl start frps
```
