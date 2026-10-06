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
It loads the resource helper from its verified committed bytes. A separately
bound launcher adapter preserves its resource controls and uses `setpriv` to
drop real and effective UID/GID to 65534 with no supplementary groups before
starting each scoped workload. Both original and adapted code hashes are
included in the sanitized summary. The fixture identity test does not replace
execution of the resource controls on a qualified full-package host.

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

The UI test tools also come from a fresh, private extraction of the fixed
official Node.js 22.16.0 archive and its published checksum file. The control
retains the original preparation assertions, checks the complete extracted
file inventory and link targets, and runs Node.js, npm and a small JavaScript
probe under UID/GID 65534. Scripts, receipts, binaries and resolved libraries
are bound by hashes and rechecked after package assembly. This establishes
the test-tool prerequisite; it does not run the application UI suite or prove
browser compatibility, performance or production runtime adoption.

The manual defaults bind the reviewed successful source commit
`82d2789dcbbfea32d3362ee4008104b7e52b193a` and run `37532312763`.
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

The parent prepares the ten transaction scripts and two separate source
interface scripts from the authenticated public source inputs. It checks the
frozen controller, raw probes and loader before applying only the original
path and disposable-workspace substitutions. The generated files and receipt
are bound by hashes and rechecked after assembly. Their status is `prepared_not_executed`,
with `executed: false`; the authenticated source run's aggregate results remain
separate evidence. These files still need to be adapted and executed against
the sealed package before compatibility acceptance. The UI dependency
installation also needs fresh, bound inputs before full-suite acceptance.

The dependency preparation workflow resolves only the existing `jsdom@26.1.0`
browser-test prerequisite using the verified private Node.js 22.16.0 and npm
10.9.2 tools. It downloads every package in the generated lockfile, checks each
tarball's integrity, and seeds a separate empty cache from those downloads.
It then checks a script-free offline `npm ci` and a small DOM probe under
UID/GID 65534. Only public package metadata, the lockfile and a preparation
receipt are exported. The reviewed graph must be frozen in committed inputs
before the full suite consumes it; a newly generated artifact cannot replace
those commitments automatically. This fixture does not run application browser
tests or change the full package host requirements.
Tar validation permits harmless `.` path aliases only inside the package root.
Repeated normalized files must match in type, permissions, size and content;
every physical entry still counts toward member and expanded-byte limits.
The DOM probe reads the running Node process's kernel supplementary group list
from `/proc/self/status`; it must be empty. Node's `process.getgroups()` includes
the effective group, so that API does not represent this empty-list control.

The reviewed 39-package graph is frozen in `ui-dependency-inputs/v1/`, with
exact file hashes and inventory checked by the package-input workflow. Its
preparation evidence is the successful [dependency job at `0b82936`](https://github.com/CosmonautJones/m-local/actions/runs/37535107874).
The parent now consumes these exact committed files after package acceptance,
checks fresh tarball sizes, hashes and integrity, and populates an empty private
cache before an offline installation and DOM probe. Each command uses the
bounded workload launcher and a private root-owned log. The installed files,
Node tools, mounts and preparation receipt are rechecked before cleanup.
The live dependency directory remains available for the later application
test adapter; the public summary contains hashes and counts only. A supported
Linux fixture exercises this installation and rejects mutated receipts and
files. Its status remains `dependencies_prepared`, with application tests
explicitly unexecuted. Full application suite integration and execution remain
required before compatibility acceptance.

The nine original compatibility, catalog, loader and native-gate sources are
also frozen byte-for-byte in `native-inputs/native-suite-v5/`. Their manifest
retains all 24 compatibility phases, both separate source interfaces, the six
physical catalog mutation cases, and strict graph coverage counts. The input
check verifies their committed bytes without executing any original script.
Fresh storage, cache, source-denial, tool, loader and dependency bindings still
need to be connected by a reviewed adapter before full-suite acceptance.
