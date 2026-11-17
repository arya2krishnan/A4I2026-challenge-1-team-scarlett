# Dispatch approval API

A small REST service that adds the human step between the agent's recommendation and the field crews:

1. The **agent** submits its dispatch sheet as a *proposal* (`PENDING_REVIEW`).
2. A **dispatcher** approves some or all of the stops, optionally moving some. The API returns a signed `dispatch_id` (`APPROVED`).
3. **Field crews and the dispatch map** read the active dispatches.
4. During the day, **triage** can move a stop (e.g. an intersection is blocked). The reason is logged and the dispatch is re-signed.
5. At the end of the heat day the dispatch is **closed** and leaves the active list.

It runs on **Cloud Run** (private, behind IAM) and stores data in **Firestore**. Locally it uses **SQLite**.

## Endpoints

| Method | Path | Body | Result |
|---|---|---|---|
| `POST` | `/api/dispatches/proposals` | The dict `build_dispatch_plan` returns, plus `forecast_high_f` | `201` `{proposal_id, status: "PENDING_REVIEW"}` |
| `POST` | `/api/dispatches/approve` | `{proposal_id, approved_by, approved_stops: [1,2], approved_teams?: [..], overrides?: {"2": {latitude, longitude, reason}}}` | `201` the dispatch with `dispatch_id`, `status: "APPROVED"` and `signature` |
| `GET` | `/api/dispatches/active` | none | `{count, dispatches: [...]}`: approved stops, wellness teams and the change log |
| `PATCH` | `/api/dispatches/{id}/override` | `{stop, latitude, longitude, reason, requested_by}` | `200` the dispatch with the stop moved, `revision` increased and a new signature |
| `POST` | `/api/dispatches/{id}/close` | `{closed_by, reason}` | `200` `status: "CLOSED"` |
| `GET` | `/healthz` | none | `{"status": "ok"}` |

**Error codes:**
- `404`: the proposal or dispatch doesn't exist.
- `409`: wrong state, e.g. approving a proposal twice or overriding a closed dispatch.
- `422`: invalid input, e.g. a point outside the City of Chicago, a stop number that isn't in the proposal, or an empty reason.

**Behaviour to know about:**
- **Stop numbers stay as proposed.** If you approve only stop 2, it stays "truck #2".
- **Moved stops keep their original point** in `original_latitude` / `original_longitude`. Every move is listed in `overrides`.
- **Signatures:** `signature` is an HMAC-SHA256 over the approver, the approval time, the revision, and every stop's and team's coordinates. The key is in Secret Manager.
- **No double approval:** approvals run in a transaction, so two dispatchers approving the same proposal at the same moment cannot both succeed.
- **No login in the app itself.** Cloud Run IAM decides who can call it, and `approved_by` is whatever the caller sends.

## Code

```
api/
  dispatch_api/app.py       routes; picks the database from DISPATCH_STORE
  dispatch_api/models.py    request formats, Chicago boundary check
  dispatch_api/store.py     the lifecycle (propose, approve, override, close), shared by both databases
  dispatch_api/repos.py     SqliteRepo (local) and FirestoreRepo (Cloud Run)
  dispatch_api/signing.py   HMAC signing
  Dockerfile                container for Cloud Run
  requirements.txt
scripts/deploy_api.sh           make deploy-api
scripts/smoke_dispatch_api.py   make smoke-api (end-to-end test of a running server)
tests/test_dispatch_api.py      offline tests (part of make test)
```

## Run and test locally

```bash
make setup                         # once: .venv with Python 3.11 (macOS: brew install python@3.11)
make test                          # offline tests, including tests/test_dispatch_api.py
make api-local                     # http://127.0.0.1:8080, SQLite at .data/dispatches.db
open http://127.0.0.1:8080/docs    # interactive Swagger UI
make smoke-api URL=http://127.0.0.1:8080 NOAUTH=1   # end-to-end check against the local server
```

`make api-local` reads `.env`. Set `DISPATCH_SIGNING_KEY` there. Without it, the API makes up a random key at startup, and signatures stop checking out after a restart.

