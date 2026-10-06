#!/usr/bin/env python3
"""Offline tests for the fixed GitHub source-proof origin binding."""

from pathlib import Path
import ast
import copy
import contextlib
import hashlib
import importlib.util
import io
import json
import unittest
from unittest.mock import patch


ROOT = Path(__file__).resolve().parent
RUNNER = ROOT / 'run-fresh-source.py'
VERIFY_SPEC = importlib.util.spec_from_file_location('verify_source_origin', ROOT / 'verify-source-origin.py')
VERIFY = importlib.util.module_from_spec(VERIFY_SPEC)
VERIFY_SPEC.loader.exec_module(VERIFY)


REPOSITORY_ID = 1389740586
API_ROOT = 'repos/CosmonautJones/m-local/actions/'
GH_SECONDS = 30
COMMIT = 'a' * 40
RUN_ID = '123456'
RUN_NUMBER = 42
ATTEMPT = 1
CONTRACT = 'c' * 64
ARTIFACT_DIGEST = 'sha256:' + ('d' * 64)
REPOSITORY = {'id': REPOSITORY_ID, 'full_name': 'CosmonautJones/m-local'}
START = '2026-10-06T00:00:00.0000000Z'
JOB_END = '2026-10-06T00:22:00.0000000Z'
NATIVE_START = '2026-10-06T00:07:00.0000000Z'
NATIVE_END = '2026-10-06T00:20:00.0000000Z'
UPLOAD_START = '2026-10-06T00:21:00.0000000Z'
UPLOAD_END = '2026-10-06T00:22:00.0000000Z'

STEP_NAMES = (
    'Checkout public proof inputs',
    'Check source runner output and mount binding',
    'Check sanitized source handoff verifier',
    'Check source producer and export boundaries',
    'Check sanitized source failure context',
    'Check fresh matrix loader provenance binding',
    'Run fresh source/bootstrap/matrix proof',
    'Verify exported source handoff',
    'Retain verified public source handoff',
)
CHECKS = [
    'host-controls', 'fresh-64Gi-storage', 'public-app-revision', 'public-pinned-downloads',
    'postgres-distribution', 'dependency-priming-pillow', 'fresh-forks-80fd-d363',
    'cold-compile-before-after', 'bootstrap-53', 'matrix-10-plus-2', 'scrubbed-36-file-contract',
]


def step(number, name, started, completed):
    return {'number': number, 'name': name, 'status': 'completed', 'conclusion': 'success',
            'started_at': started, 'completed_at': completed}


def runner_constant(name):
    tree = ast.parse(RUNNER.read_text(encoding='utf-8'))
    for node in tree.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name) and node.targets[0].id == name and \
                isinstance(node.value, ast.Constant) and isinstance(node.value.value, str):
            return node.value.value
    raise AssertionError('runner constant missing: ' + name)


def source_summary():
    total_bytes = 321
    verification = {
        'status': 'passed', 'scope': 'sanitized commitment bundle verification',
        'member_count': 36, 'total_bytes': total_bytes, 'contract_sha256': CONTRACT,
        'commit_sha': COMMIT, 'run_id': RUN_ID,
    }
    return {
        'status': 'passed', 'checks': CHECKS, 'github_sha': COMMIT,
        'application_revision': runner_constant('APP_REVISION'),
        'application_digest': runner_constant('APP_SHA'),
        'jac_base': runner_constant('JAC_BASE'),
        'jac_sha256': runner_constant('JAC_SHA'),
        'jacpython_sha256': runner_constant('JACPYTHON_SHA'),
        'shim_sha256': runner_constant('SHIM_SHA'),
        'typeshed_inventory_sha256': runner_constant('TYPESHED_SHA'),
        'helper_sha256': hashlib.sha256((ROOT / 'kali-build-resources-v2.py').read_bytes()).hexdigest(),
        'handoff': {'status': 'prepared_not_uploaded', 'member_count': 36, 'total_bytes': total_bytes,
                    'contract_sha256': CONTRACT, 'verification': verification},
        'external_jac_db_url': False,
        'source_override': 'leaf receipts only',
        'status_scope': 'prepared source proof; no package/adoption/deployment',
    }


def source_log(summary=None, timestamp='2026-10-06T00:12:00.0000000Z'):
    payload = json.dumps(summary or source_summary(), sort_keys=True, separators=(',', ':'))
    return '\n'.join([
        timestamp + ' ##[group]Run fresh source/bootstrap/matrix proof',
        timestamp + ' source runner emitted sanitized summary',
        timestamp + ' ' + payload,
        NATIVE_END + ' ##[endgroup]',
    ]) + '\n'


