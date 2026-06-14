# Deploying CSTT Agent Studio

Three supported paths, from local to cloud:

1. **Local Docker Compose** — full stack on your machine.
2. **Azure (ACR + Container Apps)** — two Container Apps in one environment, via `azd`.
3. **ContentSync** — deck-level approval / versioning / republish (runtime feature, no extra infra).

---

## 1. Local — Docker Compose (both services)

```powershell
cd cstt_agent_studio
# backend/.env must hold Azure OpenAI + Doc Intelligence keys (see backend/.env.example)
docker compose up --build
# open http://localhost:8080
```

- `frontend` (nginx) serves the built SPA and reverse-proxies `/api` + `/health` to
  `backend` using the `BACKEND_URL` env var (`http://backend:8000` by default).
- `backend` (FastAPI) keeps state in `redis` so sessions survive restarts; uploads
  and decks live on the `backend-data` volume.

### Build & push images to ACR (optional, for manual deploys)

```powershell
$env:REGISTRY = "<name>.azurecr.io"; $env:TAG = "v1"
docker compose build
az acr login -n <name>
docker compose push
```

---

## 2. Azure — ACR + Container Apps (azd)

Infrastructure-as-code lives in [`azure.yaml`](azure.yaml) and [`infra/`](infra):

| File | Purpose |
| --- | --- |
| `azure.yaml` | azd service map (backend + frontend → `containerapp`) |
| `infra/main.bicep` | subscription scope: resource group + params |
| `infra/resources.bicep` | Log Analytics, Container Apps env, ACR (+AcrPull identity), Storage (Blob+Table), AI Search, both Container Apps |
| `infra/main.parameters.json` | maps azd env vars → Bicep params |

### Provisioned resources

- **Azure Container Registry** (Basic) + user-assigned managed identity with `AcrPull`.
- **Container Apps Environment** + Log Analytics.
- **Storage account** (Blob container `cstt` for files, Table service for state).
- **Azure AI Search** (basic) for the per-session knowledge base.
- **backend** Container App — *internal* ingress on `:8000`
  (`STATE_BACKEND=azure`, `STORAGE_BACKEND=azure`, `RETRIEVAL_BACKEND=azure`,
  `QUEUE_BACKEND=local`). An account SAS (`listAccountSas`, services `bt`) and the
  Search admin key are injected as Container App **secrets**.
- **frontend** Container App — *external* ingress on `:80`; `BACKEND_URL` is set to
  the backend's internal FQDN so nginx proxies `/api` server-side (browser only ever
  hits the frontend domain, so calls are effectively same-origin).

### Deploy

```powershell
cd cstt_agent_studio
azd auth login

# one-time: set the secrets/config azd feeds into Bicep
azd env new cstt-prod
azd env set AZURE_OPENAI_ENDPOINT   "https://<your-aoai>.openai.azure.com/"
azd env set AZURE_OPENAI_API_KEY    "<aoai-key>"
azd env set AZURE_OPENAI_DEPLOYMENT "gpt-4o"
azd env set AZURE_OPENAI_EMBEDDING_DEPLOYMENT "text-embedding-ada-002"
azd env set JWT_SECRET "<random string, >=32 chars>"

azd up   # provisions infra, builds+pushes both images to ACR, deploys both apps
```

`azd up` first provisions with a placeholder image, then builds each service's
Dockerfile, pushes to ACR, and updates the Container Apps. The frontend URL is
printed as `SERVICE_FRONTEND_URI`.

> Azure OpenAI and Document Intelligence are assumed to already exist; only their
> endpoint/keys are passed in. Everything else is created by Bicep.

---

## 3. ContentSync — deck-level approval / versioning / republish

Runtime feature (no infra). Once a session has a generated deck:

| Endpoint | Action |
| --- | --- |
| `POST /api/sessions/{sid}/contentsync/submit` | snapshot current deck+plan as a new **pending** version |
| `POST /api/sessions/{sid}/contentsync/approve` | accept the pending version → becomes the live `current_version` |
| `POST /api/sessions/{sid}/contentsync/reject` | decline (requires `feedback`); live version unchanged |
| `POST /api/sessions/{sid}/contentsync/republish` | re-render the latest approved plan into a new **published** version |
| `GET  /api/sessions/{sid}/contentsync/versions` | version history with slide-level changelog |
| `GET  /api/sessions/{sid}/contentsync/versions/{v}/download` | download a specific version's `.pptx` |
| `GET  /api/sessions/{sid}/contentsync/status` | current/pending/live version summary |

Versions are immutable: each submit/republish copies the deck bytes to a
version-scoped object (`deck-v{n}-*.pptx`) and records a changelog computed from the
slide-title diff against the previous live version. State persists through whichever
`STATE_BACKEND` is configured (local / redis / azure).

Offline tests: `cd backend; .\.venv\Scripts\python.exe -m pytest tests/test_contentsync.py -q`
