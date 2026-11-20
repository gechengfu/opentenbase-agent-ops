# 运维协议与验证边界

## 结构

Agent → `SKILL.md` 选择命令 → argparse 校验 → 生成 SQL/参数列表 → 原生 `psql` / `pgxc_ctl` → JSON 结果。

状态/角色/节点查询统一使用 `json_agg(row_to_json(...))`，避免按空格或表格分隔符拆解 SQL 返回值。原生 psql 的 `-X -w -v ON_ERROR_STOP=1` 禁用启动脚本、交互密码提示并传播 SQL 错误。传给子进程的是参数数组，不经过 shell。数据库和列名按 PostgreSQL 标识符规则转义并限制 UTF-8 字节长度；类型只接受白名单。

## 结果协议

机器可读约束见 [result-schema.json](result-schema.json)。

```json
{"ok":true,"command":"database-create","mode":"plan","data":{"sql":"CREATE DATABASE \"course_demo\";","executed":false},"error":null}
```

所有正常命令返回一行 JSON。`--help`/`--version` 遵循命令行惯例输出文本。

- `mode=read`：查询或本地读取；不代表整个集群健康。
- `mode=plan`：未执行写入、启停操作。
- `mode=apply`：已调用原生命令且收到零退出码。
- 退出码 0：包装命令成功；1：原生命令、超时或本地 IO 失败；2：参数或输入错误。
- `error.code` 为 `INVALID_ARGUMENT` 或 `OPERATION_FAILED`。不会把原生 stderr 原样放入错误 JSON，以免输出连接密钥或数据。

`doctor` 即使缺少客户端也返回成功的诊断结果；请检查 `sql_ready` 和 `cluster_control_ready`。`cluster monitor` 将原生输出放在 `data.output`，固定标注 `health_verified=false`，因为一些原生工具的零退出码不等于全部节点存活。

## 原生接口依据

核对版本：OpenTenBase commit `b2b129b35b58855ea0017650ab2abce192a4d93c`。

- [pgxc_node 系统目录](https://github.com/OpenTenBase/OpenTenBase/blob/b2b129b35b58855ea0017650ab2abce192a4d93c/src/include/catalog/pgxc_node.h)：`node_name/node_type/node_host/node_port`。
- [pgxc_ctl 入口](https://github.com/OpenTenBase/OpenTenBase/blob/b2b129b35b58855ea0017650ab2abce192a4d93c/contrib/pgxc_ctl/pgxc_ctl.c)：`--home`、`-c` 及命令调度。
- [项目测试工具中的启停调用](https://github.com/OpenTenBase/OpenTenBase/blob/b2b129b35b58855ea0017650ab2abce192a4d93c/src/test/opentenbase_test/opentenbase_test.py)：`start all / stop all / monitor all`。
- [分片建表回归样例](https://github.com/OpenTenBase/OpenTenBase/blob/b2b129b35b58855ea0017650ab2abce192a4d93c/src/test/regress/sql/float4.sql)：`DISTRIBUTE BY SHARD`。

这些是源码级接口核对，不是对所有 OpenTenBase 版本的兼容性证明。

## 超时与错误诊断

默认 30 秒，可用全局 `--timeout 1..300` 修改。SQL 还设置服务器 statement_timeout 和连接超时。超时后数据库操作或集群启停可能已部分完成，程序不会自动重试或回滚集群状态。不要把超时解释成“什么都没做”。

缺客户端：先 `doctor`，再指定 `--psql`/`--pgxc-ctl` 或配置 PATH。

查询失败：用同一环境在终端检查 psql 登录、目标数据库、权限；普通 PostgreSQL 没有 `pgxc_node`，应选用正确的 OpenTenBase CN。`PGOPTIONS` 追加 statement_timeout，原有选项保留。

建表失败：检查数据库、schema、默认节点组和权限。grant-select 仅授予表 SELECT，不隐式授予 schema USAGE 或数据库 CONNECT。

日志读取只取文件末尾至多 1 MiB，最多输出 1000 行。截断起始行会丢弃；异常 UTF-8 用替代字符表示。日志输出可能含业务信息，分享演示前请自行脱敏。

## 真实集群验收

状态：**本提交未执行**。需要一个获准修改的独立课程测试集群及已安装的 OpenTenBase 客户端。

1. 配置 CN 的 PGHOST/PGPORT/PGDATABASE/PGUSER。运行 doctor、status、nodes、roles，确认 server version、数据库及 CN/DN 拓扑。
2. 在现有数据库连接上，对一个未存在的专用数据库先运行 database-create 计划，再执行 --apply；用 psql `\l` 验证。
3. 切换 PGDATABASE 到新库，运行 table-create 计划及 --apply；用 `\d public.events` 和节点系统目录验证定义和分布。
4. 在已具备 CONNECT/USAGE 的实验角色上执行 grant-select；以该角色 SELECT 应通过，INSERT 应按权限设置被拒绝。验证前先核对角色并无其他写权限来源。
5. 读取测试集群已知日志。将输出与原文件末尾对照。
6. 仅在允许停机的实验环境生成 cluster stop/start 计划，核对全部受影响节点，再执行 --apply。用原生 monitor 输出和 SQL 可连接性再次确认。
7. 记录版本、拓扑、命令、时间、退出码、脱敏输出。保留失败情况，不覆盖成本地模拟成功记录。清理由实验环境管理者在确认后完成，本工具没有自动 DROP/CLEAN 功能。

## 测试映射

`tests/test_ops.py` 的 11 项测试覆盖：五类计划零副作用、标识符引号、非法/重复列、非法 shard key、类型注入、参数边界、三类查询、错误 JSON、错误退出码、超时、密钥输出约束、apply 单次执行、日志边界、集群路径与状态语义、真实 CLI 及客户端替身进程。
