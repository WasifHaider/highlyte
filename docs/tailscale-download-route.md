# YouTube download route (Tailscale)

YouTube blocks the EC2 server's IP, so production downloads go out through
teammates' home laptops instead:

```
backend (yt-dlp) --HTTP--> ts-<name> sidecar --tailnet--> teammate laptop (exit node) --> YouTube
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
   whose `--exit-node=` comes from a `<NAME>_EXIT_NODE` variable. It must be
   the laptop's Tailscale IP (`100.x.y.z`, shown in **Machines**), not its
   name: the sidecar can't resolve names while starting up. Copy the block
   to add one.
2. In `~/highlyte/.env` on the server:

   ```
   TS_AUTHKEY=tskey-auth-...
   YTDLP_PROXIES=http://ts-muntazir:1056
   MUNTAZIR_EXIT_NODE=100.x.y.z
   ```

   Separate several proxies with commas; the first is tried first.
3. Deploy (push to master), or on the server: `docker-compose up -d`.

## 5. Check a route

```bash
docker-compose exec ts-muntazir tailscale status
```

The laptop should show as the active exit node.

```bash
docker-compose exec backend yt-dlp --proxy http://ts-muntazir:1056 --print title "https://www.youtube.com/watch?v=dQw4w9WgXcQ"
```

This should print the video title, not a "not a bot" error.
The backend logs `[ingest] route ... failed: ...` whenever it skips a
route.

## 6. Fewer rate limits: PO tokens and cookies

Two optional extras make YouTube treat the downloads as less bot-like.
Each one helps on its own; together they help most.

### PO-token provider

The `pot-provider` service in `deploy/docker-compose.yml` generates
YouTube "proof of origin" tokens, and the `bgutil-ytdlp-pot-provider`
plugin (in `requirements.txt`) hands them to yt-dlp. Turn it on by adding
this to `~/highlyte/.env`, then redeploy:

```
YTDLP_POT_URL=http://pot-provider:4416
```

If the sidecar is down, yt-dlp logs a warning and downloads without a
token, as before. Keep its image tag equal to the plugin version.

### Cookies from a burner account

Logged-in downloads are rate-limited far less than anonymous ones.

> **Use a throwaway Google account made only for this.** YouTube can
> suspend accounts used for automated downloads. Never use anyone's real
> account.

1. Make a new Google account and open YouTube with it once.
2. Open a **private/incognito window**, log in to YouTube with the burner
   account, and open `https://www.youtube.com/robots.txt` in that tab.
3. Export the cookies for youtube.com with a cookies.txt extension
   ("Get cookies.txt LOCALLY" works). Save as `youtube-cookies.txt`.
4. Close the private window **without logging out**. Using that window
   again would make YouTube rotate the cookies and the exported ones stop
   working.
5. Copy the file to the server and point the backend at it:

   ```bash
   scp -i hireflow-key.pem youtube-cookies.txt ec2-user@13.204.4.68:~/highlyte/data/secrets/youtube-cookies.txt
   ```

   In `~/highlyte/.env` (the container sees `data/` as `/app/data`):

   ```
   YTDLP_COOKIES=/app/data/secrets/youtube-cookies.txt
   ```

   Then `docker-compose up -d backend`.

The file is read fresh for every download, so replacing it needs no
restart. When the cookies expire the backend logs
`[ingest] YouTube rejected the cookies in YTDLP_COOKIES`: repeat steps
2-5. Expect to do this every few weeks.

## Limits

- Downloads work only while at least one route's laptop is awake and online.
- Download speed is capped by that home connection's upload speed.
- The video is downloaded from YouTube once per job and every clip is cut
  from that file, so a job makes a handful of requests, not one per clip.
- Routes take turns. A route YouTube rate-limits (429 / "not a bot") is
  retried once after a pause, then rested for 10 minutes. An offline route
  is skipped until it answers a quick check. If none is usable, the job
  waits up to 15 minutes for one to return, then fails with the real cause.
- Tuning (server `.env`, all optional): `YTDLP_WAIT_S` (default 900),
  `YTDLP_RATE_COOLDOWN_S` (600), `YTDLP_CONCURRENCY` (simultaneous
  YouTube downloads, default 2).
