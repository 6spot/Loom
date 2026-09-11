---
task: C2-R3-T10
issue: 628
kind: leaf
parent: C2-R3
depends_on: [C2-R3-T07, C2-R3-T09, C2-R3-T02, C2-R2-T09]
---

# 统一接入阶段 API、Rust 边界与 typed client

## 范围与交接

[Issue #628](https://github.com/6spot/Loom/issues/628) 对应本任务；具体实施步骤、文件归属和验收要求保留在下文。让生产前端通过已有Rust入口消费人物资料和阶段审核，保持公开/Studio权限、来源版本及类型一致。

- 输入：T07/T09领域API、T01类型、T02的0.3注册；已有 history-api.ts、narrative-types.ts、Rust public/studio代理与原文reader。
- 交付：Python/Rust路由；typed client固定 getReadingPeople / getPersonStates / getPersonStateEvidence / submitPersonStateAssessment，现有 listReviewPage 增加 review_scope；端到端HTTP合同测试。
- 前置：[C2-R3-T07](https://github.com/6spot/Loom/issues/625)、[C2-R3-T09](https://github.com/6spot/Loom/issues/627)、[C2-R3-T02](https://github.com/6spot/Loom/issues/620)、[C2-R2-T09](https://github.com/6spot/Loom/issues/578)

语义与接口以 [人物阶段资料契约](../../../../apps/chronicle/docs/person-state-reading.md) §§5.1、7 为准；全轮任务图见 [README](README.md)。task 记录需求与实施边界，任务状态由当前任务管理工具维护。

## 文件归属

- `apps/chronicle/read_api/router.py`
- `apps/chronicle/read_api/reader_chapters.py（仅0.3读取适配）`
- `apps/chronicle/read_api/source_context.py（仅复用0.3锚点）`
- `apps/chronicle/read_api/test_person_state_router_postgres.py（新）`
- `apps/chronicle/server/src/app.rs（仅API注册）`
- `apps/chronicle/server/tests/person_state_integration.rs（新）`
- `apps/chronicle/webapp/src/lib/person-state-api.ts（新）`
- `apps/chronicle/webapp/src/lib/studio-api.ts（review_scope与状态决定）`
- `apps/chronicle/webapp/tests/person-state-api.test.ts（新）`
- `apps/chronicle/webapp/tests/studio-person-state-api.test.ts（新）`
- `apps/chronicle/docs/read-api.md`
- `apps/chronicle/docs/server.md`

本轮共享HTTP/client唯一owner；T11/T12通过props/回调独立开发，T13在本任务后接App/SPA和static assets。

主阅读复用 C2-R2E 的 version/paragraph 接口与 `clear|uncertain` 类型，不用来源 stream/unit 包装综合正文。共用事实审核沿用 narrative ReviewItem 分派；任何来源阶段评估都不跳过最终结论审核。原文继续经已有 source reader，浏览器不直连 sidecar。

## 已有综合审核必须保留

按 #619 的联合 DTO 扩展时，保留当前 `studio-api.ts` 中的 `scope=narrative`、facts/prose 详情、显式结论覆盖和两次审核提交方法。新增 person_state 不能把类型收窄为只有 resolution/person_state，也不能丢失 narrative 的错误、409 或候选 hash 校验。

Rust／typed client 集成验证包含混合 all 队列的三种 scope、四种实际审核表单，并分别提交正确 payload；错 scope 的决定应失败。主阅读／人物详情继续固定综合 version/paragraph/phase，来源 stream/unit 参数不替代它们。

## 实施步骤

1. 在现有 Python router/Rust public routes 接入 T09 的 history 状态扩展，复用 history-api.ts 的固定版本及结论读取；来源 people/states 分支保持原义。Studio 沿同一 reviews 路径按 scope 分派，浏览器不得绕过 Rust。
2. 保持Studio先认证后资源检查，匿名401、未配置503；public只读已发布成员，0.3原文仍走唯一source reader。
3. typed client导入T01类型，query/cursor带完整locator/scope；支持abort/重试所需错误，不用any或另写简化DTO。
4. 验证正常读取、状态评估、错误方法、重复参数、超限/404/409、catalog错配、跨publication锚点；不读环境里的latest来补参数。
5. 同步现有API说明与相关消费者测试；本任务不接生产页面或生成dist。

## 验收

- [ ] Rust→Python→PG的public与Studio状态合同可用，权限和错误正确。
- [ ] 0.3来源查询沿唯一reader，错版本/越权锚点不泄露内容。
- [ ] typed client与T01 DTO/分页一致，identity和state决定不会串型。
- [ ] 无新的产品服务/DB直连/页面接线；共享入口变更集中于本任务。
- [ ] HTTP 与 typed client 的混合队列保留 narrative facts/prose，错误 scope 不能串用决定，原有综合审核调用回归通过。
- [ ] typed client 与 T01 DTO／分页一致，identity、state、narrative 决定不串型；综合位置与来源位置有不同类型，现有 HistoryReturnLink 返回契约保留。

## 验证要求

```bash
python3 -m unittest discover -s apps/chronicle/read_api -p 'test_person_state_router_postgres.py' -v
cargo test --manifest-path apps/chronicle/server/Cargo.toml --test person_state_integration
cargo fmt --manifest-path apps/chronicle/server/Cargo.toml -- --check
npm --prefix apps/chronicle/webapp test -- tests/person-state-api.test.ts tests/studio-person-state-api.test.ts
```

Rust测试用真实sidecar/PG的既有integration harness；Cargo产物只用workspace-local target。

以上是实施后的验证要求；新增脚本尚由该任务交付。按[当前交付流程](../../../development/task-completion.md)在 PR 记录实际检查、内容证据及未验证项。
