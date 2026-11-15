# Deploying Baton

Baton ships as one container. `scripts/serve.sh` starts a HydraDB node inside it, restores the learned graph from `results/snapshots/1700.json`, and serves the API, dashboard and `/route` on port 7860. The image builds on the public HydraDB image (`ghcr.io/hydra-db/hydradb:0.4.0`, amd64 and arm64), so nothing has to be compiled. The HydraDB node uses about 1.5 GB of memory, so the host needs at least 2 GB.

The dashboard is built into the image and served by the same container, so no separate frontend host is needed. `web/vercel.json` can also host it on Vercel, proxying the API to the container.

## Free: Google Cloud Run

Cloud Run runs the container as is and scales to zero when idle. Its monthly free tier (180,000 vCPU-seconds, 360,000 GiB-seconds, 2 million requests) covers about 50 hours of active time at 1 vCPU and 2 GiB. Google needs a billing account with a card, so the deploy script adds two guards before it deploys anything:

- A Cloud Run spend cap budget. It pauses Cloud Run in the project once the month's gross usage reaches `BATON_SPEND_CAP` (default 1 USD). Gross usage counts free tier usage too, so the cap trips well before the free tier runs out and the bill stays at zero. The service comes back on the first of the next month, or when you lift the cap in Billing, Budgets and alerts.
- An alerts-only budget on the whole project that emails the billing admins on the first real charge, for anything outside Cloud Run (image storage, builds).

It also keeps image storage under the 0.5 GB free tier with a cleanup policy that keeps the two newest images, and caps the service at one instance (the graph lives in one container anyway).

```sh
gcloud auth login
gcloud projects create <project-id>
gcloud billing projects link <project-id> --billing-account=<billing-account-id>
scripts/deploy_cloud_run.sh <project-id>
```

The image is built by Cloud Build from the uploaded source (`.gcloudignore` reuses `.dockerignore`, so `.env` is never uploaded), so Docker is not needed locally. `BATON_LEARN_TOKEN` comes from `.env`. If the billing account is not in USD, set `BATON_SPEND_CAP` to about 1 USD in its currency, for example `BATON_SPEND_CAP=90` for INR. If the container runs out of memory, redeploy with `BATON_MEMORY=4Gi`, which halves the free hours. The first request after an idle period waits for HydraDB to start and the graph to restore.

Hugging Face Docker Spaces now need a PRO subscription, so `scripts/deploy_hf_space.sh` only works on a paid account.

## Paid, about $10 a month: Fly.io

Fly has no free tier for new accounts, only a short trial. `fly.toml` asks for a `shared-cpu-2x` machine with 2 GB, which costs about $10 a month when always on. With `auto_stop_machines = "stop"` and `min_machines_running = 0` it stops when idle and you pay for running time only.

```sh
fly launch --copy-config --no-deploy
fly deploy
```

## Free, more setup: any VM with Docker

Oracle Cloud's Always Free tier includes an ARM VM with 12 GB of memory (current Oracle docs). On it, or any machine with Docker:

```sh
docker build -t baton .
docker run -p 7860:7860 baton
```

## Settings

| Variable | Default | Meaning |
|---|---|---|
| `PORT` | `7860` | HTTP port for the API and dashboard |
| `BATON_STATE_DIR` | `/tmp/hydradb` | HydraDB data directory inside the container |
| `BATON_BOLT_PORT` | `7687` | HydraDB Bolt port, inside the container only |
| `BATON_HYDRADB_TOKEN` | development token | HydraDB auth token. Set it as a secret on a public host. |
| `BATON_LEARN_TOKEN` | unset, so `POST /learn` is open | Bearer token required by `POST /learn`. Set it on a public host. |

The graph lives in the container's temporary disk. A restart restores the 1,700-issue graph again. Issues learned through `/learn` after that are lost on restart unless the host gives the container a persistent volume at `BATON_STATE_DIR`.

## Not verified

`scripts/serve.sh` was run end to end on macOS against a local HydraDB build: the graph restored (22 teams, 1,225 entities, 2,286 issues) and `/route` and the dashboard answered. The Docker image itself has not been built yet, because Docker was not available on the build machine. The first `docker build` or Space build is its first test.
