# YouTube download route (Tailscale)

YouTube blocks the EC2 server's IP, so production downloads go out through
teammates' home laptops instead:

```
backend (yt-dlp) --SOCKS5--> ts-<name> sidecar --tailnet--> teammate laptop (exit node) --> YouTube
```

`YTDLP_PROXIES` lists the sidecars in the order to try. A route that YouTube
blocks, or that is offline, is skipped; if every route fails the job ends
with an error asking for a teammate's laptop to be switched on. Errors about
the video itself (private, removed) are not retried on other routes.

## 1. Admin console (once)

1. Invite each teammate to your tailnet: login.tailscale.com, **Users →
   Invite users**. They must join *your* tailnet, not create their own.
2. **Settings → Keys → Generate auth key**: Reusable on, Ephemeral off.
   This is `TS_AUTHKEY` on EC2. Keep it secret.

## 2. Teammate laptop (Windows)

1. Install Tailscale from tailscale.com/download/windows and log in through
   the invite, choosing your tailnet.
2. Tray icon → **Exit node → Run exit node**.
3. Tray icon → **Preferences → Run unattended** on.
4. Windows **Settings → System → Power**: never sleep when plugged in.

## 3. Admin console (per laptop)

On the laptop's row in **Machines**:

1. **⋯ → Edit route settings → Use as exit node**.
2. **⋯ → Disable key expiry**.
3. **⋯ → Edit machine name**: a readable name such as `muntazir-laptop`.

## 4. EC2

1. In `deploy/docker-compose.yml`, each laptop has a `ts-<name>` sidecar
   whose `--exit-node=` is the machine name from step 3. Copy the block to
   add one.
2. In `~/highlyte/.env` on the server:

   ```
   TS_AUTHKEY=tskey-auth-...
   YTDLP_PROXIES=socks5://ts-muntazir:1055
   ```

   Separate several proxies with commas; the first is tried first.
3. Deploy (push to master), or on the server: `docker-compose up -d`.

## 5. Check a route

```bash
docker-compose exec ts-muntazir tailscale status
```

The laptop should show as the active exit node.

```bash
docker-compose exec backend yt-dlp --proxy socks5://ts-muntazir:1055 --print title "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

This should print the video title, not a "not a bot" error.
The backend logs `[ingest] route ... failed: ...` whenever it skips a
route.

## Limits

- Downloads work only while at least one route's laptop is awake and online.
- Download speed is capped by that home connection's upload speed.
