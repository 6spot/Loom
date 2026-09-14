# Chronicle 当前整章验收指南

当前唯一验收入口是 `apps/chronicle/acceptance/staged_gate.py`。它验证
staged 0.4 的完整链路：原文上传、整章翻译、抽取、linking、审核、修复、接受回执、
reading/catalog 发布，以及公开读取。旧轮次的任务、语料和结论仍保留在各自的历史目录，
但不再作为当前 CI 门禁或生产入口。

权威契约见 [chapter-production.md](chapter-production.md)、
[staged-chapter-production.md](staged-chapter-production.md) 和
[review-workflow.md](review-workflow.md)。统一入口与运行时使用
[gate_runtime.py](../acceptance/gate_runtime.py) 的隔离 Compose / PostgreSQL 生命周期。

## Fixture 模式

Fixture 只提供模型 Responses，不生成 accepted artifact，不写产品数据库，也不绕过
worker 的 durable run、step history、candidate validation、review 或 acceptance receipt。
当前唯一 worker fixture 是 `apps/chronicle/worker/staged_pipeline_fixture.py`；它会解析完整
`SOURCE` 提示并生成 staged 0.4 候选。fixture 结果只证明程序链路和结构检查，不能证明真实
翻译、人物判断或历史内容。

```bash
mise install
python3 -m pip install \
  -r apps/chronicle/persistence/requirements.txt \
  -r apps/chronicle/read_api/requirements.txt \
  -r apps/chronicle/worker/requirements.txt
docker build -f apps/chronicle/Dockerfile -t loom-chronicle:local .

printf '%s\n' \
  'CHRONICLE_POSTGRES_PASSWORD=test-only-local' \
  'CHRONICLE_ADMIN_USER=admin' \
  'CHRONICLE_ADMIN_PASSWORD=test-only-local' \
  > /tmp/chronicle-staged-test.env

python3 -m unittest discover -s apps/chronicle/acceptance -p 'test_staged_gate.py' -v
python3 apps/chronicle/acceptance/staged_gate.py \
  --mode fixture \
  --env-file /tmp/chronicle-staged-test.env \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-staged-offline \
  --browser-required
```

CI 使用同一个入口的 `staged-gate` job。成功 manifest 必须包含候选版本 0.4、完整
step history、review decisions、公开 publication/read evidence、失败关闭和重启证据，
并在 `terminal_jobs` 中为每个已完成的 0.4 source job 保留终态 detail、逐 chunk
step history、output metadata 和完整 acceptance receipt。gate 会校验每个阶段、
每个生产步骤、输出 hash 与 receipt 的绑定；任一证据缺失会 fail closed，并在
`manifest.partial.json` 中保留阶段与失败位置。`--skip-browser` 只用于本地快速迭代。

程序检查与人工内容判断分开：脚本检查 schema、source scope、hash、引用/原文锚点、状态
流转、原子发布、重试/取消/lease takeover、无半成品和浏览器结构/性能；人工验收必须完整
阅读每一章原文、完整输出和对应证据，独立判断译文、实体消歧、同名不同人、来源关系、
人物阶段及历史叙事。fixture 的 PASS 不得替代人工内容结论。

## Live 模式

```bash
python3 apps/chronicle/acceptance/staged_gate.py \
  --mode live \
  --env-file .env.chronicle \
  --source-pack apps/chronicle/corpus/first-round/source-pack.json \
  --evidence-dir /tmp/chronicle-staged-live
```

Live 严格拒绝 fixture pack、fixture model、`--auto-decide`、非交互会话以及带凭据/查询
秘密的 endpoint；需要 `CHRONICLE_CHAPTER_MODEL`、`CHRONICLE_NARRATIVE_MODEL` 和真实
provider 配置。当前入口只做 preflight 并写出 `READY` 交接，真实 provider 调用和逐章人工
判断尚未在此环境完成，不能把 `READY` 或 fixture PASS 记作 live 通过。

验收结束后默认 `ComposeStack` 执行 `down -v` 清理隔离栈；只有明确使用
`--keep-stack` 时才保留服务以供同一会话中的浏览器检查。
