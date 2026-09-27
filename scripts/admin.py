#!/usr/bin/env python3
"""Admin tool for reviewing business applications and provisioning merchant access.

Usage:
    python3 scripts/admin.py list                         # Show pending applications
    python3 scripts/admin.py decisions                    # Show all decisions
    python3 scripts/admin.py approve <actor_id>           # Approve and create restaurant
    python3 scripts/admin.py reject <actor_id> --reason "Why"  # Reject application

Approval creates a Restaurant and Location in the shared graph via the running
Jac server, then updates MLOCAL_MERCHANT_OWNERS so the applicant gains merchant
access after a server restart.

Requires a running Jac server (default http://localhost:8000) and admin
credentials set via MLOCAL_ADMIN_USER / MLOCAL_ADMIN_PASSWORD env vars, or
--api-token for direct JWT authentication.

Safety:
    - Repeated approval returns the existing slug (no duplicates).
    - Applicants only get the restaurant created by their approval.
    - Rejection is final and includes a reason.
    - Decisions cannot be reversed (approve→reject or reject→approve).
"""
import argparse
import json
import os
import shlex
import secrets
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

# Allow importing from scripts/ directory
sys.path.insert(0, str(Path(__file__).resolve().parent))
from admin_decisions import (
    list_pending,
    list_decisions,
    get_draft,
    existing_decision,
    record_approval,
    record_rejection,
)


def local_api(value):
    parsed = urllib.parse.urlsplit(value)
    if parsed.scheme != 'http' or parsed.hostname not in ('localhost', '127.0.0.1', '::1'):
        raise argparse.ArgumentTypeError('Use the local Jac API (e.g. http://localhost:8000).')
    return value.rstrip('/')