To run the API tests against Firestore instead of SQLite, start the emulator (`gcloud emulators firestore start`, needs Java), set `FIRESTORE_EMULATOR_HOST`, then run `make test`.

## Deploy to Google Cloud

### 1. Prerequisites

- **Tools:** the `gcloud` CLI, `openssl`, `bash` and `make`.
- **Account:** an account on the target project with Owner, or with all of these roles:
  - Service Usage Admin
  - Service Account Admin
  - Project IAM Admin
  - Cloud Datastore Owner
  - Secret Manager Admin
  - Cloud Run Admin
  - Cloud Build Editor
  - Service Account User
- **Billing** enabled on the project.

```bash
gcloud auth login                               # the account that owns / can deploy to the project
gcloud config set project <PROJECT_ID>
```

### 2. Point `.env` at the project

```bash
cp .env.example .env        # if you do not have one yet
```

Then set at least these in `.env`:

```
GOOGLE_CLOUD_PROJECT=<PROJECT_ID>
GOOGLE_CLOUD_LOCATION=us-central1
```

Optional settings (defaults shown):

| Variable | Default | Meaning |
|---|---|---|
| `DISPATCH_API_SERVICE_NAME` | `heat-dispatch-api` | Cloud Run service name |
| `FIRESTORE_DATABASE` | `heat-dispatch` | Named Firestore database (separate from the project's `(default)` database) |
| `FIRESTORE_LOCATION` | `GOOGLE_CLOUD_LOCATION` | Firestore location. **Cannot be changed after creation** |
| `DISPATCH_SIGNING_SECRET` | `dispatch-signing-key` | Secret Manager secret that holds the HMAC key |
| `DISPATCH_API_SERVICE_ACCOUNT` | `heat-dispatch-api@<PROJECT_ID>.iam.gserviceaccount.com` | Identity the service runs as |
| `ALLOW_UNAUTHENTICATED` | `false` | `true` makes the API public. Don't, unless it's a throwaway demo |

### 3. Deploy

```bash
make deploy-api
```

`scripts/deploy_api.sh` is safe to re-run. It does the following:

1. Enables the Cloud Run, Cloud Build, Artifact Registry, Firestore and Secret Manager APIs.
2. Creates the Firestore database `heat-dispatch` (Native mode) if it doesn't exist.
3. Creates the service account and grants it `roles/datastore.user`, which allows reading and writing Firestore only.
4. Creates the secret `dispatch-signing-key` with a random 32-byte key if it doesn't exist. The key is never printed. The script then gives the service account access to that secret only.
5. Builds `api/` with Cloud Build and deploys it to Cloud Run with these settings:
   - private (`--no-allow-unauthenticated`)
   - 512 MiB memory, at most 3 instances
   - `DISPATCH_STORE=firestore`
   - the key mounted from Secret Manager as `DISPATCH_SIGNING_KEY`
6. Writes the service URL to `.env` as `DISPATCH_API_URL`.

The first run takes a few minutes, mostly for the Cloud Build image build.

### 4. Test the deployed service

```bash
make smoke-api
```

This runs 18 checks against `DISPATCH_API_URL`, authenticating with your `gcloud auth print-identity-token`:
- the full lifecycle (propose, approve, list active, override, close)
- every error code
- two simultaneous approvals of one proposal, where exactly one must win

Everything it creates is tagged `submitted_by: smoke-test` and closed at the end, so nothing is left on the active list. The command exits with `0` only if every check passes. This is the step that tests the Firestore storage end to end.

### 5. Give access to callers

The service is private, so every caller needs `roles/run.invoker`:

```bash
SERVICE=heat-dispatch-api; REGION=us-central1; PROJECT=<PROJECT_ID>

# a person (dispatcher, teammate)
gcloud run services add-iam-policy-binding $SERVICE --region $REGION --project $PROJECT \
  --member user:someone@example.com --role roles/run.invoker

# the agent on Agent Runtime, or the Streamlit client, calling it with their own identity
gcloud run services add-iam-policy-binding $SERVICE --region $REGION --project $PROJECT \
  --member serviceAccount:heat-agent@$PROJECT.iam.gserviceaccount.com --role roles/run.invoker
```

### 6. Call it by hand

```bash
URL=$(grep ^DISPATCH_API_URL= .env | cut -d= -f2)
TOKEN=$(gcloud auth print-identity-token)

curl -s -H "Authorization: Bearer $TOKEN" "$URL/api/dispatches/active"

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H "Content-Type: application/json" "$URL/api/dispatches/approve" \
  -d '{"proposal_id": "prop-...", "approved_by": "Officer Miller", "approved_stops": [1, 2]}'
```

Or open a local tunnel that adds the token for you. It also makes the Swagger UI reachable:

```bash
gcloud run services proxy heat-dispatch-api --region us-central1 --project <PROJECT_ID> --port 8081
open http://127.0.0.1:8081/docs
```

## Operating it

- **Ship a code change:** run `make deploy-api` again, then `make smoke-api`. The database and secret are reused.
- **Logs:** `gcloud run services logs read heat-dispatch-api --region us-central1 --project <PROJECT_ID>`.
- **Roll back:** list revisions, then send all traffic back to the previous one:
  ```bash
  gcloud run revisions list --service heat-dispatch-api --region us-central1
  gcloud run services update-traffic heat-dispatch-api --to-revisions <REVISION>=100 --region us-central1
  ```
- **Rotate the signing key:**
  ```bash
  openssl rand -hex 32 | tr -d '\n' | gcloud secrets versions add dispatch-signing-key --data-file=-
  ```
  Then run `make deploy-api` so new instances pick up `:latest`. Signatures made with the old key will no longer check out.
- **Look at the data:** in the Cloud Console go to **Firestore → heat-dispatch**. The collections are `proposals` and `dispatches`.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `Set GOOGLE_CLOUD_PROJECT in .env` | Step 2 |
| `403` from the service | Your account or the caller's service account is missing `roles/run.invoker` (step 5). `gcloud auth print-identity-token` must come from that same account |
| Cloud Build fails with a permission error on the build service account | Grant the project's build service account (shown in the error, usually `<PROJECT_NUMBER>-compute@developer.gserviceaccount.com`) `roles/cloudbuild.builds.builder`, then re-run |
| Container fails to start: `DISPATCH_SIGNING_KEY is required on Cloud Run` | The secret isn't mounted. Re-run `make deploy-api`, or check that the service account has `secretAccessor` on the secret |
| `PermissionDenied` / `403` from Firestore in the logs | The service account is missing `roles/datastore.user`, or `FIRESTORE_DATABASE` names a database that doesn't exist |
| `gcloud firestore databases create` fails | An organisation policy may restrict locations. Set `FIRESTORE_LOCATION` to an allowed one (e.g. `nam5`). It can't be changed later |
| Smoke test `concurrent approvals` fails | Two approvals both succeeded, which means the transaction isn't working. Don't use the service for real dispatches until this is fixed |

## Tear down

```bash
PROJECT=<PROJECT_ID>; REGION=us-central1
gcloud run services delete heat-dispatch-api --region $REGION --project $PROJECT
gcloud firestore databases delete --database heat-dispatch --project $PROJECT     # deletes all dispatch records
gcloud secrets delete dispatch-signing-key --project $PROJECT
gcloud iam service-accounts delete heat-dispatch-api@$PROJECT.iam.gserviceaccount.com --project $PROJECT
```

## Not done yet

- **Nothing sends proposals automatically.** The agent doesn't submit to this API yet. A small agent tool that posts the result of `build_dispatch_plan` to `/api/dispatches/proposals` would close the loop.
- **Approver identity isn't checked.** `approved_by` is whatever the caller sends. To record who really approved, read the caller identity that Cloud Run IAM or IAP provides.
- **Dispatches don't expire.** One stays active until someone closes it; there is no automatic end-of-day close.
