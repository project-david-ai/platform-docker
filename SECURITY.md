# Security Policy

## Supported Versions

Security updates are provided for the latest stable release only. Make sure you are running the latest version before reporting a vulnerability.

| Version | Supported |
|---|---|
| >= 1.32.0 | ✅ |
| < 1.32.0 | ❌ |

---

## Reporting a Vulnerability

**Please do not open a public GitHub Issue for security vulnerabilities.**

If you discover a security-related issue in Project David, report it privately. All reports are handled with high priority by the maintainer.

**Email:** [engineering@projectdavid.co.uk](mailto:engineering@projectdavid.co.uk)

Include:
- A summary of the issue
- A proof of concept if available
- The version and component affected (Platform, Core API, Sandbox, Inference Worker, Training Pipeline, SDK)

**Acknowledgment:** within 48 hours
**Resolution:** coordinated fix and release before public disclosure

---

## Security Architecture

`pdavid --mode up` orchestrates the full Project David stack. This document covers the complete security posture of the platform and all components it manages. Operators running the platform stack should read this document in full before deployment in production or regulated environments.

---

### Platform Orchestrator

The `pdavid` CLI manages Docker Compose stack lifecycle from the host machine. A container guard exits immediately if the orchestrator detects it is running inside a Docker container, preventing Docker-in-Docker execution paths.

**Secret generation** — all platform secrets (database passwords, API keys, signing keys, sandbox tokens) are generated locally at first run using Python's `secrets` module with cryptographically secure entropy. No secrets are hardcoded in source or images. Secrets are written to a `.env` file on the operator's machine and excluded from Docker build contexts via `.dockerignore`.

**Docker socket** — the orchestrator and training worker both require access to the Docker socket (`/var/run/docker.sock`). Any process with Docker socket access has effective root on the host. Operators should restrict access to the socket to trusted users only.

**Environment variables** — `HF_TOKEN` and other credentials are passed to containers as environment variables. These are visible via `docker inspect` to any user with Docker socket access. Apply appropriate host-level controls.

**subprocess execution** — the orchestrator uses Python `subprocess` to run Docker Compose commands. `shell=True` is used on Windows hosts for PowerShell compatibility. All command arguments are constructed from internal values — no user input is passed to shell commands. Known suppressions are documented with `# nosec B602`.

---

### License Enforcement

Platform licensing uses an Ed25519 cryptographic offline mechanism. Validation is entirely local — no network call, no registration server, no telemetry. The license file is a signed JSON payload verified against a public key embedded in the platform binary. It cannot be forged without the private key and cannot be modified without invalidating the signature.

The platform will start and operate normally with no network access whatsoever, provided a valid license file is present on disk. The license file is suitable for delivery via USB or any out-of-band channel appropriate to the operator's environment.

---

### SSH Tunnel Manager

The `pdavid tunnel` command manages persistent SSH reverse tunnels from the HEAD node to remote GPU worker nodes. Key points for security review:

- Key-based authentication is enforced. Password authentication is disabled on the inference worker sshd.
- `StrictHostKeyChecking=accept-new` is used on first connection. Operators in high-security environments should pre-populate `known_hosts` and set `StrictHostKeyChecking=yes`.
- `ExitOnForwardFailure=yes` is set — the tunnel exits immediately if a port forward cannot be established rather than silently continuing with incomplete connectivity.
- Tunnel state is persisted to `~/.pdavid/tunnels.json`. This file contains host addresses and PIDs but no credentials.
- The tunnel forwards Ray, Redis, and MySQL ports from the remote worker back to the HEAD node's localhost. These ports are not exposed externally — they are accessible only to processes on the respective machines.

---

### Reverse Proxy and Rate Limiting

All inbound traffic passes through nginx before reaching any application service. nginx enforces:

- **Rate limiting** — 300 requests per minute per IP address with a burst allowance of 50 requests. Requests exceeding the burst are rejected immediately.
- **Request size limits** — 100 MB on the core API. Training endpoints accept up to 500 MB for dataset uploads.
- **Upstream retry** — failed upstream connections retry once before returning a 502/503/504.
- **SSE / streaming** — `X-Accel-Buffering: no` is set on all proxied responses for correct streaming behaviour through upstream CDN and load balancer layers.
- **HTTPS** — a TLS server block is included in the nginx configuration as a documented placeholder. Operators must enable it with their own certificates before exposing the platform to untrusted networks. The provided cipher configuration enforces TLSv1.2 and TLSv1.3 with strong ciphers.

The Ray dashboard (port 8265) and Ray client server (port 10001) are not exposed through nginx and are not accessible from outside the Docker network by default.

---

### API Key Authentication

Every API endpoint requires a valid API key. Keys are validated via a FastAPI dependency injected at the router level — there is no unauthenticated surface on the core API. The validated key object is passed into every route handler, making the authenticated user identity available throughout the request lifecycle.

