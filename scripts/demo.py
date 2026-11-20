#!/usr/bin/env python3
# Copyright (c) 2026 Gecheng Fu. SPDX-License-Identifier: MIT
"""Run a local demonstration without a database or mutations."""
import json
from pathlib import Path
import platform
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
steps = []
with tempfile.TemporaryDirectory() as tmp:
    log = Path(tmp)/'demo.log'
    log.write_text('fixture: connection accepted\nfixture: checkpoint complete\n')
    commands = [
        ('local environment diagnosis', ['doctor']),
        ('plan only; no database created', ['database-create', '--name', 'course_demo']),
        ('plan only; no table created', ['table-create', '--name', 'events', '--column', 'id:bigint', '--column', 'payload:text', '--shard-key', 'id']),
        ('plan only; no privileges changed', ['grant-select', '--table', 'events', '--role', 'reader']),
        ('plan only; no cluster stopped', ['cluster', 'stop', '--home', '/example/admin', '--config', '/example/pgxc_ctl.conf']),
        ('read local synthetic log fixture', ['logs', '--file', str(log), '--lines', '1']),
        ('reject invalid input', ['table-create', '--name', 'events', '--column', 'id:bigint', '--shard-key', 'missing']),
    ]
    for description, args in commands:
        proc = subprocess.run([sys.executable, str(ROOT/'scripts/otb_ops.py'), *args], capture_output=True, text=True)
        expected = 2 if description == 'reject invalid input' else 0
        assert proc.returncode == expected, proc.stderr
        steps.append(dict(verification=description, args=['<temporary-log>' if x == str(log) else x for x in args], exit_code=proc.returncode, output=json.loads(proc.stdout)))
record = dict(generated_at=datetime.now(timezone.utc).isoformat(), python=platform.python_version(), live_database_tested=False, steps=steps)
(ROOT/'examples/demo-record.json').write_text(json.dumps(record, ensure_ascii=False, indent=2)+'\n')
print('Recorded %d actual local CLI invocations; no live database operations.' % len(steps))
