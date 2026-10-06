# Fresh package execution

The initial branch push proved that the standard GitHub runner stops at the
package memory guard. Automatic package runs are disabled to avoid retrying
that unchanged, unqualified host. `.github/workflows/runtime-package-proof.yml`
retains manual dispatch; GitHub requires the workflow on the default branch.
A qualified host and reviewed execution connection are still required.

The first step reports actual available CPUs and raw MemTotal. A host below
four CPUs or 17,179,869,184 memory bytes stops before checkout, authenticated
artifact retrieval, downloads, storage provisioning or compiler execution.
The parent independently enforces Ubuntu 24.04, systemd, cgroup v2, root
provisioning, non-WSL, fresh storage and all bounded worker controls.

After provisioning storage and before runtime downloads or compiler work,
the parent runs the pinned source-isolation control on fresh owned fixtures.
It proves readable baselines, four permission-denied operations under
UID/GID 65534 with zero capabilities, and exact restoration of directory
ownership, permissions, inode and contents. The separate package-input
workflow exercises this control on a small disposable Linux filesystem.
This fixture result does not prove candidate/source isolation throughout
application compatibility or native execution; those remain separate gates.

The parent also downloads two fixed official tracing-client archives, checks
their declared sizes and hashes, and extracts them only inside a fresh owned
private mount. The declared rolling repository index pin is provenance; execution
does not require that mutable index to retain its historical bytes. Frozen
controls prove a real file read under UID/GID 65534 and removal of the client's
library environment from the traced program. Scripts and receipts are bound
by hashes, and both receipts are rechecked before the acceptance summary.
The package-input workflow exercises these controls on a disposable Linux
filesystem. This verifies the tracing fixture; tracing the fresh candidate
through compatibility, native HTTP and capacity still requires execution.

The PostgreSQL client fixture downloads fixed PGDG client and libpq archives
and extracts them privately. It checks PostgreSQL 18.6 tool versions, binary
and dynamic-library hashes, and execution under UID/GID 65534. Missing host
libraries fail the check. It installs no system packages and starts no database.
The original extractor receipt and a separate dependency binding are sealed
and rechecked before acceptance. This proves client setup only; database
durability, backup/restore and sustained capacity require their own execution.

The manual defaults bind the reviewed successful source commit
`990c7b33c920e6a93431d34a01df7b8c87c432ba` and run `37477834755`.
The parent authenticates their exact successful job and unexpired artifact,
then checks the archive and every committed source/package input. Updating
these defaults requires current successful source evidence. Caller-supplied
manual input values never become shell commands.

The workflow verifies the fixed parent and declaration entry point hashes
before executing them. Credentials are confined to the authentication step,
passed through the environment and excluded from worker environments.
The job has a six-hour limit; an outer 21,000-second deadline and 90-second
termination grace leave time for owned cleanup within that limit.

The job uploads no payloads, private caches or logs. Only the parent's
sanitized acceptance summary is printed after successful independent byte
verification and cleanup. A green package job proves package assembly only;
application compatibility, native HTTP, sustained capacity, runtime adoption
and full release acceptance still require separate current evidence.
