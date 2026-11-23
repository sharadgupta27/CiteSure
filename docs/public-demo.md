# Free public demo

A public link anyone can open, at no cost: the whole app in **one Docker container** ([deploy/demo/](../deploy/demo/)) on Render's free tier.

| | |
|---|---|
| What runs | Postgres 16 + pgvector, API, worker and nginx in one container; the database is created and seeded when the image is built |
| Models | the deterministic fake providers: no API key, no cost, nothing sent anywhere |
| Data | the fictional Acme Robotics handbook and its golden set; uploads and public research are off; everything resets on restart |
| Size | about 190 MB of RAM in use, so it fits the free 512 MB / 0.1 CPU instance |
| Sleep | Render's free tier sleeps after 15 minutes without visitors. The next visitor sees a "CiteSure is waking up" page that reloads itself; the app is ready about 1 to 2 minutes later |
| Link | `https://citesure-demo.onrender.com` (or similar; Render shows it) |

The container clones this GitHub repository at build time (`CITESURE_REF`, default `main`), so **push your changes to GitHub first**.

## Deploy on Render (recommended)

1. Push this repository to GitHub (it must be the public `main` branch the Dockerfile clones).
2. Create a free account at [render.com](https://render.com) (sign in with GitHub is fine; no card needed for the free tier).
3. **New** → **Blueprint** → pick the CiteSure repository. Render reads [render.yaml](../render.yaml): one free Docker web service, `deploy/demo/Dockerfile`, health check `/healthz`, `PORT=7860`.
4. **Apply**. The first build takes about 10 minutes. Then open the URL Render shows and sign in as `employee@acme.example` / `citesure-demo`.
5. Put the link in the README and share it.

Without the Blueprint: **New** → **Web Service** → the repository → Runtime **Docker**, Dockerfile path `deploy/demo/Dockerfile`, Docker build context `deploy/demo`, instance type **Free**, environment variable `PORT=7860`, health check path `/healthz`.

Each push to `main` redeploys. To pin a version instead, set the build argument `CITESURE_REF=<commit sha>` in the Dockerfile.

## Other free hosts

| Host | How | Notes |
|---|---|---|
| **Koyeb** (free instance) | Create service → GitHub → this repository → builder **Dockerfile**, Dockerfile location `deploy/demo/Dockerfile`, work directory `deploy/demo`, exposed port `7860`, health check `/healthz` | same 512 MB / 0.1 CPU size; scales to zero when idle |
| **Hugging Face Spaces** | Docker SDK, upload the files of `deploy/demo/` and add Space front matter (`sdk: docker`, `app_port: 7860`) to its README | Docker Spaces are a paid option on some accounts; the image runs as uid 1000 as Spaces require |
| **Any VM with Docker** | `docker build -t citesure-demo deploy/demo && docker run -d -p 80:7860 citesure-demo` | e.g. an Oracle Cloud Always Free VM ([free-deployment.md](free-deployment.md)) |

## Test it locally first

```bash
docker build -t citesure-demo deploy/demo
docker run --rm -p 7860:7860 --memory 512m --cpus 0.1 citesure-demo    # same limits as the free tier
# open http://localhost:7860 : the "waking up" page first, then the app
```

Measured with those limits: the waking page answers after 4 seconds, the app after 61 seconds, using 190 MB of memory.

## Why it is safe to make public

- `ENV=prod`: API docs off; a random `JWT_SECRET` on every start; production checks at startup.
- No secrets in the image and no API keys: the fake models cannot spend money or send data out.
- Uploads off (only the build-time seed may upload), public research off; Postgres listens on localhost inside the container.
- Security headers (CSP, `nosniff`, no referrer) on every response.
- The demo passwords are public by design and only reach invented data. An admin visitor can delete demo documents; a restart restores them.

## Limits

- Fake models give extractive answers (quotes), not fluent prose. Real models: see the [README](../README.md#run-it).
- One container: no observability stack and no private mode here. Use the compose files for those.
- Not for real documents: anything stored is lost on restart, and the demo logins are public.
