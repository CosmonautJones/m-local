# Release Checklist

Status: not release-ready. Unverified items remain explicitly open.

The current public-launch gates are in [release acceptance](RELEASE-ACCEPTANCE.md).
CI passed at `8e369f9`, including 13 access-context tests without skips; the recovery [receipt](review/recovery-v61/verification.json)
and exact [Git source binding](review/recovery-v61/source-binding.json) retain
their tested revisions. This checklist does not certify the public deployment.

- [x] Jac 0.37.23 pinned and checksum-verified.
- [x] Runtime resolver rejects mismatched binaries.
- [x] Source check passes.
- [x] Strict isolated core and insights tests pass in current CI; missing imports cannot silently skip coverage.
- [x] Production `.jab` build passes.
- [x] Isolated demo server returns HTTP 200.
- [x] Compiled UI, gateway and deployment tooling checks pass in current CI.
- [x] Aggregate command propagates missing-suite/account failures.
- [x] Separate strict access-context suite passes in [CI at 8e369f9](https://github.com/CosmonautJones/m-local/actions/runs/37414464801).
- [ ] Provision local demo accounts and run `tests/integration/qr_http.py`.
- [x] Disposable HTTP approval and coordinated recovery fixtures verify same-store and post-restore restart persistence.
- [ ] Verify persistence and coordinated recovery on the actual public deployment, including RPO/RTO.
- [ ] Verify simultaneous last-unit claims and redemptions over HTTP.
- [ ] Separate users share the public catalog without private QR credentials.
- [ ] Second teammate reproduces setup from a clean clone.
- [ ] iPhone Safari and Android camera flow verified on a supported secure origin.
- [ ] Baz review and source-language inventory completed.
- [ ] Organizer deadline confirmed and demo evidence recorded.
- [ ] Deployment decision authorized by the human team.

No credentials, passwords, or private account files belong in Git.
