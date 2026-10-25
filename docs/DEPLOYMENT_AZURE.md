# Deploying InvoiceIQ to Azure Container Apps

Target architecture:

```
                 ┌──────────────── Azure Container Apps environment ────────────────┐
 Browser ──HTTPS──► frontend (nginx)        api (FastAPI, 1–5 replicas) ◄──HTTPS── Browser
                 │                              │        │                          │
                 │   migrate (Container Apps Job: alembic upgrade head, per release)│
                 │   worker (Celery, 0–N replicas, scaled by Redis queue length)    │
                 └──────────────────────────────┼────────┼──────────────────────────┘
                     Azure Database for PostgreSQL      Azure Cache for Redis
                     (Flexible Server)                  Object storage (S3-compatible*)
```

| Component | Azure service | Why |
|---|---|---|
| API, worker, frontend | **Container Apps** | Runs our Docker images; HTTPS ingress, autoscaling, scale-to-zero, no Kubernetes to manage |
| Images | **Azure Container Registry (ACR)** | Private registry next to the apps |
| Database | **PostgreSQL Flexible Server** | Managed Postgres 17: backups, patching, HA |
| Broker / rate limits | **Azure Cache for Redis** | Managed Redis (TLS on port 6380) |
| Secrets | **Container Apps secrets** (or Key Vault references) | Never in images or the repo |
| Logs | **Log Analytics** (attached to the environment) | Our JSON logs are searchable by `request_id`, `invoice_id` |

\* **Storage:** the code supports any S3-compatible service today (`STORAGE_BACKEND=s3`), e.g.
Cloudflare R2 or AWS S3. Native **Azure Blob Storage** is the planned second implementation of
the `StorageBackend` interface (`upload / download / delete / presigned_url` → Blob SAS URLs);
`STORAGE_BACKEND=azure` is reserved for it. No other code changes are needed.

---

## 1. One-time setup

```bash
az login
az extension add --name containerapp --upgrade

RG=invoiceiq-rg
LOC=centralindia
ACR=invoiceiqacr$RANDOM          # must be globally unique
ENV=invoiceiq-env

az group create -n $RG -l $LOC
az acr create -g $RG -n $ACR --sku Basic
az containerapp env create -g $RG -n $ENV -l $LOC   # also creates Log Analytics
```

## 2. Managed Postgres and Redis

```bash
az postgres flexible-server create -g $RG -n invoiceiq-db -l $LOC \
  --tier Burstable --sku-name Standard_B1ms --version 17 \
  --admin-user invoiceiq --admin-password '<strong-password>' \
  --public-access 0.0.0.0          # allow Azure services; use VNet integration in real prod
az postgres flexible-server db create -g $RG -s invoiceiq-db -d invoiceiq

az redis create -g $RG -n invoiceiq-redis -l $LOC --sku Basic --vm-size c0
az redis list-keys -g $RG -n invoiceiq-redis      # copy the primary key
```

Redis URLs on Azure use TLS: `rediss://:<key>@invoiceiq-redis.redis.cache.windows.net:6380/0`
(note `rediss://`, port 6380). Use `/1` and `/2` for the Celery broker and result backend.

## 3. Build and push images

```bash
az acr login -n $ACR
docker build -t $ACR.azurecr.io/invoiceiq-backend:v1 ./backend
docker build -t $ACR.azurecr.io/invoiceiq-frontend:v1 \
  --build-arg VITE_API_URL=https://<api-fqdn>/api/v1 ./frontend
docker push $ACR.azurecr.io/invoiceiq-backend:v1
docker push $ACR.azurecr.io/invoiceiq-frontend:v1
```

(Create the API first to learn its FQDN, then build the frontend with it.)

## 4. Configuration (environment variables)

Secrets (`--secrets` + `secretref:`): `JWT_SECRET_KEY` (64+ random chars), `POSTGRES_PASSWORD`,
`REDIS_URL`, `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND`, `S3_SECRET_KEY`, `LLM_API_KEY`.

Plain values: `ENVIRONMENT=production`, `DEBUG=false`, `LOG_LEVEL=INFO`,
`POSTGRES_HOST=invoiceiq-db.postgres.database.azure.com`, `CORS_ORIGINS=https://<frontend-fqdn>`,
`S3_ENDPOINT_URL` = `S3_PUBLIC_ENDPOINT_URL` = your storage endpoint, `S3_BUCKET`, `S3_ACCESS_KEY`,
`WEB_CONCURRENCY=2`.

