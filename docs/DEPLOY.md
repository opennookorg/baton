# Deploying Baton

Baton ships as one container. `scripts/serve.sh` starts a HydraDB node inside it, restores the learned graph from `results/snapshots/1700.json`, and serves the API, dashboard and `/route` on port 7860. The image builds on the public HydraDB image (`ghcr.io/hydra-db/hydradb:0.4.0`, amd64 and arm64), so nothing has to be compiled. The HydraDB node uses about 1.5 GB of memory, so the host needs at least 2 GB.

The dashboard is served by the same container, so no separate frontend host (Vercel or similar) is needed.

## Free: Hugging Face Spaces

Docker Spaces on the free `cpu-basic` hardware (2 vCPU, 16 GB RAM) run the container as is. A free Space sleeps after 48 hours without visitors and wakes on the next visit, which takes about a minute while the graph is restored.

```sh
uvx --from huggingface_hub hf auth login
scripts/deploy_hf_space.sh <hf-user>/baton
```

The script packs the committed tree (`git archive HEAD`, without `docs/` and `tests/`), adds the Space front matter (`sdk: docker`, `app_port: 7860`) to the README, creates the Space if needed and uploads it. The live link is `https://<hf-user>-baton.hf.space`. Run the script again to redeploy.

## Paid, about $10 a month: Fly.io

Fly has no free tier for new accounts, only a short trial. `fly.toml` asks for a `shared-cpu-2x` machine with 2 GB, which costs about $10 a month when always on. With `auto_stop_machines = "stop"` and `min_machines_running = 0` it stops when idle and you pay for running time only.

```sh
fly launch --copy-config --no-deploy
fly deploy
```

## Free, more setup: any VM with Docker

Oracle Cloud's Always Free tier includes an ARM VM with up to 24 GB of memory. On it, or any machine with Docker:

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

The graph lives in the container's temporary disk. A restart restores the 1,700-issue graph again. Issues learned through `/learn` after that are lost on restart unless the host gives the container a persistent volume at `BATON_STATE_DIR`.

## Not verified

`scripts/serve.sh` was run end to end on macOS against a local HydraDB build: the graph restored (22 teams, 1,225 entities, 2,286 issues) and `/route` and the dashboard answered. The Docker image itself has not been built yet, because Docker was not available on the build machine. The first `docker build` or Space build is its first test.
