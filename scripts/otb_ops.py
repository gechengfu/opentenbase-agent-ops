#!/usr/bin/env python3
# Copyright (c) 2026 Gecheng Fu. SPDX-License-Identifier: MIT
"""Bounded, structured OpenTenBase operations for agents (Python 3.9+)."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

VERSION = '1.0.0'
TYPES = {'bigint', 'integer', 'text', 'boolean', 'date', 'timestamptz', 'numeric'}
QUERIES = {
    'status': 'SELECT current_database() AS database, current_user AS username, version() AS version, pg_is_in_recovery() AS in_recovery',
    'nodes': 'SELECT node_name, node_type, node_host, node_port FROM pg_catalog.pgxc_node ORDER BY node_name',
    'roles': 'SELECT rolname, rolcanlogin, rolsuper, rolcreatedb FROM pg_catalog.pg_roles ORDER BY rolname',
}

class UsageError(ValueError):
    pass

class BackendError(Exception):
    pass

class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise UsageError(message)


def identifier(value):
    if not value or '\x00' in value or len(value.encode('utf-8')) > 63:
        raise UsageError('Identifiers must contain 1–63 UTF-8 bytes and no NUL')
    return '"' + value.replace('"', '""') + '"'


def bounded_int(low, high):
    def parse(value):
        try:
            result = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError('must be an integer')
        if not low <= result <= high:
            raise argparse.ArgumentTypeError('must be between %d and %d' % (low, high))
        return result
    return parse


def parser():
    p = Parser(description=__doc__)
    p.add_argument('--version', action='version', version=VERSION)
    p.add_argument('--psql', default='psql', help='OpenTenBase psql executable path')
    p.add_argument('--pgxc-ctl', default='pgxc_ctl')
    p.add_argument('--timeout', type=bounded_int(1, 300), default=30)
    sub = p.add_subparsers(dest='command', required=True, parser_class=Parser)
    for name in ['doctor', 'status', 'nodes', 'roles']:
        sub.add_parser(name)
    db = sub.add_parser('database-create')
    db.add_argument('--name', required=True)
    table = sub.add_parser('table-create')
    table.add_argument('--schema', default='public')
    table.add_argument('--name', required=True)
    table.add_argument('--column', action='append', required=True, help='name:type (repeatable)')
    table.add_argument('--shard-key', required=True, help='one declared column')
    grant = sub.add_parser('grant-select')
    grant.add_argument('--schema', default='public')
    grant.add_argument('--table', required=True)
    grant.add_argument('--role', required=True)
    for command in [db, table, grant]:
        command.add_argument('--apply', action='store_true', help='execute the mutation; default is plan only')
    cluster = sub.add_parser('cluster')
    cluster.add_argument('action', choices=['monitor', 'start', 'stop'])
    cluster.add_argument('--home', required=True)
    cluster.add_argument('--config', required=True)
    cluster.add_argument('--apply', action='store_true')
    logs = sub.add_parser('logs')
    logs.add_argument('--file', required=True)
    logs.add_argument('--lines', type=bounded_int(1, 1000), default=50)
    return p


def sql_plan(args):
    if args.command == 'database-create':
        return 'CREATE DATABASE %s;' % identifier(args.name)
    if args.command == 'grant-select':
        return 'GRANT SELECT ON TABLE %s.%s TO %s;' % (
            identifier(args.schema), identifier(args.table), identifier(args.role))
    if args.command == 'table-create':
        columns, names = [], set()
        for column in args.column:
            if ':' not in column:
                raise UsageError('Column syntax is name:type')
            name, typename = column.rsplit(':', 1)
            if typename not in TYPES:
                raise UsageError('Supported column types: ' + ', '.join(sorted(TYPES)))
            if name in names:
                raise UsageError('Duplicate column name')
            names.add(name)
            columns.append(identifier(name) + ' ' + typename)
        if args.shard_key not in names:
            raise UsageError('Shard key must name a declared column')
        return 'CREATE TABLE %s.%s (%s) DISTRIBUTE BY SHARD (%s);' % (
            identifier(args.schema), identifier(args.name), ', '.join(columns), identifier(args.shard_key))
    raise UsageError('Unknown SQL operation')


def run(argv, timeout, sql=False):
    env = os.environ.copy()
    if sql:
        env['PGCONNECT_TIMEOUT'] = str(min(timeout, 10))
        # Bound server-side execution as well as waiting in the local process.
        env['PGOPTIONS'] = env.get('PGOPTIONS', '') + ' -c statement_timeout=%d' % (timeout * 1000)
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=timeout, env=env)
    except FileNotFoundError:
        raise BackendError('Required executable was not found; run doctor or supply its path')
    except subprocess.TimeoutExpired:
        raise BackendError('Operation timed out; a timed-out mutation may have completed. Inspect state before retrying')
    if proc.returncode:
        # Backend stderr can contain credentials, SQL data or deployment paths.
        raise BackendError('Backend exited with status %d; check connectivity, privileges and server logs' % proc.returncode)
    return proc.stdout


def psql(args, sql):
    return run([args.psql, '-X', '-w', '-q', '-A', '-t', '-v', 'ON_ERROR_STOP=1',
                '-P', 'pager=off', '-c', sql], args.timeout, sql=True)


def execute(args):
    if args.command == 'doctor':
        found = {name: shutil.which(path) for name, path in [('psql', args.psql), ('pgxc_ctl', args.pgxc_ctl)]}
        return 'read', {'executables': found, 'sql_ready': bool(found['psql']),
                        'cluster_control_ready': bool(found['pgxc_ctl']),
                        'connection_variables_set': [key for key in ['PGHOST', 'PGPORT', 'PGDATABASE', 'PGUSER', 'PGSERVICE', 'PGPASSFILE'] if os.environ.get(key)]}
    if args.command in QUERIES:
        query = "SELECT COALESCE(json_agg(row_to_json(t)), '[]'::json) FROM (%s) t;" % QUERIES[args.command]
        try:
            rows = json.loads(psql(args, query))
        except json.JSONDecodeError:
            raise BackendError('Backend did not return valid JSON')
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise BackendError('Backend JSON did not contain an array of objects')
        return 'read', {'rows': rows}
    if args.command == 'logs':
        path = Path(args.file).expanduser()
        if not path.is_file():
            raise UsageError('Log path must be an existing regular file')
        # Read at most 1 MiB even for a multi-gigabyte log or an enormous line.
        with path.open('rb') as stream:
            size = stream.seek(0, 2)
            start = max(0, size - 1024 * 1024)
            stream.seek(start)
            content = stream.read(1024 * 1024)
        if start:
            content = content.partition(b'\n')[2]
        return 'read', {'lines': content.decode('utf-8', errors='replace').splitlines()[-args.lines:],
                        'window_truncated': bool(start), 'max_bytes': 1024 * 1024}
    if args.command == 'cluster':
        home = str(Path(args.home).expanduser().resolve())
        config = str(Path(args.config).expanduser().resolve())
        argv = [args.pgxc_ctl, '--home', home, '-c', config, args.action, 'all']
        if args.action != 'monitor' and not args.apply:
            return 'plan', {'argv': argv, 'scope': 'all configured nodes', 'executed': False}
        if not Path(config).is_file() or not Path(home).is_dir():
            raise UsageError('Cluster execution requires an existing home directory and trusted configuration file')
        output = run(argv, args.timeout)
        return 'read' if args.action == 'monitor' else 'apply', {
            'output': output, 'health_verified': False,
            'note': 'Command exit status alone does not prove cluster health; inspect monitor output and nodes/status'}
    sql = sql_plan(args)
    if not args.apply:
        return 'plan', {'sql': sql, 'executed': False}
    psql(args, sql)
    return 'apply', {'executed': True}


def main(argv=None):
    command = None
    try:
        args = parser().parse_args(argv)
        command = args.command
        mode, data = execute(args)
        result, code = dict(ok=True, command=command, mode=mode, data=data, error=None), 0
    except (UsageError, ValueError) as exc:
        result, code = dict(ok=False, command=command, mode=None, data=None,
                            error=dict(code='INVALID_ARGUMENT', message=str(exc))), 2
    except (BackendError, OSError) as exc:
        message = str(exc) if isinstance(exc, BackendError) else 'Local file or process operation failed'
        result, code = dict(ok=False, command=command, mode=None, data=None,
                            error=dict(code='OPERATION_FAILED', message=message)), 1
    print(json.dumps(result, ensure_ascii=False))
    return code

if __name__ == '__main__':
    sys.exit(main())