`ENVIRONMENT=production` makes the app refuse to start with `DEBUG=true` or a short JWT secret,
and hides `/docs`.

## 5. Create the apps

```bash
COMMON_ENV="ENVIRONMENT=production DEBUG=false POSTGRES_HOST=... CORS_ORIGINS=https://... \
  JWT_SECRET_KEY=secretref:jwt REDIS_URL=secretref:redis ..."   # all variables from step 4

# API: public HTTPS ingress, scales 1-5 on concurrent requests
az containerapp create -g $RG -n invoiceiq-api --environment $ENV \
  --image $ACR.azurecr.io/invoiceiq-backend:v1 --registry-server $ACR.azurecr.io \
  --ingress external --target-port 8000 --min-replicas 1 --max-replicas 5 \
  --secrets jwt=<...> redis=<...> db-password=<...> llm=<...> \
  --env-vars $COMMON_ENV

# Worker: no ingress; scale on the Celery queue length in Redis (KEDA redis scaler).
# Scale-to-zero when the queue is empty = no cost when idle.
az containerapp create -g $RG -n invoiceiq-worker --environment $ENV \
  --image $ACR.azurecr.io/invoiceiq-backend:v1 --registry-server $ACR.azurecr.io \
  --command celery --args "-A app.workers.celery_app worker --loglevel=INFO --concurrency=2" \
  --min-replicas 0 --max-replicas 4 \
  --scale-rule-name queue --scale-rule-type redis \
  --scale-rule-metadata address=invoiceiq-redis.redis.cache.windows.net:6380 listName=celery \
      listLength=5 enableTLS=true databaseIndex=1 \
  --scale-rule-auth password=redis-key \
  --secrets redis-key=<key> ... --env-vars $COMMON_ENV

# Frontend: static nginx
az containerapp create -g $RG -n invoiceiq-web --environment $ENV \
  --image $ACR.azurecr.io/invoiceiq-frontend:v1 --registry-server $ACR.azurecr.io \
  --ingress external --target-port 80 --min-replicas 1
```

## 6. Migrations: a job per release, not on API start

Running `alembic upgrade head` inside every API replica would race when several start at once.
A Container Apps **Job** runs it exactly once per release, before traffic moves to the new version:

```bash
az containerapp job create -g $RG -n invoiceiq-migrate --environment $ENV \
  --trigger-type Manual --replica-timeout 600 \
  --image $ACR.azurecr.io/invoiceiq-backend:v1 --registry-server $ACR.azurecr.io \
  --command alembic --args "upgrade head" --secrets ... --env-vars $COMMON_ENV
az containerapp job start -g $RG -n invoiceiq-migrate
```

Migrations must stay **backward compatible** with the previous release (add columns as nullable,
drop old ones a release later), so old and new API versions can run side by side during a rollout.

## 7. Continuous deployment (GitHub Actions)

Extend `.github/workflows/ci.yml` with a `deploy` job on pushes to `main`, after tests pass:

1. `azure/login@v2` with **OIDC federated credentials** (no long-lived secrets in GitHub).
2. Build and push both images tagged with the commit SHA (`:${{ github.sha }}`) — never `:latest`,
   so every deployment is traceable and rollback is "deploy the previous SHA".
3. `az containerapp job start -n invoiceiq-migrate` (with the new image) and wait.
4. `az containerapp update -n invoiceiq-api --image ...:${{ github.sha }}` (same for worker, web).

Container Apps creates a new **revision** per update and shifts traffic once it is healthy
(our `/health` checks DB and Redis); a failed revision never receives traffic.

## 8. Production checklist

- [ ] `ENVIRONMENT=production`, strong `JWT_SECRET_KEY`, `DEBUG=false`
- [ ] `CORS_ORIGINS` = the real frontend URL only
- [ ] Postgres: VNet / private endpoint, automated backups on, TLS enforced
- [ ] Health probes on `/health` (liveness + readiness)
- [ ] Log Analytics alerts: 5xx rate, `Invoice failed` log volume, worker queue length
- [ ] Flower is **not** exposed publicly (internal ingress or omitted)
- [ ] Gemini/OpenAI quota and cost alerts
