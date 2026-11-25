# AiFlow — Deployment Guide

AiFlow deploys as two independent services:

- **Backend** — AWS Lambda + API Gateway via AWS SAM
- **Frontend** — AWS Amplify (static hosting, built from `frontend/dist`)

There are two ways through this document. **Releasing a new version** (next section) is the everyday routine and uses the helper scripts. **Steps 1 to 4** are the first-time setup and also the manual fallback: everything the scripts do is spelled out there.

---

## Quick path: releasing a new version

Use this once the first deployment (Steps 1 to 4 below) is done. It is the everyday routine.

### 1. Prepare the release

```powershell
cd C:\dev\aiflow
python scripts/bump_version.py patch      # a fix:      0.11.0 -> 0.11.1
python scripts/bump_version.py minor      # a feature:  0.11.0 -> 0.12.0
python scripts/bump_version.py major      # a breaking change, or leaving beta
```

This changes `VERSION`, adds an entry for the new number at the top of `CHANGELOG.md`, and copies the number into `backend/app/version.py` and `frontend/package.json`. Then:

1. Replace the placeholder text in the new `CHANGELOG.md` entry with what changed (this is what people read under **Help → About**).
2. Run the tests: `cd backend; .venv\Scripts\python.exe -m pytest -q` and `cd ..\frontend; npm test`. A test fails if the version numbers disagree or the changelog does not lead with the current version.
3. If the release adds a database change, apply the new `supabase/update_*.sql` file in the Supabase SQL editor **before** deploying the backend.
4. Commit. Optionally tag it: `git tag vX.Y.Z`.

### 2. Deploy the backend

```powershell
python scripts/deploy.py --dry-run      # shows the commands, runs nothing
python scripts/deploy.py                # sam build, then sam deploy
```

What the script does:

- refuses to run if there are uncommitted changes, because the commit it stamps into the server would then not describe what is deployed (`--allow-dirty` overrides this);
- reads the `parameter_overrides` already in `samconfig.toml` and adds `GitCommit=<short commit id>`, so nothing else changes. Settings the config does not mention (the secrets) keep their previous values, exactly as with a plain `sam deploy`;
- finds `sam` on the PATH before running anything. On Windows the SAM CLI is `sam.cmd`, which the script resolves for you; if it is not installed you get a clear message instead of a crash;
- then runs `sam build` and `sam deploy`. SAM still asks you to confirm the change set (`confirm_changeset = true` in `samconfig.toml`).

### 3. Deploy the frontend

Push to `main`. Amplify builds and deploys automatically (Step 3c).

**Order:** to avoid a short period where the page is newer than the server (for a minor or major release the app then shows a "newer than the server" banner; a patch release does not, because patch differences are treated as compatible), commit locally, run `python scripts/deploy.py` first, and push afterwards. If the order is reversed nothing breaks; the banner just appears until the backend catches up.

### 4. Check it

- **Help → About AiFlow**: the page version and the server version are the same, and the server shows the commit you deployed (not `unknown`).
- `GET https://<api-gateway-url>/api/health` returns the version and commit.
- Run the post-deploy checklist (Step 4 below), at least the parts that touch what changed.

### If the script fails

| Symptom | Cause and fix |
| --- | --- |
| "There are uncommitted changes" | Commit first, or use `--allow-dirty` (the stamped commit will then be the previous one) |
| "'sam' was not found on the PATH" | Install the AWS SAM CLI and open a new terminal |
| A SAM or CloudFormation error | The script only wraps SAM; read the error as you would for a plain deploy |
| Anything else, or you simply prefer to | Use the manual steps in **Step 2b** below. They do the same thing; the only difference is that the server's commit shows as `unknown` |

The manual steps below are the explanation of what the script automates and the fallback if it ever breaks. They remain correct and are kept as they were; only their headings are relabelled, and a note on stamping the commit by hand is added to Step 2b.

---

## Prerequisites (first-time setup)

