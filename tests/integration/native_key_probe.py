"""Disposable native-key compatibility probe; never an application launcher.

The parent SQL fixture supplies an owned request and an independent original-key
fingerprint. Only synthetic material belongs here. Public stdout is redacted.
"""
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import sys
import traceback
from uuid import UUID


PLACEHOLDER = 'supersecretkey_for_testing_only!'


class ProbeRefusal(ValueError):
    pass


def effective_key(material, expected_sha256):
    # Failing-first seed: preserve the existing raw-key conversion before
    # enforcing the independent preservation/representability boundary.
    return material.decode('utf-8').strip()


def owned_request(path):
    path = Path(path)
    if path.is_symlink():
        raise ProbeRefusal('request')
    path = path.resolve(strict=True)
    temporary = Path(os.environ['TMPDIR']).resolve(strict=True)
    if not path.is_relative_to(temporary) or path.is_symlink():
        raise ProbeRefusal('request')
    request = json.loads(path.read_text())
    root = Path(request['fixture_root']).resolve(strict=True)
    if (not root.is_relative_to(temporary) or not root.parent.name.startswith('mlocal-aux-')
            or path.parent != root or request.get('synthetic_disposable_only') is not True):
        raise ProbeRefusal('fixture')
    for field in ('base', 'entry', 'original_home', 'packet'):
        candidate = Path(request[field])
        if not candidate.is_absolute() or not candidate.resolve().is_relative_to(root):
            raise ProbeRefusal('path')
    if request['phase'] not in {'admit', 'resolve', 'seed', 'verify', 'verify-wrong-secret'}:
        raise ProbeRefusal('phase')
    return request


def select_material(request):
    from services.onboarding_backend import backend_name
    from services.postgres_auxiliary import PostgresAuxiliary
    if os.environ.get('MLOCAL_ENV', '').strip().lower() == 'production':
        raise ProbeRefusal('production')
    selection = backend_name()
    # Reuse the established loopback/test-database/schema constructor guard even
    # for baseline file signing, before native JAC_DB_URL can be configured.
    backend = PostgresAuxiliary(request['dsn'], request['schema'])
    if selection == 'sqlite':
        path = Path(request['original_home']) / '.jac/data/jwt_secret'
        if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(Path(request['fixture_root'])):
            raise ProbeRefusal('original')
        material = path.read_bytes()
    else:
        material = backend.signing_material()['native_key']
    return selection, material, effective_key(material, request['expected_raw_sha256'])


def private_json(path, value):
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
        json.dump(value, stream, sort_keys=True)
        stream.write('\n')