def fixture():
    steps = [
        step(1, STEP_NAMES[0], START, '2026-10-06T00:01:00.0000000Z'),
        step(2, STEP_NAMES[1], '2026-10-06T00:01:00.0000000Z', '2026-10-06T00:02:00.0000000Z'),
        step(3, STEP_NAMES[2], '2026-10-06T00:02:00.0000000Z', '2026-10-06T00:03:00.0000000Z'),
        step(4, STEP_NAMES[3], '2026-10-06T00:03:00.0000000Z', '2026-10-06T00:04:00.0000000Z'),
        step(5, STEP_NAMES[4], '2026-10-06T00:04:00.0000000Z', '2026-10-06T00:05:00.0000000Z'),
        step(6, STEP_NAMES[5], '2026-10-06T00:05:00.0000000Z', '2026-10-06T00:06:00.0000000Z'),
        step(7, STEP_NAMES[6], NATIVE_START, NATIVE_END),
        step(8, STEP_NAMES[7], '2026-10-06T00:20:00.0000000Z', '2026-10-06T00:21:00.0000000Z'),
        step(9, STEP_NAMES[8], UPLOAD_START, UPLOAD_END),
    ]
    run = {
        'id': int(RUN_ID), 'run_number': RUN_NUMBER, 'run_attempt': ATTEMPT,
        'workflow_id': 376097532, 'path': '.github/workflows/runtime-source-proof.yml',
        'head_sha': COMMIT, 'head_branch': 'codex/runtime-verification',
        'head_repository': copy.deepcopy(REPOSITORY), 'status': 'completed', 'conclusion': 'success', 'event': 'push',
        'created_at': START, 'updated_at': JOB_END, 'repository': copy.deepcopy(REPOSITORY),
    }
    job = {
        'id': 987654, 'run_id': int(RUN_ID), 'run_attempt': ATTEMPT,
        'name': 'source-proof', 'head_sha': COMMIT, 'status': 'completed',
        'conclusion': 'success', 'started_at': START, 'completed_at': JOB_END,
        'runner_group_name': 'GitHub Actions', 'labels': ['ubuntu-24.04'], 'steps': steps,
    }
    artifact = {
        'id': 246810, 'name': 'm-local-source-handoff-' + COMMIT + '-' + RUN_ID,
        'size_in_bytes': 3210, 'archive_download_url': 'https://api.github.com/unused',
        'digest': ARTIFACT_DIGEST, 'expired': False,
        'created_at': UPLOAD_START, 'updated_at': UPLOAD_END,
        'expires_at': '2026-10-13T00:21:00.0000000Z',
        'workflow_run': {'id': int(RUN_ID), 'repository_id': REPOSITORY_ID,
                         'head_repository_id': REPOSITORY_ID, 'head_branch': 'codex/runtime-verification',
                         'head_sha': COMMIT},
    }
    return run, {'total_count': 1, 'jobs': [job]}, {'total_count': 1, 'artifacts': [artifact]}, source_log()