API keys are stored hashed in the database. The plain key is returned exactly once at creation and is never stored or logged. Keys can be scoped, named, and revoked independently.

**Admin vs user scoping** — a subset of endpoints require the authenticated key's owner to hold admin status, checked against the database on each request. Regular user keys are rejected with HTTP 403 on admin-scoped routes.

**Self-service vs cross-user access** — API key management endpoints enforce that the authenticated key belongs to the requested user, or that the key owner is an admin. A user cannot read, create, or revoke keys belonging to another user.

---

### WebSocket Authentication

WebSocket endpoints require a short-lived signed JWT issued by the main API. The JWT is validated before the WebSocket connection is accepted — unauthenticated connections are closed with `WS_1008_POLICY_VIOLATION` before any data exchange. Room access is enforced at the token level: a JWT issued for room A cannot be used to join room B. User identity is taken exclusively from the verified JWT payload.

---

### Sandbox — Code Interpreter

The code interpreter executes user-submitted Python in a firejail sandbox with the following controls:

- `--private=<session_dir>` — process HOME is the session working directory
- `--caps.drop=all` — all Linux capabilities dropped
- `--seccomp` — system call filtering
- `--nogroups` — supplementary group memberships stripped
- `--nosound`, `--notv` — device access blocked

A static blocklist rejects submissions containing `__import__`, `exec`, `eval`, `subprocess`, `os.system`, `shutil.rmtree`, and related patterns before execution. Syntax is validated with `ast.parse` before the process is spawned. Temporary files are written to an isolated directory and cleaned up after each execution.

`DISABLE_FIREJAIL=true` disables sandboxing for local development. This must never be set in production.

---

### Sandbox — Computer Shell

The persistent shell uses firejail with per-process network namespace isolation:

- A new network namespace is created per shell session (`--net=eth0`)
- iptables netfilter rules applied inside that namespace:
  - Loopback allowed
  - Outbound DNS allowed
  - RFC-1918 ranges blocked (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16) — Docker-internal services unreachable from the shell
  - Public internet allowed
- At most one PTY process is alive per room at any time — stale sessions are torn down before new ones are registered
- Sessions auto-destruct after 5 minutes of inactivity
- Files generated during a session are harvested and uploaded to the file server on session end, then the session directory is wiped

`COMPUTER_SHELL_ALLOW_NET=true` bypasses the netfilter rules entirely. This must never be set in production.

---

### Inference Worker

The inference worker runs vLLM through Ray Serve. Each model deployment is isolated as a separate Ray Serve application. The worker container runs an OpenSSH daemon to support SSH tunnel connectivity from the HEAD node. Key-based authentication is enforced; password authentication is disabled.

`PermitRootLogin yes` is required for RunPod and similar cloud GPU providers. Operators running inference workers on controlled infrastructure should create a dedicated non-root user and set `PermitRootLogin no`.

When `RAY_ADDRESS` is set, the worker joins the cluster as a worker node via `ray start --address` before the Python inference process starts. When `RAY_ADDRESS` is empty, the worker starts as the Ray HEAD node.

---

### Training Pipeline

Training jobs are dispatched via Redis queue and consumed by the training worker as subprocess calls within the container. `HF_HUB_OFFLINE=1` prevents any outbound HuggingFace requests during training — required for fully air-gapped deployments.

---

### Dependency Scanning

All repos run Bandit, Ruff, and mypy in CI. Known suppressions are documented inline with `# nosec` annotations and justification. Third-party images in the compose file are pinned by SHA256 digest in production releases.

---

## Known Limitations

| Item | Status | Mitigation |
|---|---|---|
| HTTP only by default | Addressable | HTTPS server block documented in nginx config — enable with operator certificates |
| `PermitRootLogin yes` in inference worker | Addressable | Use dedicated non-root user on controlled infrastructure |
| `api_user@%` MySQL grant for tunnel deployments | Addressable | Restrict to tunnel IP range post-deployment |
| Docker socket access required by orchestrator and training worker | By design | Restrict Docker socket access to trusted users on the host |
| HF_TOKEN visible via `docker inspect` | By design | Apply host-level access controls on the Docker socket |
| No inter-container network policy | By design | Implement Docker network policies for segmented deployments |
| `shell=True` on Windows subprocess paths | By design | Windows-only; all arguments are internally constructed |
| `StrictHostKeyChecking=accept-new` on tunnel first connect | Addressable | Pre-populate `known_hosts` and set `StrictHostKeyChecking=yes` |
| firejail `--private` allows read access to system paths | Roadmap | Full filesystem overlay isolation planned |
| Rate limiting at nginx layer only | By design | No application-layer rate limiting — nginx is the enforcement point |

---

## Responsible Disclosure

Project David is maintained by a solo engineer. We appreciate your patience and your help in keeping the ecosystem safe for the operators and organisations depending on it across more than 100 countries.

*Project David is created and maintained by Francis Neequaye Armah.*
*All intellectual property is solely owned by the author.*
