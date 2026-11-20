# OpenTenBase Agent 运维 CLI / Skill

作者：付格丞（GitHub：`gechengfu`）。课程作业：OpenTenBase 社区 CLI、Skill 技能包开发。

将原生 `psql` SQL 和 `pgxc_ctl` 运维命令封装为可安装、可自动测试的 CLI，并提供 Agent 的调用说明。工具不自建数据库，也不替代 OpenTenBase 服务端。

## 交付物

| 作业要求 | 文件 |
|---|---|
| 工具代码 | `scripts/otb_ops.py`，`pyproject.toml` |
| Skill 包 | `SKILL.md` 和关联 references/scripts |
| 测试 case | `tests/test_ops.py`，自动覆盖正常、错误和边界行为 |
| 使用说明 | 本文和 `references/operations.md` |
| 演示记录 | `examples/demo-record.json`、`examples/test-results.txt` |
| 可复现演示 | `scripts/demo.py`，重跑生成本地记录 |
| 设计与限制 | `references/operations.md` |

## 安装

Python 3.9+。运行时只依赖标准库。直接使用无需安装：

```sh
python3 scripts/otb_ops.py --help
python3 scripts/otb_ops.py doctor
```

也可在虚拟环境安装命令入口（构建需要 setuptools）：

```sh
python3 -m venv .venv
. .venv/bin/activate
python3 -m pip install .
otb-ops --help
```

作为 Skill 使用时，把整个仓库复制到支持 `SKILL.md` 的 Agent 技能目录下的 `opentenbase-agent-ops` 文件夹。以 Codex 为例可放到 `~/.codex/skills/opentenbase-agent-ops`，重新加载后用 `$opentenbase-agent-ops` 调用。这里交付的是包；没有修改你的全局 Agent 配置。

## 配置连接

使用 **OpenTenBase 自带的客户端**。设置目标 CN 的 libpq 环境变量：

```sh
export PGHOST=127.0.0.1
export PGPORT=11003
export PGDATABASE=postgres
export PGUSER=opentenbase
# 密码配置在权限为 0600 的 .pgpass / PGPASSFILE 中，不要放进命令行。
python3 scripts/otb_ops.py --psql /path/to/opentenbase/bin/psql status
```

上面的端口和路径是示例，需替换为实际部署值。集群命令在已有 `pgxc_ctl` 管理环境上执行，所需 SSH、节点注册、默认节点组均由现有集群配置提供。

## 核心调用

以下使用安装后的 `otb-ops`；也可替换为 `python3 scripts/otb_ops.py`。

```sh
otb-ops status
otb-ops nodes
otb-ops roles
otb-ops logs --file /path/to/postgresql.log --lines 30

# 默认只生成计划；核对目标后添加 --apply 才执行。
otb-ops database-create --name course_demo
otb-ops database-create --name course_demo --apply
export PGDATABASE=course_demo
otb-ops table-create --name events --column id:bigint --column payload:text --shard-key id
otb-ops table-create --name events --column id:bigint --column payload:text --shard-key id --apply
# reader 应已存在，并已有数据库 CONNECT / schema USAGE 权限。
otb-ops grant-select --table events --role reader
otb-ops grant-select --table events --role reader --apply

otb-ops cluster monitor --home /path/to/admin --config /path/to/pgxc_ctl.conf
otb-ops cluster start --home /path/to/admin --config /path/to/pgxc_ctl.conf
# stop 同样先生成计划，执行时会影响配置中的全部节点。
otb-ops cluster stop --home /path/to/admin --config /path/to/pgxc_ctl.conf
```

建表允许 `bigint/integer/text/boolean/date/timestamptz/numeric`，重复传入 `--column 名称:类型`，必须指定一个已声明的 shard key。当前不封装索引、任意 SQL、删除数据库、复杂约束、角色创建或撤销权限。建库不是幂等操作，重复执行会报错。

## Agent 调用示例

用户：“查看实验集群有哪些节点，把最近 20 行日志给我总结一下。”

Agent 使用 `nodes` 和指定路径的 `logs`，根据 JSON 的 `ok` 和退出码处理结果，不把节点目录记录当作存活检测。

用户：“在 course_demo 里建一个按 id 分片的 events 表。”

Agent 核对连接目标、生成 `table-create` 计划，然后根据授权执行 `--apply`；成功后用 `psql` 的 `\d public.events` 验证表定义。若超时，先检查表是否已创建，不自动再次建表。

## 测试与演示

```sh
python3 -m unittest discover -s tests -v
python3 scripts/demo.py
```

测试包含真实 CLI 子进程、可执行客户端替身，以及原生命令层的单元测试；客户端替身不是真实数据库。演示实际运行了本地检查、计划生成、日志读取和参数错误处理。`demo-record.json` 记录命令、输出、退出码及验证类型。

2026-11-20 已在免费本地 Lima ARM64 Linux 虚拟机、两个 Docker 容器中的 OpenTenBase 集群补做真实验收。记录见 [live-demo.json](examples/live-demo.json) 和 [本地集群说明](references/local-lab.md)。初版的 demo-record.json 保留为纯本地模拟/计划演示历史记录。真实启停使用 opentenbase_ctl；pgxc_ctl 后端仍仅有单元测试。

## AI 使用与原创工作

本作业由 `gechengfu` 使用 Codex 辅助进行方案设计、编码、测试、文档和提交。测试输出由实际执行生成；未执行的集群验收明确标注。提交者应理解代码并能解释 JSON 协议、标识符转义、执行计划和测试边界，按课程要求披露 AI 使用。

MIT License。未复制 OpenTenBase 服务端实现；源接口对应关系见参考文档。

## OpenTenBase 原生管理器

已有集群由 opentenbase_ctl 管理时，不要将 INI 配置交给 pgxc_ctl：

```sh
otb-ops cluster monitor --controller opentenbase_ctl --config /path/to/opentenbase_config.ini
otb-ops --timeout 120 cluster stop --controller opentenbase_ctl --config /path/to/opentenbase_config.ini --apply
otb-ops --timeout 120 cluster start --controller opentenbase_ctl --config /path/to/opentenbase_config.ini --apply
```

该后端把 monitor 映射为原生 status，无需 --home。可通过全局 --opentenbase-ctl 指定可执行文件。