class SourceOriginTests(unittest.TestCase):
    def verify(self, run, jobs, artifacts, log):
        return VERIFY.verify_origin(run, jobs, artifacts, log,
                                    expected_commit=COMMIT, expected_run_id=RUN_ID)

    def test_valid_origin_returns_only_finite_bound_summary(self):
        result = self.verify(*fixture())
        self.assertEqual(result['status'], 'passed')
        self.assertEqual(str(result['run_id']), RUN_ID)
        self.assertEqual(str(result['job_id']), '987654')
        self.assertEqual(str(result['artifact_id']), '246810')
        self.assertEqual(result['artifact_digest'], ARTIFACT_DIGEST)
        self.assertEqual(result['artifact_size'], 3210)
        self.assertEqual(result['contract_sha256'], CONTRACT)
        self.assertIsInstance(result['scope'], str)
        self.assertIn('source', result['scope'].lower())
        self.assertEqual(set(result), {
            'status', 'scope', 'run_id', 'job_id', 'artifact_id', 'artifact_name',
            'artifact_digest', 'artifact_size', 'contract_sha256',
        })

    def test_run_and_job_identity_or_required_step_fail_closed(self):
        run, jobs, artifacts, log = fixture()
        cases = []
        bad = copy.deepcopy(run)
        bad['head_sha'] = 'b' * 40
        cases.append(('run commit', bad, jobs, artifacts, log))
        bad = copy.deepcopy(run)
        bad['repository'] = {'id': 999, 'full_name': 'CosmonautJones/m-local'}
        cases.append(('repository', bad, jobs, artifacts, log))
        bad = copy.deepcopy(run)
        bad['workflow_id'] = 999
        cases.append(('workflow', bad, jobs, artifacts, log))
        bad = copy.deepcopy(run)
        bad['path'] = '.github/workflows/other.yml'
        cases.append(('workflow path', bad, jobs, artifacts, log))
        bad = copy.deepcopy(run)
        bad['head_branch'] = 'main'
        cases.append(('branch', bad, jobs, artifacts, log))
        bad_jobs = copy.deepcopy(jobs)
        bad_jobs['jobs'][0]['conclusion'] = 'failure'
        cases.append(('job conclusion', run, bad_jobs, artifacts, log))
        bad_jobs = copy.deepcopy(jobs)
        bad_jobs['jobs'][0]['steps'][4]['conclusion'] = 'failure'
        cases.append(('required step', run, bad_jobs, artifacts, log))
        for label, bad_run, bad_jobs, bad_artifacts, bad_log in cases:
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                self.verify(bad_run, bad_jobs, bad_artifacts, bad_log)

    def test_artifact_name_digest_expiry_and_upload_window_are_bound(self):
        run, jobs, artifacts, log = fixture()
        cases = []
        for key, value in (
                ('name', artifacts['artifacts'][0]['name'].replace(COMMIT, 'b' * 40)),
                ('digest', 'md5:' + ('e' * 32)),
                ('expired', True),
                ('created_at', '2026-10-06T00:00:00.0000000Z'),
                ('size_in_bytes', 0)):
            bad = copy.deepcopy(artifacts)
            bad['artifacts'][0][key] = value
            cases.append((key, bad))
        for label, bad_artifacts in cases:
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                self.verify(run, jobs, bad_artifacts, log)
        bad = copy.deepcopy(artifacts)
        bad['artifacts'][0]['workflow_run']['head_sha'] = 'b' * 40
        with self.assertRaises(RuntimeError):
            self.verify(run, jobs, bad, log)

    def test_log_requires_one_bound_successful_source_summary(self):
        run, jobs, artifacts, log = fixture()
        cases = [
            ('outside native window', source_log(timestamp='2026-10-06T00:23:00.0000000Z')),
            ('duplicate', log + log),
            ('bad contract', source_log(dict(source_summary(), handoff=dict(
                source_summary()['handoff'], contract_sha256='e' * 64)))),
            ('wrong count', source_log(dict(source_summary(), handoff=dict(
                source_summary()['handoff'], verification=dict(
                    source_summary()['handoff']['verification'], member_count=35))))),
            ('smtp control', source_log(dict(source_summary(), external_jac_db_url=True))),
        ]
        for label, bad_log in cases:
            with self.subTest(label=label), self.assertRaises(RuntimeError):
                self.verify(run, jobs, artifacts, bad_log)

    def test_attempt_and_timestamp_cross_binding_reject_prior_retry(self):
        run, jobs, artifacts, log = fixture()
        bad_run = copy.deepcopy(run)
        bad_run['run_attempt'] = 2
        with self.assertRaises(RuntimeError):
            self.verify(bad_run, jobs, artifacts, log)
        bad_jobs = copy.deepcopy(jobs)
        bad_jobs['jobs'][0]['run_attempt'] = 2
        with self.assertRaises(RuntimeError):
            self.verify(run, bad_jobs, artifacts, log)
        bad_jobs = copy.deepcopy(jobs)
        bad_jobs['jobs'][0]['head_sha'] = 'b' * 40
        with self.assertRaises(RuntimeError):
            self.verify(run, bad_jobs, artifacts, log)
        bad_artifacts = copy.deepcopy(artifacts)
        bad_artifacts['artifacts'][0]['created_at'] = '2026-10-06T00:00:00.0000000Z'
        with self.assertRaises(RuntimeError):
            self.verify(run, jobs, bad_artifacts, log)
        bad_jobs = copy.deepcopy(jobs)
        bad_jobs['jobs'][0]['steps'][0]['started_at'] = '2026-10-06T00:00:00+00:00'
        with self.assertRaises(RuntimeError):
            self.verify(run, bad_jobs, artifacts, log)

    def test_unrelated_log_noise_is_ignored_and_never_returned(self):
        run, jobs, artifacts, log = fixture()
        noisy = '2026-10-06T00:11:00.0000000Z RAW_PRIVATE_LOG_SENTINEL\n' + log
        result = self.verify(run, jobs, artifacts, noisy)
        self.assertNotIn('RAW_PRIVATE_LOG_SENTINEL', json.dumps(result, sort_keys=True))

    def test_cli_reads_fixed_endpoints_in_order_and_returns_sanitized_json(self):
        run, jobs, artifacts, log = fixture()
        run_endpoint = API_ROOT + 'runs/' + RUN_ID
        responses = {
            run_endpoint: [json.dumps(run), json.dumps(run)],
            run_endpoint + '/attempts/' + str(ATTEMPT) + '/jobs?per_page=100': json.dumps(jobs),
            run_endpoint + '/artifacts?per_page=100': json.dumps(artifacts),
            API_ROOT + 'jobs/987654/logs': log,
        }
        calls = []

        def fake_gh_read(endpoint, limit):
            calls.append(endpoint)
            value = responses[endpoint]
            return value.pop(0) if isinstance(value, list) else value

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(VERIFY, 'gh_read', side_effect=fake_gh_read), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = VERIFY.main(['--expected-commit', COMMIT, '--expected-run-id', RUN_ID])
        self.assertEqual(code, 0)
        output = json.loads(stdout.getvalue())
        self.assertEqual(output['contract_sha256'], CONTRACT)
        self.assertEqual(stderr.getvalue(), '')
        self.assertEqual(calls, [run_endpoint,
                                 run_endpoint + '/attempts/1/jobs?per_page=100',
                                 run_endpoint + '/artifacts?per_page=100',
                                 API_ROOT + 'jobs/987654/logs', run_endpoint])

    def test_cli_rejects_failed_run_before_fetching_jobs_and_sanitizes_errors(self):
        run, jobs, artifacts, log = fixture()
        run_endpoint = API_ROOT + 'runs/' + RUN_ID
        bad_run = copy.deepcopy(run)
        bad_run['conclusion'] = 'failure'
        calls = []

        def failed_run(endpoint, limit):
            calls.append(endpoint)
            return json.dumps(bad_run)

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(VERIFY, 'gh_read', side_effect=failed_run), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = VERIFY.main(['--expected-commit', COMMIT, '--expected-run-id', RUN_ID])
        self.assertEqual(code, 1)
        self.assertEqual(calls, [run_endpoint])
        self.assertEqual(stdout.getvalue(), '')
        self.assertEqual(stderr.getvalue(), 'source origin verification failed\n')

        def private_error(endpoint, limit):
            raise RuntimeError('RAW_PRIVATE_GITHUB_BODY_SENTINEL')

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(VERIFY, 'gh_read', side_effect=private_error), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = VERIFY.main(['--expected-commit', COMMIT, '--expected-run-id', RUN_ID])
        self.assertEqual(code, 1)
        self.assertNotIn('RAW_PRIVATE_GITHUB_BODY_SENTINEL', stdout.getvalue() + stderr.getvalue())

        def duplicate_run(endpoint, limit):
            return '{"id":1,"id":2}'

        stdout, stderr = io.StringIO(), io.StringIO()
        with patch.object(VERIFY, 'gh_read', side_effect=duplicate_run), \
                contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
            code = VERIFY.main(['--expected-commit', COMMIT, '--expected-run-id', RUN_ID])
        self.assertEqual(code, 1)
        self.assertNotIn('id', stdout.getvalue())
        self.assertEqual(stderr.getvalue(), 'source origin verification failed\n')

    def test_gh_read_has_fixed_bounded_process_boundary_and_cleanup(self):
        class Stdout:
            def __init__(self, payload):
                self.payload = payload
                self.sizes = []

            def read(self, size):
                self.sizes.append(size)
                return self.payload

        class Process:
            def __init__(self, payload, returncode=0):
                self.stdout = Stdout(payload)
                self.returncode = returncode
                self.waits = 0
                self.kills = 0
                self._poll = None

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def wait(self):
                self.waits += 1
                if self._poll is None:
                    self._poll = self.returncode
                return self.returncode

            def poll(self):
                return self._poll

            def kill(self):
                self.kills += 1

        class Timer:
            instances = []

            def __init__(self, seconds, callback):
                self.seconds = seconds
                self.callback = callback
                self.daemon = False
                self.started = False
                self.cancelled = False
                self.instances.append(self)

            def start(self):
                self.started = True

            def cancel(self):
                self.cancelled = True

        process = Process(b'bounded response')
        with patch.object(VERIFY.subprocess, 'Popen', return_value=process) as popen, \
                patch.object(VERIFY.threading, 'Timer', Timer), \
                patch.dict(VERIFY.os.environ, {'GH_DEBUG': '1', 'ORIGIN_TEST_ENV': 'kept'}):
            result = VERIFY.gh_read('repos/CosmonautJones/m-local/actions/runs/123', 20)
        self.assertEqual(result, 'bounded response')
        args, kwargs = popen.call_args
        command = args[0]
        self.assertEqual(command, [
            'gh', 'api', '--hostname', 'github.com', '--method', 'GET',
            '-H', 'Accept: application/vnd.github+json',
            '-H', 'X-GitHub-Api-Version: 2026-03-10',
            'repos/CosmonautJones/m-local/actions/runs/123'])
        self.assertIs(kwargs['stdout'], VERIFY.subprocess.PIPE)
        self.assertIs(kwargs['stderr'], VERIFY.subprocess.DEVNULL)
        self.assertNotIn('GH_DEBUG', kwargs['env'])
        self.assertEqual(kwargs['env']['ORIGIN_TEST_ENV'], 'kept')
        self.assertEqual(process.stdout.sizes, [21])
        self.assertEqual(process.waits, 1)
        self.assertEqual(process.kills, 0)
        self.assertEqual(len(Timer.instances), 1)
        self.assertEqual(Timer.instances[0].seconds, GH_SECONDS)
        self.assertTrue(Timer.instances[0].daemon)
        self.assertTrue(Timer.instances[0].started)
        self.assertTrue(Timer.instances[0].cancelled)

        for payload, limit, label in ((b'123456', 5, 'GitHub response size'),
                                      (b'\xff', 5, 'GitHub response encoding')):
            process = Process(payload)
            Timer.instances.clear()
            with patch.object(VERIFY.subprocess, 'Popen', return_value=process), \
                    patch.object(VERIFY.threading, 'Timer', Timer):
                with self.assertRaisesRegex(RuntimeError, '^' + label + '$'):
                    VERIFY.gh_read('origin', limit)
            self.assertEqual(process.stdout.sizes, [limit + 1])
            self.assertGreaterEqual(process.waits, 1)
            self.assertGreaterEqual(process.kills, 1 if label == 'GitHub response size' else 0)
            self.assertTrue(Timer.instances[0].cancelled)

        process = Process(b'failure', returncode=7)
        Timer.instances.clear()
        with patch.object(VERIFY.subprocess, 'Popen', return_value=process), \
                patch.object(VERIFY.threading, 'Timer', Timer):
            with self.assertRaisesRegex(RuntimeError, '^GitHub request failed$'):
                VERIFY.gh_read('origin', 20)
        self.assertEqual(process.waits, 1)
        self.assertTrue(Timer.instances[0].cancelled)

    def test_cli_rejects_final_run_attempt_or_status_change(self):
        run, jobs, artifacts, log = fixture()
        run_endpoint = API_ROOT + 'runs/' + RUN_ID
        endpoints = [run_endpoint,
                     run_endpoint + '/attempts/1/jobs?per_page=100',
                     run_endpoint + '/artifacts?per_page=100',
                     API_ROOT + 'jobs/987654/logs', run_endpoint]
        for label, final_run in (
                ('attempt', dict(run, run_attempt=2)),
                ('status', dict(run, status='in_progress', conclusion=None))):
            responses = {
                run_endpoint: [json.dumps(run), json.dumps(final_run)],
                endpoints[1]: json.dumps(jobs), endpoints[2]: json.dumps(artifacts), endpoints[3]: log,
            }
            calls = []

            def fake_gh_read(endpoint, limit):
                calls.append(endpoint)
                value = responses[endpoint]
                return value.pop(0) if isinstance(value, list) else value

            stdout, stderr = io.StringIO(), io.StringIO()
            with self.subTest(label=label), patch.object(VERIFY, 'gh_read', side_effect=fake_gh_read), \
                    contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                code = VERIFY.main(['--expected-commit', COMMIT, '--expected-run-id', RUN_ID])
            self.assertEqual(code, 1)
            self.assertEqual(calls, endpoints)
            self.assertEqual(stdout.getvalue(), '')
            self.assertEqual(stderr.getvalue(), 'source origin verification failed\n')


if __name__ == '__main__':
    unittest.main()
