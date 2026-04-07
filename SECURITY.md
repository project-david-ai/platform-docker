# Security Policy

## Supported Versions

Security updates are provided for the latest stable release only. Ensure you are running the latest version from PyPI before reporting a vulnerability.

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
- The version and component affected (Core, Platform, SDK)

**Acknowledgment:** within 48 hours
**Resolution:** coordinated fix and release before public disclosure

We ask that you do not disclose the issue publicly until a patched version has been released.

---

## Security Architecture

Project David is designed from the ground up for deployment in security-sensitive, air-gapped, and sovereignty-constrained environments. The following documents the current security posture of the platform.

### License Enforcement

Platform licensing uses an Ed25519 cryptographic offline mechanism. Validation is entirely local — no network call, no registration server, no telemetry. The license file is a signed JSON payload verified against a public key embedded in the binary. It cannot be forged without the private key and cannot be modified without invalidating the signature.

The platform will start and operate normally with no network access whatsoever, provided a valid license file is present on disk.

### Secret Management

All platform secrets (database passwords, API keys, signing keys) are generated locally at first run using Python's `secrets` module. No secrets are hardcoded in source code or container images. Secrets are stored in a `.env` file on the operator's machine and are explicitly excluded from Docker build contexts via `.dockerignore`.

`HF_TOKEN`, when set, is passed to containers as an environment variable. Operators in classified environments should be aware that environment variables are visible via `docker inspect` and should apply appropriate host-level access controls.

### SSH Tunnel

The `pdavid tunnel` command establishes SSH reverse tunnels from the HEAD node outbound to remote worker nodes. Key-based authentication is enforced. Password authentication is disabled. The tunnel uses `StrictHostKeyChecking=accept-new` on first connection — operators in high-security environments should pre-populate `known_hosts` and set `StrictHostKeyChecking=yes` via the `--key` flag workflow.

### Database Access

The platform database user (`api_user`) is created with `localhost` access only by default. Operators extending the cluster via SSH tunnel who require remote database access should grant access to specific tunnel IP ranges rather than the wildcard `%` host. The wildcard grant is documented as a cluster setup step and should be reviewed and tightened post-deployment.

### Container Networking

All platform services run on a shared Docker bridge network (`my_custom_network`). There is no inter-container network policy by default — any container on the network can reach any other container. Operators requiring network segmentation should implement Docker network policies or deploy behind a service mesh appropriate to their environment.

### Inference Worker SSH

The inference worker container runs an OpenSSH daemon to support SSH tunnel connectivity from the HEAD node. `PermitRootLogin yes` is set to support RunPod and similar cloud GPU providers where root is the only available user. Operators running inference workers on controlled infrastructure should create a dedicated non-root user and set `PermitRootLogin no` in the sshd configuration.

### subprocess and Shell Execution

The platform orchestrator uses Python `subprocess` with `shell=True` on Windows hosts to ensure compatibility with PowerShell. This is flagged and suppressed (`# nosec B602`) with justification in the source. All command arguments are constructed from internal values — no user-supplied input is passed to shell commands.

### Dependency Scanning

All repos run Bandit, Ruff, and mypy in CI. Known suppressions are documented inline with `# nosec` annotations. Third-party images in the platform compose file are pinned by SHA256 digest.

---

## Known Limitations

The following are known architectural constraints that operators should factor into their deployment risk assessment:

| Item | Status | Mitigation |
|---|---|---|
| `api_user@%` MySQL grant for tunnel deployments | Addressable | Restrict to tunnel IP range post-deployment |
| `PermitRootLogin yes` in inference worker | Addressable | Use dedicated non-root user on controlled infrastructure |
| HF_TOKEN visible via `docker inspect` | By design | Apply host-level access controls on the Docker socket |
| No inter-container network policy | By design | Implement Docker network policies for segmented deployments |
| `shell=True` on Windows subprocess | By design | Windows-only code path, arguments are internally constructed |

---

## Responsible Disclosure

Project David is maintained by a solo engineer. We appreciate your patience and your help in keeping the ecosystem safe for the operators and organisations depending on it across more than 100 countries.

*Project David is created and maintained by Francis Neequaye Armah.*
*All intellectual property is solely owned by the author.*
