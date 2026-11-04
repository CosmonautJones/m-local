"""Operator endpoints authorized by a host-held secret, never by an account.

download_backup answers only with MLOCAL_BACKUP_TOKEN set on the host and the
same token in the request body. See services/hosted_backup.py and
docs/HOSTED-BACKUPS.md.
"""

import from services.hosted_backup { snapshot, BackupRefused }
import from services.promo { _lock, _unlock }

obj BackupResult {
    has ok: bool = False,
        message: str = "",
        backup: str = "";
}


"""One coordinated backup as a JSON string, taken under the mutation lock."""
def:pub download_backup(token: str) -> BackupResult {
    try {
        fd = _lock();
        data = "";
        try { data = str(snapshot(token)); }
        finally { _unlock(fd, False); }
        return BackupResult(ok=True, message="Backup ready.", backup=data);
    } except BackupRefused as error {
        return BackupResult(message=str(error));
    } except Exception {
        return BackupResult(message="The backup could not be taken. Nothing was changed; try again later.");
    }
}
