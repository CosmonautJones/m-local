# Production startup admission

Use the release package launcher for supervised hosting. Its guard runs before
either serving process is spawned. For a controlled source-server invocation,
use the pinned WSL/Linux Bash entry:

```bash
bash scripts/production-start.sh --no-dev --host 127.0.0.1 --port 8200
```

This runs the pure Python production guard through official pinned `jacpython`,
then executes the unchanged native Jac server. Development configuration remains
usable. Missing or ambiguous production settings exit with status 78, report
setting names without values, and never start a native listener or serving child.
Outer whitespace in durable, onboarding and native-data paths is refused; inner
spaces in an exact preserved path are valid. Signing configuration follows the
official environment fallback and TOML semantics, retaining the original key.

Raw `jac run` is an unsupported production entry. Official Jac can resolve or
mint its signing key before application imports execute. The application import
guard still terminates unsafe native startup, but cannot prevent that earlier
path selection. The retained failed direct-start receipt demonstrates this
ordering; it is not a passing no-alternate-store proof. Do not delete or adopt
an alternate store as an automatic repair. Preserve existing identity and keys,
correct the setting through the operator procedure, and use preflight admission.

The preflight entry handles startup admission. Public serving additionally needs
the reviewed restricted gateway, one serialized upstream lane, durable original
state, process supervision and non-overlapping rollout. See the combined
candidate's hosting package. Neither raw native startup nor this source entry
alone establishes transaction safety, HTTPS ingress, host durability or recovery.