def run(request):
    for name in tuple(os.environ):
        if (name.startswith('JAC_SERVE_') or name.startswith('JAC_DB_SCRATCH')
                or name in {'JAC_DB_URL', 'JAC_DATA_PATH', 'JAC_DEV_SOURCE',
                            'KUBERNETES_SERVICE_HOST', 'PGHOSTADDR', 'PGSERVICE', 'PGSERVICEFILE'}):
            os.environ.pop(name, None)
    os.environ['MLOCAL_ONBOARDING_BACKEND'] = request['selection']
    os.environ['MLOCAL_ENV'] = request.get('environment', 'development')
    request['_stage'] = 'admission'
    selection, material, effective = select_material(request)
    result = {'status': 'ok', 'phase': request['phase'], 'stage': 'admitted',
              'pid': os.getpid(), 'selection': selection,
              'raw_sha256': hashlib.sha256(material).hexdigest()}
    if request['phase'] == 'admit':
        return result

    # No native context/settings are initialized before successful admission.
    request['_stage'] = 'settings'
    os.environ['JAC_DB_URL'] = request['dsn']
    if selection == 'postgres-proof':
        os.environ['JAC_SERVE_AUTH_SECRET'] = effective
    else:
        os.environ['JAC_DATA_PATH'] = request['original_home']
    base, entry = str(Path(request['base'])), str(Path(request['entry']))
    os.chdir(base)
    from jaclang.project.config import JacConfig, set_config
    config = JacConfig(project_root=Path(base))
    set_config(config)
    from jaclang.server.settings import ServeSettings
    from jaclang.server.identity.config import configure_identity, signing_secret
    from jaclang.server.serving.authcrypt import PLACEHOLDER_JWT_SECRET
    assert PLACEHOLDER_JWT_SECRET == PLACEHOLDER
    settings = ServeSettings.load(base_path=base, config=config)
    assert settings.auth.algorithm == 'HS256'
    if selection == 'postgres-proof':
        assert settings.auth.secret == effective and effective
    else:
        assert settings.auth.secret.strip() in {'', PLACEHOLDER}
    assert settings.auth.resolve_secret(base) == effective
    configure_identity(settings.auth, base)
    assert signing_secret() == effective
    result.update(stage='resolved', effective_sha256=hashlib.sha256(effective.encode()).hexdigest(),
                  sql_nonblank_env=selection == 'postgres-proof' and bool(os.environ.get('JAC_SERVE_AUTH_SECRET')),
                  canonical_base=base, canonical_entry=entry)
    if request['phase'] == 'resolve':
        return result

    from jaclang.runtime.runtime import JacRuntime as Jac
    from jaclang.server.session import Session
    from jaclang.data.store import PgStore
    from jaclang.server.identity.user_manager import UserManager
    from jaclang.server.shared_store import shared_store
    from jaclang.data.pgpool import drain_all
    request['_stage'] = 'native'
    Jac.set_base_path(base)
    Jac.set_full_target_path(entry)
    context = Jac.create_j_context(None, base, entry)
    Jac.set_context(context)
    users = None
    try:
        assert isinstance(context.mem, Session)
        assert isinstance(context.mem.store, PgStore)
        users = UserManager(base_path=base, provision_unknown_users=False)
        packet_path = Path(request['packet'])
        if request['phase'] == 'seed':
            rows = []
            for index in range(2):
                name = 'native-key-fixture-' + secrets.token_hex(8)
                created = users.create_user_with_identities(
                    [{'type': 'username', 'value': name},
                     {'type': 'email', 'value': name + '@example.test', 'verified': index == 0}],
                    {'type': 'password', 'password': secrets.token_urlsafe(32)},
                    {'fixture_only': True, 'index': index})
                assert created.get('user_id') and created.get('root_id') and not created.get('error')
                user = users.get_user(created['user_id'])
                assert user['role'] == 'user' and user['status'] == 'active'
                rows.append({'user': user, 'token': users.create_jwt_token(user['user_id'])})
            private_json(packet_path, rows)
        else:
            rows = json.loads(packet_path.read_text())
        assert len(rows) == 2
        for row in rows:
            user, token = row['user'], row['token']
            detail = users.validate_jwt_token_detail(token, check_existence=True)
            assert detail['status'] == 'ok' and detail['user_id'] == user['user_id']
            assert users.get_user(user['user_id']) == user
            assert UUID(users.get_root_id(user['user_id'])).hex == UUID(user['root_id']).hex
            context.set_user_root(user['root_id'])
            assert context.user_root.id.hex == UUID(user['root_id']).hex
            for identity in user['identities']:
                assert users.find_user_by_identity(identity['value_normalized'])['user_id'] == user['user_id']
            parts = token.split('.')
            parts[2] = ('A' if parts[2][0] != 'A' else 'B') + parts[2][1:]
            denied = users.validate_jwt_token_detail('.'.join(parts), check_existence=True)
            assert denied['status'] == 'invalid' and denied['user_id'] is None
        if request['phase'] == 'verify-wrong-secret':
            original_setting = settings.auth.secret
            settings.auth.secret = 'synthetic-deliberately-wrong-native-secret-only'
            configure_identity(settings.auth, base)
            for row in rows:
                denied = users.validate_jwt_token_detail(row['token'], check_existence=True)
                assert denied['status'] == 'invalid' and denied['user_id'] is None
            settings.auth.secret = original_setting
            configure_identity(settings.auth, base)
            assert signing_secret() == effective
            assert all(users.validate_jwt_token_detail(row['token'], check_existence=True)['status'] == 'ok' for row in rows)
        result.update(stage='verified', identities=2, original_tokens_verified=2,
                      token_issuance=request['phase'] == 'seed', actual_session_pgstore=True,
                      wrong_native_secret_denied=request['phase'] == 'verify-wrong-secret')
        return result
    finally:
        if users is not None:
            users.close()
        context.close()
        store = shared_store()
        if store is not None:
            store.close()
        drain_all()


def main():
    stage = 'request'
    request = {}
    try:
        if len(sys.argv) != 2:
            raise ProbeRefusal('arguments')
        request = owned_request(sys.argv[1])
        stage = 'admission'
        result = run(request)
        print(json.dumps(result, sort_keys=True))
    except Exception as error:
        last = traceback.extract_tb(error.__traceback__)[-1]
        print(json.dumps({'status': 'refused' if isinstance(error, ValueError) else 'error',
                          'phase': request.get('phase', 'unknown'), 'stage': request.get('_stage', stage),
                          'error_class': type(error).__name__, 'line': last.lineno}, sort_keys=True))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
