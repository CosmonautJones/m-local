# Fresh package execution

`.github/workflows/runtime-package-proof.yml` runs on changes to that workflow
on `codex/runtime-verification`. This narrow push trigger allows pre-release
verification while main is held for final review. GitHub's manual dispatch
requires the workflow to exist on the default branch; its declared manual
inputs will apply once that condition is met.

The first step reports actual available CPUs and raw MemTotal. A host below
four CPUs or 17,179,869,184 memory bytes stops before checkout, authenticated
artifact retrieval, downloads, storage provisioning or compiler execution.
The parent independently enforces Ubuntu 24.04, systemd, cgroup v2, root
provisioning, non-WSL, fresh storage and all bounded worker controls.

The push defaults bind the reviewed successful source commit
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