- [AWS CLI](https://docs.aws.amazon.com/cli/latest/userguide/install-cliv2.html) installed
- [AWS SAM CLI](https://docs.aws.amazon.com/serverless-application-model/latest/developerguide/install-sam-cli.html) installed
- [Node.js](https://nodejs.org/) 18+
- [Python](https://www.python.org/) 3.12+
- A Supabase project with `schema.sql` applied
- An LLM API key (OpenAI or compatible)

---

## Step 1 — Create a dedicated IAM user

Create a project-scoped AWS IAM user so deployments never use shared credentials.

### 1a — Create the user

AWS Console → **IAM → Users → Create user**

- Username: `aiflow-deploy`
- Access type: **Programmatic access only** (no Console login needed)

### 1b — Attach managed policies

Attach all 6 of these AWS managed policies:

| Policy | Why SAM needs it |
|---|---|
| `AWSCloudFormationFullAccess` | Creates / updates / deletes the stack |
| `AmazonS3FullAccess` | Uploads deployment artifacts to the SAM bucket |
| `AWSLambda_FullAccess` | Creates and updates the Lambda function |
| `AmazonAPIGatewayAdministrator` | Creates the API Gateway |
| `IAMFullAccess` | Creates the Lambda execution role (SAM does this automatically) |
| `CloudWatchLogsFullAccess` | Creates log groups for Lambda |

### 1c — Create access keys

**IAM → Users → aiflow-deploy → Security credentials → Create access key**

- Use case: **Command Line Interface (CLI)**
- Copy both keys — the secret is only shown once

### 1d — Configure a named AWS profile

```powershell
aws configure --profile aiflow
```

Enter when prompted:
```
AWS Access Key ID:     <your access key>
AWS Secret Access Key: <your secret key>
AWS Default region:    us-east-1
Default output format: json
```

Verify it works:
```powershell
aws sts get-caller-identity --profile aiflow
```

You should see the `aiflow-deploy` user ARN. The `aiflow` profile is already set in `samconfig.toml` — every `sam deploy` uses it automatically without touching your default credentials.

---

## Step 2 — Deploy the backend (Lambda + API Gateway)

### 2a — First deploy

```powershell
cd C:\dev\aiflow
sam build
sam deploy --guided
```

When prompted, enter:

| Parameter | Value |
|---|---|
| `LLMApiKey` | Your OpenAI API key |
| `SupabaseUrl` | `https://your-project.supabase.co` |
| `SupabaseServiceRoleKey` | From Supabase Dashboard → Settings → API |
| `SupabaseJwtSecret` | From Supabase Dashboard → Settings → API |
| `FrontendOrigin` | Your Amplify URL (e.g. `main.d1abc.amplifyapp.com`) — **without** `https://` |
| `AdminEmail` | Your email — auto-promoted to approved admin on startup |

SAM will output the **API Gateway URL** at the end — copy it, you'll need it for the frontend env var.

### 2b — Subsequent deploys (manual; this is what `scripts/deploy.py` automates)

```powershell
sam build && sam deploy
```
or do it one by one

```powershell
sam build
```

```powershell
sam deploy --profile aiflow
```

A plain `sam deploy` leaves the server's commit as `unknown`. To stamp it by hand, add the parameter yourself:

```powershell
sam deploy --parameter-overrides "<the overrides from samconfig.toml> GitCommit=$(git rev-parse --short HEAD)"
```

---

## Step 3 — Deploy the frontend (Amplify)

### 3a — Connect repo to Amplify

AWS Console → **Amplify → Create new app → From Git**

- Provider: GitHub
- Repo: `fuvito/aiflow`
- Branch: `main`
- Build settings: Amplify will detect `amplify.yml` automatically

### 3b — Set environment variables

In Amplify → App settings → Environment variables, add:

| Key | Value |
|---|---|
| `VITE_API_BASE_URL` | The API Gateway URL from Step 2a (e.g. `https://abc123.execute-api.us-east-1.amazonaws.com/Prod`) |
| `VITE_SUPABASE_URL` | `https://your-project.supabase.co` |
| `VITE_SUPABASE_ANON_KEY` | From Supabase Dashboard → Settings → API |
| `VITE_TURNSTILE_SITE_KEY` | Your Cloudflare Turnstile site key |

### 3c — Trigger a deploy

Push any commit to `main` — Amplify builds and deploys automatically. Or click **Run build** in the Amplify console.

---

## Step 4 — Post-deploy checklist

- [ ] `GET https://<api-gateway-url>/api/health` returns `{"status": "ok", "version": "...", "commit": "..."}`
- [ ] **Help → About AiFlow** shows the same version for the page and the server
- [ ] Landing page loads at the Amplify URL
- [ ] Login works and redirects to `/app`
- [ ] Workflow generate and simulate work end-to-end
- [ ] Admin panel accessible at `/app/admin`
- [ ] Backend logs show `bootstrap: promoted <email> to approved admin` on startup
- [ ] `https://<frontend-url>/guide` loads the user guide with its screenshots
- [ ] Open a cloud share link in a private window: the shared page loads without signing in (this needs the single-page-app rewrite in Amplify, which serves `index.html` for unknown paths)

---

## Env var reference

### Backend (Lambda — set via SAM parameters)

| Variable | Description |
|---|---|
| `LLM_API_KEY` | LLM provider API key |
| `LLM_MODEL` | Model name (default: `gpt-4o-mini`) |
| `LLM_BASE_URL` | Leave empty for OpenAI |
| `CORS_ORIGINS` | Set in `template.yaml` from the `FrontendOrigin` parameter, plus `https://aiflow.fuatyazar.com` and `http://localhost:5173` |
| `GIT_COMMIT` | Short commit id shown by `/api/health` and Help → About; set from the `GitCommit` parameter (`scripts/deploy.py` fills it in) |
| `SUPABASE_URL` | Supabase project URL |
| `SUPABASE_SERVICE_ROLE_KEY` | Supabase service role key (never expose to frontend) |
| `SUPABASE_JWT_SECRET` | Supabase JWT secret |
| `ADMIN_EMAIL` | Auto-promoted to approved admin on startup |
| `TURNSTILE_SECRET_KEY` | Cloudflare Turnstile secret key |
| `DEMO_MAX_EXECUTIONS_PER_DAY` | Default: 10 (0 = unlimited) |
| `DEMO_MAX_LLM_REQUESTS_PER_DAY` | Default: 20 (0 = unlimited) |
| `APPROVED_MAX_EXECUTIONS_PER_DAY` | Default: 0 (unlimited) |
| `APPROVED_MAX_LLM_REQUESTS_PER_DAY` | Default: 0 (unlimited) |

### Frontend (Amplify environment variables)

| Variable | Description |
|---|---|
| `VITE_API_BASE_URL` | API Gateway URL |
| `VITE_SUPABASE_URL` | Supabase project URL |
| `VITE_SUPABASE_ANON_KEY` | Supabase anon key (safe to expose) |
| `VITE_TURNSTILE_SITE_KEY` | Cloudflare Turnstile site key (safe to expose) |