def post(api, path, body, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = f'Bearer {token}'
    req = urllib.request.Request(
        api + path, json.dumps(body).encode(), headers, method='POST')
    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as error:
        detail = ''
        try:
            detail = error.read().decode()[:200]
        except Exception:
            pass
        raise RuntimeError(f'{path} returned HTTP {error.code}: {detail}') from None


def get_admin_token(api, user, password):
    """Authenticate as admin and return JWT token."""
    result = post(api, '/user/login', {
        'identity': {'type': 'email', 'value': user},
        'credential': {'type': 'password', 'password': password},
    })
    data = result.get('data', result)
    token = data.get('token') or data.get('access_token')
    if not token:
        raise RuntimeError('Admin login failed. Check credentials.')
    return token


def create_restaurant_via_api(api, token, slug, draft):
    """Create Restaurant + Location in the shared graph using a Jac script."""
    record = {
        'slug': slug,
        'name': draft.get('name', ''),
        'cuisine': draft.get('cuisine', ''),
        'blurb': draft.get('description', ''),
        'is_demo': False,
        'source': 'application',
        'location': {
            'address': draft.get('address', ''),
            'neighborhood': '',
            'entrance_note': '',
            'note_date': '',
        },
        'menu': [],
        'offers': [],
    }
    
    # We use a local Jac script to mutate the graph database directly.
    jac_bin = os.environ.get('JAC_BIN', 'jac')
    script_path = Path(__file__).resolve().parent / 'create_restaurant.jac'
    
    env = dict(os.environ, MLOCAL_RESTAURANT_RECORD=json.dumps(record))
    import subprocess
    result = subprocess.run(
        [jac_bin, 'run', str(script_path)],
        env=env, capture_output=True, text=True
    )
    if result.returncode != 0 or 'Success' not in result.stdout:
        raise RuntimeError(f"Failed to create restaurant in graph: {result.stderr}\n{result.stdout}")
    return result.stdout


def read_merchant_owners_env():
    """Read current MLOCAL_MERCHANT_OWNERS from the env files."""
    env_paths = [
        Path('.jac/qr-demo.env'),
        Path('.jac/onboarding.env'),
    ]
    current = {}
    for path in env_paths:
        if path.exists():
            for line in path.read_text().splitlines():
                if line.startswith('export MLOCAL_MERCHANT_OWNERS='):
                    value = line.split('=', 1)[1]
                    # Strip shell quoting
                    if value.startswith("'") and value.endswith("'"):
                        value = value[1:-1]
                    elif value.startswith('"') and value.endswith('"'):
                        value = value[1:-1]
                    try:
                        current = json.loads(value)
                    except json.JSONDecodeError:
                        pass
    # Also check live environment
    env_val = os.environ.get('MLOCAL_MERCHANT_OWNERS', '')
    if env_val:
        try:
            live = json.loads(env_val)
            if isinstance(live, dict):
                current.update(live)
        except json.JSONDecodeError:
            pass
    return current


def update_merchant_owners_env(slug, actor_id):
    """Add a slug→actor mapping to the merchant owners env file.

    Uses .jac/merchant-owners.env as the canonical file for approved merchants.
    This is separate from qr-demo.env to avoid mixing demo and real accounts.
    """
    env_path = Path('.jac/merchant-owners.env')
    env_path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

    # Read existing mappings from this file
    current = {}
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            if line.startswith('export MLOCAL_MERCHANT_OWNERS='):
                value = line.split('=', 1)[1]
                if value.startswith("'") and value.endswith("'"):
                    value = value[1:-1]
                try:
                    current = json.loads(value)
                except json.JSONDecodeError:
                    pass

    # Normalize actor to 32-hex
    actor_hex = UUID(actor_id).hex

    # Check: do not overwrite existing mappings for different actors
    if slug in current and current[slug] != actor_hex:
        raise ValueError(f'Slug {slug} is already assigned to a different actor. This should not happen.')

    current[slug] = actor_hex

    # Write atomically
    content = 'export MLOCAL_MERCHANT_OWNERS=' + shlex.quote(json.dumps(current)) + '\n'
    temp = env_path.with_name(env_path.name + '.tmp-' + secrets.token_hex(6))
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w') as stream:
            stream.write(content)
        os.replace(temp, env_path)
        os.chmod(env_path, 0o600)
    finally:
        temp.unlink(missing_ok=True)

    return env_path


def format_time(ts):
    if not ts:
        return '(unknown)'
    return datetime.fromtimestamp(ts, tz=timezone.utc).strftime('%Y-%m-%d %H:%M UTC')


def cmd_list(args):
    pending = list_pending()
    if not pending:
        print('No pending applications.')
        return

    print(f'\n  {len(pending)} pending application(s):\n')
    for i, app in enumerate(pending, 1):
        print(f'  [{i}] Actor:    {app["actor_id"]}')
        print(f'      Email:    {app["email"]}')
        print(f'      Name:     {app["applicant_name"]}')
        print(f'      Business: {app["business_name"]}')
        print(f'      Cuisine:  {app["cuisine"]}')
        print(f'      Address:  {app["address"]}')
        if app.get('website'):
            print(f'      Website:  {app["website"]}')
        print(f'      Applied:  {format_time(app.get("submitted_at"))}')
        print()


def cmd_decisions(args):
    decisions = list_decisions()
    if not decisions:
        print('No decisions recorded.')
        return

    print(f'\n  {len(decisions)} decision(s):\n')
    for d in decisions:
        status = '✅ APPROVED' if d['decision'] == 'approved' else '❌ REJECTED'
        print(f'  {status}  actor={d["actor"]}')
        print(f'           email={d.get("email", "(unknown)")}')
        if d.get('slug'):
            print(f'           slug={d["slug"]}')
        if d.get('reason'):
            print(f'           reason={d["reason"]}')
        print(f'           at={format_time(d.get("decided_at"))}')
        print()


def cmd_approve(args):
    actor = args.actor_id
    # Normalize
    try:
        actor = UUID(actor).hex
    except ValueError:
        print(f'Error: Invalid actor ID format: {actor}')
        sys.exit(1)

    # Check draft exists
    draft = get_draft(actor)
    if not draft:
        print(f'Error: No application found for actor {actor}.')
        sys.exit(1)

    print(f'Application details:')
    print(f'  Business: {draft.get("name", "(empty)")}')
    print(f'  Cuisine:  {draft.get("cuisine", "(empty)")}')
    print(f'  Address:  {draft.get("address", "(empty)")}')
    print(f'  Status:   {draft.get("status", "(unknown)")}')
    print()

    # Record decision (idempotent)
    try:
        result = record_approval(actor, slug_override=args.slug or '')
    except ValueError as e:
        print(f'Error: {e}')
        sys.exit(1)

    slug = result['slug']

    if result.get('already'):
        print(f'Already approved as "{slug}". Checking env file...')
    else:
        print(f'Approved with slug: {slug}')

    # Create restaurant via API
    if not args.skip_graph:
        api = args.api
        token = args.api_token
        if not token:
            admin_user = os.environ.get('MLOCAL_ADMIN_USER', '')
            admin_password = os.environ.get('MLOCAL_ADMIN_PASSWORD', '')
            if not admin_user or not admin_password:
                print('\nWarning: No API token or admin credentials. Skipping graph creation.')
                print('Set MLOCAL_ADMIN_USER/MLOCAL_ADMIN_PASSWORD or --api-token, then re-run.')
                print('Or use --skip-graph to only record the decision and update the env file.')
                args.skip_graph = True
            else:
                try:
                    token = get_admin_token(api, admin_user, admin_password)
                except RuntimeError as e:
                    print(f'\nWarning: Could not authenticate: {e}')
                    print('Skipping graph creation. Restaurant will be created on next server start.')
                    args.skip_graph = True

    if not args.skip_graph:
        try:
            print(f'Creating restaurant "{draft.get("name", slug)}" in shared graph...')
            create_restaurant_via_api(api, token, slug, draft)
            print('Restaurant and location created in graph.')
        except RuntimeError as e:
            print(f'Warning: Graph creation issue: {e}')
            print('The restaurant may need to be created manually or on server restart.')

    # Update merchant owners env
    try:
        env_path = update_merchant_owners_env(slug, actor)
        print(f'Merchant ownership recorded in {env_path}')
    except (ValueError, OSError) as e:
        print(f'Warning: Could not update env file: {e}')
        print(f'Manually add to MLOCAL_MERCHANT_OWNERS: {{"{slug}": "{actor}"}}')

    print()
    print('Next steps:')
    print(f'  1. Source the env file:  source .jac/merchant-owners.env')
    print(f'  2. Restart the server:  bash scripts/dev.sh')
    print(f'  3. The merchant can now sign in and use merchant_portal/save_offer.')


def cmd_reject(args):
    actor = args.actor_id
    try:
        actor = UUID(actor).hex
    except ValueError:
        print(f'Error: Invalid actor ID format: {actor}')
        sys.exit(1)

    draft = get_draft(actor)
    if not draft:
        print(f'Error: No application found for actor {actor}.')
        sys.exit(1)

    print(f'Rejecting application:')
    print(f'  Business: {draft.get("name", "(empty)")}')
    print(f'  Reason:   {args.reason}')
    print()

    try:
        result = record_rejection(actor, args.reason)
    except ValueError as e:
        print(f'Error: {e}')
        sys.exit(1)

    if result.get('already'):
        print('Already rejected.')
    else:
        print(f'Application rejected: {args.reason}')


def main():
    parser = argparse.ArgumentParser(
        description='Review business applications and provision merchant access.')
    parser.add_argument('--api', type=local_api, default='http://localhost:8000',
                        help='Local Jac API URL (default: http://localhost:8000)')
    parser.add_argument('--api-token', default='',
                        help='JWT token for API authentication')

    sub = parser.add_subparsers(dest='command', required=True)

    sub.add_parser('list', help='List pending business applications')
    sub.add_parser('decisions', help='Show all recorded decisions')

    approve_parser = sub.add_parser('approve', help='Approve a business application')
    approve_parser.add_argument('actor_id', help='Actor ID (UUID) of the applicant')
    approve_parser.add_argument('--slug', default='', help='Override the generated slug')
    approve_parser.add_argument('--skip-graph', action='store_true',
                                help='Skip graph creation (only record decision + env)')

    reject_parser = sub.add_parser('reject', help='Reject a business application')
    reject_parser.add_argument('actor_id', help='Actor ID (UUID) of the applicant')
    reject_parser.add_argument('--reason', required=True, help='Reason for rejection')

    args = parser.parse_args()
    if args.command == 'list':
        cmd_list(args)
    elif args.command == 'decisions':
        cmd_decisions(args)
    elif args.command == 'approve':
        cmd_approve(args)
    elif args.command == 'reject':
        cmd_reject(args)


if __name__ == '__main__':
    try:
        main()
    except (OSError, RuntimeError, ValueError, KeyError) as error:
        raise SystemExit(str(error))
