# Copyright (c) 2026 Gecheng Fu. SPDX-License-Identifier: MIT
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('otb_ops', ROOT / 'scripts/otb_ops.py')
ops = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ops)

class OpsTests(unittest.TestCase):
    def invoke(self, *argv):
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            code = ops.main(list(argv))
        return code, json.loads(output.getvalue())

    def test_plans_never_launch_a_process(self):
        for args in [('database-create', '--name', 'demo'),
                     ('table-create', '--name', 'events', '--column', 'id:bigint', '--shard-key', 'id'),
                     ('grant-select', '--table', 'events', '--role', 'reader'),
                     ('cluster', 'start', '--home', '/unused', '--config', '/unused/conf'),
                     ('cluster', 'stop', '--home', '/unused', '--config', '/unused/conf')]:
            with self.subTest(args=args), patch.object(ops.subprocess, 'run') as run:
                code, data = self.invoke(*args)
                self.assertEqual(code, 0)
                self.assertEqual(data['mode'], 'plan')
                self.assertFalse(data['data']['executed'])
                run.assert_not_called()

    def test_quoted_identifier_cannot_end_the_statement(self):
        name = 'x"; DROP DATABASE postgres; --'
        code, data = self.invoke('database-create', '--name', name)
        self.assertEqual(code, 0)
        self.assertEqual(data['data']['sql'], 'CREATE DATABASE "x""; DROP DATABASE postgres; --";')

    def test_invalid_columns_and_names_fail_without_backend(self):
        cases = [('database-create', '--name', ''), ('database-create', '--name', '中'*22),
                 ('table-create', '--name', 't', '--column', 'id:text);DROP TABLE x', '--shard-key', 'id'),
                 ('table-create', '--name', 't', '--column', 'id:text', '--shard-key', 'absent'),
                 ('table-create', '--name', 't', '--column', 'id:text', '--column', 'id:text', '--shard-key', 'id'),
                 ('logs', '--file', 'missing', '--lines', '0'), ('--timeout', '0', 'status'),
                 ('--timeout', 'NaN', 'status'), ('unknown',)]
        for args in cases:
            with self.subTest(args=args), patch.object(ops.subprocess, 'run') as run:
                code, data = self.invoke(*args)
                self.assertEqual(code, 2)
                self.assertFalse(data['ok'])
                run.assert_not_called()

    def test_read_commands_decode_json(self):
        for command in ['status', 'nodes', 'roles']:
            with self.subTest(command=command), patch.object(ops.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '[{"name":"中文"}]', '')) as run:
                code, data = self.invoke(command)
                self.assertEqual(code, 0)
                self.assertEqual(data['data']['rows'], [{'name':'中文'}])
                argv = run.call_args.args[0]
                self.assertIn('-X', argv)
                self.assertIn('-w', argv)
                self.assertIn('ON_ERROR_STOP=1', argv)
                self.assertNotIn('shell', run.call_args.kwargs)
                self.assertEqual(run.call_args.kwargs['timeout'], 30)

    def test_bad_backend_json(self):
        for output in ['not json', '{}', '[1]']:
            with self.subTest(output=output), patch.object(ops.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
                code, data = self.invoke('nodes')
                self.assertEqual(code, 1)
                self.assertEqual(data['error']['code'], 'OPERATION_FAILED')

    def test_failure_and_timeout_do_not_leak_stderr(self):
        with patch.object(ops.subprocess, 'run', return_value=subprocess.CompletedProcess([], 3, '', 'password=private')):
            code, data = self.invoke('status')
            self.assertEqual(code, 1)
            self.assertNotIn('private', json.dumps(data))
        for error in [FileNotFoundError(), subprocess.TimeoutExpired('psql', 30)]:
            with self.subTest(error=error), patch.object(ops.subprocess, 'run', side_effect=error):
                self.assertEqual(self.invoke('status')[0], 1)

    def test_apply_invokes_exactly_once(self):
        with patch.object(ops.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, '', '')) as run:
            code, data = self.invoke('database-create', '--name', 'course', '--apply')
            self.assertEqual(code, 0)
            self.assertEqual(data['mode'], 'apply')
            run.assert_called_once()
            self.assertEqual(run.call_args.args[0][-1], 'CREATE DATABASE "course";')

    def test_log_tail_and_bound(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'server.log'
            path.write_text('one\ntwo\n三\n')
            code, data = self.invoke('logs', '--file', str(path), '--lines', '2')
            self.assertEqual(code, 0)
            self.assertEqual(data['data']['lines'], ['two', '三'])
            path.write_bytes(b'a'*(2*1024*1024)+b'\nlast\n')
            code, data = self.invoke('logs', '--file', str(path))
            self.assertTrue(data['data']['window_truncated'])
            self.assertEqual(data['data']['lines'], ['last'])
        self.assertEqual(self.invoke('logs', '--file', str(path))[0], 2)

    def test_cluster_monitor_does_not_claim_health(self):
        with tempfile.TemporaryDirectory(prefix='cluster space ') as tmp:
            path = Path(tmp)/'pgxc_ctl.conf'
            path.write_text('# test fixture')
            for action in ['monitor', 'start', 'stop']:
                with self.subTest(action=action), patch.object(ops.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'Not running', '')) as run:
                    code, data = self.invoke('cluster', action, '--home', tmp, '--config', str(path), '--apply')
                    self.assertEqual(code, 0)
                    self.assertFalse(data['data']['health_verified'])
                    self.assertEqual(run.call_args.args[0][-2:], [action, 'all'])
                    self.assertIn(str(path.resolve()), run.call_args.args[0])

    def test_actual_cli_process_contract(self):
        proc = subprocess.run([sys.executable, str(ROOT/'scripts/otb_ops.py'), 'database-create', '--name', 'example'], capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(json.loads(proc.stdout)['mode'], 'plan')
        self.assertEqual(proc.stderr, '')

    def test_actual_backend_process_with_fixture(self):
        # This is an executable fixture, not a live database.
        with tempfile.TemporaryDirectory() as tmp:
            fake = Path(tmp)/'fixture_psql'
            fake.write_text('#!'+sys.executable+'\nimport sys\nassert "-X" in sys.argv\nassert "ON_ERROR_STOP=1" in sys.argv\nprint(\'[ {"fixture": true} ]\')\n')
            fake.chmod(0o700)
            proc = subprocess.run([sys.executable, str(ROOT/'scripts/otb_ops.py'), '--psql', str(fake), 'nodes'], capture_output=True, text=True)
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertTrue(json.loads(proc.stdout)['data']['rows'][0]['fixture'])

if __name__ == '__main__':
    unittest.main()
