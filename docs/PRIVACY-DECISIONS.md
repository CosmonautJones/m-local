# Human decisions before hosted acceptance

Engineering integration and synthetic tests do not approve collection, disclosure,
retention or destructive account deletion. Issues
[#41](https://github.com/CosmonautJones/m-local/issues/41) and
[#42](https://github.com/CosmonautJones/m-local/issues/42) stay open.

| Decision | Required human answer | Engineering boundary until answered |
| --- | --- | --- |
| Contact research and repository history | Approved destination, readers, retention, publication/removal scope and treatment of prior Git history | Preserve original material/history; no new outreach or public artifact upload. Source packages include tracked `data/research` and must remain private pending this decision. |
| Account and business records | Approved privacy/terms text, accountable operator, access/export process and retention periods | Do not advertise a completed privacy policy or implement destructive deletion. |
| Claims, disputes, merchant closure and audit | Retention and reconciliation rules for historical/held/redeemed claims, ownership, photos and attributed operator events | Suspension is reversible and preserves records. Account closure/deletion must not silently cancel claims or break ownership. |
| Consenting pilot | Named student/business testers, real-offer authority, consent and support/dispute contact | Synthetic fixture data is engineering evidence; no business contact or real email in this task. |

The new release archive and private synthetic recovery set are retained locally
for verification. Their local existence does not decide off-host backup readers,
retention or public release. Keep protected configuration, keys, credentials,
photos and private raw logs out of shared receipts. An operator must choose and
exercise protected off-host backup before hosted recovery can be accepted.

After policy decisions, verify the chosen text and implementation together on
the intended host, then record real inbox, iPhone Safari, Android Chrome and a
small consenting pilot using the exact deployed revision. See
[release gates](RELEASE-GATES.md), [phone testing](PHONE-TESTING.md) and
[backup/recovery](BACKUP-RECOVERY.md).
