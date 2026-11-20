# 免费本地真实集群验收（2026-11-20）

本次复用了本机已有的课程实验安装，而非租用云服务或重新部署数据库。宿主机为 ARM64 Mac、16 GiB 内存；Lima `otb-lab` 虚拟机分配 4 vCPU、8 GiB 内存、12 GiB 磁盘。虚拟机内的两个 Docker 容器 `otb-node1/otb-node2` 运行 Ubuntu 20.04 用户空间和此前编译安装的 OpenTenBase。

原生管理器报告 v5.21.8；数据库 `version()` 报告 PostgreSQL 10.0 @ OpenTenBase_v5.0 / OpenTenBase V5.21，aarch64，GCC 9.4.0。具体返回值保留在 [live-demo.json](../examples/live-demo.json)。这是单台物理机器内的多节点实验，不是多机高可用或性能测试。

## 实际通过的验证

| 内容 | 真实结果 |
|---|---|
| 恢复集群 | 原先 8 个实例停止，恢复后管理器报告 Running: 8 |
| CLI status | 返回版本、数据库、连接角色和 recovery 状态 |
| CLI nodes | 返回 1 CN、2 DN、1 GTM 的主节点目录；不包含全部备节点 |
| CLI database-create --apply | 创建独立测试库 `skill_lab_20261120` |
| CLI table-create --apply | 创建 `public.events(id bigint, payload text)`，按 id 分片 |
| 分布确认 | `pgxc_class.pclocatortype` 为 S |
| 数据读写 | 插入并查询两条测试数据 |
| CLI grant-select --apply | 为专用角色 `skill_reader_20261120` 授予表 SELECT |
| 权限正反向检查 | SET ROLE 后 SELECT 得到 2 行；INSERT 返回 42501 permission denied |
| CLI logs | 读取真实 CN 的 pg_ctl_start.log 末尾 5 行 |
| CLI cluster stop --apply | opentenbase_ctl 报告 8 个实例停止；SQL 连接失败，符合预期 |
| CLI cluster start --apply | 8 个实例重新运行，SQL 恢复，表内仍有 2 行 |

创建角色、前置 CONNECT/USAGE 授权及 SQL 验证通过原生 psql 完成；建库、建表、表 SELECT 授权、状态、节点、日志和启停通过交付的 CLI 完成。没有删除旧数据库或改动原有业务表。

## 真实环境发现并修复的问题

集群由 `opentenbase_ctl` 管理，原先 CLI 仅封装 `pgxc_ctl`，两者配置文件格式不同。本次增加 `--controller opentenbase_ctl`，将 monitor 映射到原生 status。

第一次管理器调用在容器默认目录下超时；切换到配置文件所在的可写管理目录后成功。工具现在显式设置该工作目录，并增加回归断言。原始失败记录保留在 live-demo.json，未删除或冒充成功。集群管理调用使用 120 秒预算；读请求超时不会被解释为整个集群不可用。

## 可复现操作

在已有管理容器内部，配置与本实验一致的环境（其他安装请替换路径）：

```sh
export PATH=/data/opentenbase/install/opentenbase/5.21.8/bin:$PATH
export LD_LIBRARY_PATH=/data/opentenbase/install/opentenbase/5.21.8/lib
export PGHOST=10.206.0.101 PGPORT=11003 PGUSER=opentenbase PGDATABASE=skill_lab_20261120
python3 /tmp/otb_ops.py status
python3 /tmp/otb_ops.py nodes
psql -X -w -c 'SELECT * FROM events ORDER BY id;'
python3 /tmp/otb_ops.py --timeout 120 cluster monitor --controller opentenbase_ctl --config /data/opentenbase/opentenbase_ctl/opentenbase_config.ini
```

从 Mac 可使用 `scripts/lima_lab.sh status`；它依赖已有 otb-lab 和两个容器，并非全新环境安装器。设置 LIMACTL 指向本机兼容的 Lima 可执行文件。`--start` 恢复 VM、容器与集群，`--stop` 正常停止集群、容器和 VM，释放内存，保留数据库磁盘。

## 仍未覆盖

pgxc_ctl 后端的真实执行、多物理机故障切换、性能压测、其他数据库版本及长时间运行。原有 examples/demo-record.json 是早期纯本地计划/模拟演示，保留其 live_database_tested=false；新增 live-demo.json 是这次真实运行证据。
