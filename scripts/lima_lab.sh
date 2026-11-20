#!/usr/bin/env bash
# Existing course lab adapter, not a fresh-install provisioner.
set -euo pipefail
TASK_LIMA="${LIMACTL:-limactl}"
TASK_VM="${OTB_VM:-otb-lab}"
TASK_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
TASK_CONFIG=/data/opentenbase/opentenbase_ctl/opentenbase_config.ini
vm() { "$TASK_LIMA" shell --workdir /tmp "$TASK_VM" -- "$@"; }
cli() { vm sudo docker exec -u opentenbase otb-node1 env \
    PATH=/data/opentenbase/install/opentenbase/5.21.8/bin:/usr/local/bin:/usr/bin:/bin \
    LD_LIBRARY_PATH=/data/opentenbase/install/opentenbase/5.21.8/lib \
    PGHOST=10.206.0.101 PGPORT=11003 PGUSER=opentenbase PGDATABASE=skill_lab_20261120 \
    python3 /tmp/otb_ops.py "$@"; }
upload() { vm sudo docker exec -i -u opentenbase otb-node1 bash -c 'cat > /tmp/otb_ops.py' < "$TASK_ROOT/scripts/otb_ops.py"; }
case "${1:-status}" in
    --start)
        "$TASK_LIMA" start "$TASK_VM"
        vm sudo docker start otb-node1 otb-node2
        upload
        cli --timeout 120 cluster start --controller opentenbase_ctl --config "$TASK_CONFIG" --apply
        cli status
        ;;
    --stop)
        upload
        cli --timeout 120 cluster stop --controller opentenbase_ctl --config "$TASK_CONFIG" --apply
        vm sudo docker stop otb-node1 otb-node2
        "$TASK_LIMA" stop "$TASK_VM"
        ;;
    *) upload; cli "${@:-status}" ;;
esac
