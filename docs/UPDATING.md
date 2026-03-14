# Applying Platform Updates

The Project David platform has two independently versioned components.
Understanding which has changed determines what action is required.

---

## Component 1 — Docker Images

**Owned by:** `entities_api` repository  
**Published to:** Docker Hub (`thanosprime/entities-api-api`, `thanosprime/entities-api-sandbox`)  
**Updated when:** Bug fixes, new features, or model changes are shipped in the API source code.

**Action required from architect:**

```bash
pdavid --mode up --force-recreate
```

No pip upgrade needed. Docker pulls the latest images and restarts the
affected containers. Volumes and data are untouched.

---

## Component 2 — Platform Orchestrator

**Owned by:** `platform-docker` repository  
**Published to:** PyPI (`projectdavid-platform`)  
**Updated when:** The compose configuration changes — new services, new environment
variables, port mapping changes, CLI improvements, or security fixes in secret generation.

**Action required from architect:**

```bash
pip install --upgrade projectdavid-platform
pdavid --mode up --force-recreate
```

The pip upgrade delivers updated compose files and orchestration logic.
The `--force-recreate` applies them to the running stack.

---

## Which update do I need?

| What changed | Pip upgrade needed? | Force recreate needed? |
|---|---|---|
| API bug fix or new feature | No | Yes |
| New service added to stack | Yes | Yes |
| New environment variable required | Yes | Yes |
| New `pdavid` CLI command | Yes | Yes |
| Port or network configuration changed | Yes | Yes |

When in doubt, check the release notes for both repositories before updating.

---

## Important

Always upgrade the pip package **before** running `--force-recreate` when a
platform orchestrator release has been issued. Running new images against an
outdated compose configuration may cause containers to crash if new required
environment variables are missing.

A `pdavid --check-update` command is on the roadmap to detect and warn about
this mismatch automatically before any action is taken.

---

## Data Safety

Neither update path touches your data volumes. The only action that affects
data is `pdavid --nuke`, which requires explicit interactive confirmation
and should never be part of a routine update.