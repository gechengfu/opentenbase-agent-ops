---
name: opentenbase-agent-ops
description: Query OpenTenBase connection and node status, inspect roles and local logs, and plan or execute database/table creation, SELECT grants and pgxc_ctl cluster operations through a structured JSON CLI. Use for OpenTenBase operational requests; not arbitrary SQL, migration planning or PostgreSQL-only deployments.
---

# OpenTenBase Agent Operations

Run `python3 <skill-dir>/scripts/otb_ops.py --help` to inspect the CLI. Python 3.9+ is sufficient for planning and local logs. Live operations require OpenTenBase's `psql`; cluster control also requires `pgxc_ctl` on the administration host.

1. Resolve the intended cluster and database from the user's request and existing environment. Connection settings use libpq's `PGHOST`, `PGPORT`, `PGDATABASE`, `PGUSER`, `PGSERVICE` and `PGPASSFILE`; do not put passwords in command arguments or output.
2. Run `doctor`, then use the matching narrow command. `status` checks one SQL endpoint; `nodes` reads its registered topology, which is not a network reachability check. `cluster monitor` returns native output without claiming that a zero exit status proves cluster health.
3. For mutations, first run without `--apply` and inspect the SQL or command plan against the requested scope. Execute with `--apply` only when the user has authorized that operation and target. Existing explicit authorization suffices; ask only if the scope is unclear. Cluster start/stop affects all nodes in the provided configuration.
4. Parse the JSON response and the process exit code together: 0 means the requested wrapper operation succeeded, 1 an operational failure, 2 invalid input. A `mode: plan` response has not changed the database. Never report a plan as an executed change.
5. Do not automatically retry a timed-out mutation: the server may already have applied it. Inspect the resulting database state first.

Useful mappings:

- Connection/version: `status`
- Registered nodes: `nodes`
- Existing roles: `roles`
- Last log lines: `logs --file <explicit-path> --lines 50`
- Database: `database-create --name <database>`
- Sharded table: `table-create --schema public --name events --column id:bigint --column payload:text --shard-key id`
- Table read access: `grant-select --schema public --table events --role <existing-role>`
- Lifecycle: `cluster monitor|start|stop --home <admin-home> --config <trusted-pgxc_ctl.conf>`

Global options (`--timeout`, `--psql`, `--pgxc-ctl`) precede the subcommand. Only use trusted native executable paths and configuration files; `pgxc_ctl` configuration can execute shell code. Log/monitor output can contain operational data: summarize only what the user needs, and do not publish raw output without authorization.

For installation and runnable examples read [README.md](README.md). For output schema, source mapping, error diagnosis and live acceptance steps read [references/operations.md](references/operations.md). The recorded local demonstration is [examples/demo-record.json](examples/demo-record.json); it explicitly marks execution versus planning and is not evidence of a live cluster deployment.
