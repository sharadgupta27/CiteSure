# Deployment: one VM, one Postgres, local embeddings

> Status: this runbook and the pipeline are written and the production images build, but **nothing was deployed from this repository**: it needs an AWS account, a domain and GitHub secrets.
> Following the steps below takes about 30 minutes. The CI/CD workflow (`.github/workflows/deploy.yml`) automates steps 5-6 on every green push to `main`.

## What you need

- An AWS account and a domain name (or use the instance's public IP with `DOMAIN=localhost` for a plain test).
- A GitHub repository with Actions enabled and these **repository secrets**: `EC2_HOST`, `EC2_USER`, `EC2_SSH_KEY` (private key). Optionally an `ANTHROPIC_API_KEY` secret for the nightly real-model evaluation.
- A GitHub **environment** named `production` (add required reviewers there if you want a manual approval before each deploy).

## 1. Create the server

- EC2 `t3.medium` (2 vCPU, 4 GB): embedding and reranking run locally, so give it memory. Ubuntu 24.04, 30 GB gp3 disk.
- Security group: inbound **22** (your IP only), **80** and **443** (anywhere). Nothing else: the database and the API are not published.
- Point your domain's A record at the instance's (elastic) IP.

## 2. Install Docker on the server

```bash
sudo apt-get update && sudo apt-get install -y ca-certificates curl
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER && newgrp docker
sudo mkdir -p /opt/citesure && sudo chown $USER /opt/citesure
```

## 3. Secrets on the server (never in git)

Create `/opt/citesure/.env`:

```bash
DOMAIN=citesure.example.com
POSTGRES_PASSWORD=<long random>
JWT_SECRET=<32+ random characters>          # the API refuses to start in prod with a short or default secret
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
EMBEDDING_PROVIDER=fastembed
RERANKER=cross-encoder
UPLOADS_ENABLED=false                        # public demo: a pre-ingested corpus, uploads off
SEED_PASSWORD=<random>                       # used once to create the two demo logins
IMAGE_PREFIX=ghcr.io/<owner>/<repo>
```

`chmod 600 /opt/citesure/.env`. S3 for uploads (optional): `STORAGE_BACKEND=s3`, `S3_BUCKET=...` and an instance role with `s3:GetObject/PutObject/DeleteObject` on that bucket. The deploy workflow builds the image with `WITH_S3=true` (adds `boto3`).

## 4. First deploy by hand (to see it work)

```bash
cd /opt/citesure   # copy docker-compose.prod.yml and deploy/Caddyfile here (scp), then:
set -a; . ./.env; set +a
export TAG=latest
docker compose -f docker-compose.prod.yml pull
docker compose -f docker-compose.prod.yml run --rm migrate
docker compose -f docker-compose.prod.yml up -d
docker compose -f docker-compose.prod.yml run --rm -e UPLOADS_ENABLED=true api python -m app.seed   # demo company + 2 logins
curl -fsS https://$DOMAIN/healthz        # {"status":"ok","database":true}
```

The seed creates `employee@acme.example`, `hr@acme.example`, `admin@acme.example` (and the `agent@` service user) with `SEED_PASSWORD`. For a public demo, share only the employee and HR logins and remove or re-password the admin.

## 5. Let CI/CD do it

Push to `main`. After `CI` is green, `deploy.yml` will: build and push both images to GHCR (the backend with the local models baked in: `WITH_ML=true`), copy the compose files, pull on the server, **run migrations**, `up -d`, and poll `/healthz` for up to two minutes, failing the run (and printing the API logs) if it never turns healthy.
Roll back by re-running the workflow on an older commit or `TAG=<old sha> docker compose -f docker-compose.prod.yml up -d`.

## 6. After the deploy

- Turn on monitoring: copy `ops/` to the server and add `-f ops/docker-compose.observability.yml` (Grafana is not exposed publicly; use an SSH tunnel: `ssh -L 3000:localhost:3000 ...`).
- Back up the `pgdata` and `uploads` volumes (EBS snapshots are the simplest option).
- Review `security/threat-model.md` "hardening backlog" before inviting real users.

## Costs (order of magnitude)

A t3.medium runs about the price of a few coffees per month; the real cost driver is LLM usage (the per-user rate limit and `max_tokens` caps bound it; the `LlmSpendHigh` alert warns above $5/hour). Local embeddings and reranking cost nothing per request.
