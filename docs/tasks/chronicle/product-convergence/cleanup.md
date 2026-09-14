# 2026-09-14 清理依据与交付记录

本次按用户授权先清理明确冗余，再把仍需改造的能力拆给 Luna。开发阶段不
保留旧生产入口兼容，不重置或迁移部署数据。本地预先存在的
`apps/chronicle/webapp/design/` 不属于本次修改。

## 已执行的清理

| 发现 | 本次处理 | 保留的有效能力 |
| --- | --- | --- |
| `web/` 的 C0 HTML/JS/CSS 仍被 Rust 发布，Python 也另提供 UI | 删除旧资源与 Python static server；Rust 只嵌入 `web/dist/` | 单一 React 应用、正常 API、SPA 刷新与受控资源 allowlist |
| `historical-entry.ts`、Studio placeholders 没有运行时调用 | 删除，并移除指向占位文件的旧测试读取 | 实际 Studio 页面和当前首页 |
| `routes.ts` 维护不用的解析器，仍将 `/` 当 World | 删除旧 parser/escapeHTML 及专属测试 | React Router，实际 URL builder 和时间格式化 |
| 外部 `/v0/*` 重复公共接口 | 删除 Rust 别名；HTTP 测试要求 404；公共 smoke 改用 `/api/v1/public/*` | Rust 到 Python 的内部 `/v0/*` 协议 |
| 两个 CLI、旧 extraction/presentation 开关与旧 prompt budget 同时存在 | 仅 `production_worker.py` 为正式入口，领取前要求 source + staged 0.4；移除旧入口、开关和预算派生 | ChapterLimits、全局 timeout、当前分步骤处理与 narrative 配置 |
| 正式发布从 prototype 导入身份算法，间接带入模型实验模块 | 算法迁至 `persistence/identity_candidates.py`、`catalog_publication.py`；测试随职责迁移 | 候选、负约束、身份稳定与原子发布；离线 CLI 改为调用正式纯模块 |
| 文档同时描述书籍/World 主体和连续历史，旧验收还要求已删除的模型开关 | 更新 product/worker/server 等当前指南；旧浏览器和 C1 验收页改为历史入口，旧 presentation 明确为保留投影合同 | 来源追溯和历史任务记录；背景手动保存规则 |

## 不能误判为死代码的部分

- `control_plane` Rust crate 是生命周期合同，Python store 镜像其规则；没有直接
  链接到生产 Rust server 不等于可以删除。
- 0.4 chapter schema 仍引用旧文件内的共用字段，reading/person-state 校验仍有
  调用。T01–T03 迁移有效定义和回归后删除旧顶层协议与旧运行分支。
- `/world`、`/timeline`、`/events/{id}` 仍有真实导航调用。T18 在新人物/全局阅读
  接好后统一退役及改链，不能留下死链接。
- 多史料核对史实不替代身份同一性核对；0007 的人工决定/负约束保留。
- 背景技能和离线图库是可用工具，缺的是产品上传、保存关联与阅读渲染。
- `chronicle_persist.py`、migrations 等是命令/启动入口，不能仅按 import 判死。

## 验证

验证针对本次工作区代码执行，具体 CI 和交付版本由 PR 记录。复用原测试环境
中隔离的 PostgreSQL 18 子库，未修改已部署 Chronicle 数据或应用。

<!-- verification:start -->
- 前端：341 项 Vitest 中，修正过时的 chapter parser 断言后对应 suite 全过；其余 321 项此前已过且输入未变。build 与 smoke:dist 通过，编译产物未发生行为差异。
- Python：723 项 persistence 单元、157 项 worker 单元、44 项离线工具测试、3 项 sidecar HTTP 边界测试通过。
- PostgreSQL：24 项 staged chapter、3 项 resolve/publish、7 项身份冲突、2 项 published corpus 边界测试通过。
- Rust：测试服务器隔离目录、Rust 1.97.1，62 项 server 测试及 fmt/clippy 全部通过。首次运行发现并更新了一条仍期待旧章节别名成功的测试；修正后完整 server suite 通过。
- 文档/CI：39 份变更文档链接、20 个叶任务依赖图及 Issue 对应、`git diff --check HEAD` 通过；CI 路由 45 项测试和 actionlint 通过；Compose 含 worker profile 的配置校验通过。
<!-- verification:end -->

可复验命令及环境：

- 本机 Python 虚拟环境执行 `python -m unittest discover -s apps/chronicle/persistence -p '*_unit.py'`、worker 同类 discovery、prototype 的 `test_*.py` 和 read_api 的 `test_server_boundary.py`。
- 前端在 `apps/chronicle/webapp/` 执行 `npm test -- --run`，修复后运行 `npx vitest run tests/chapter-reader.test.ts`；`npm run build` 与 `npm run smoke:dist` 检查单一构建。
- 测试服务器隔离目录 `/root/loom-verification/chronicle-cleanup-20260914` 使用 PostgreSQL 18 子库，运行 staged chapter、resolve/publish、身份冲突和 published corpus 测试；未使用部署库。
- 同一隔离目录使用 Rust 1.97.1 执行 server manifest 的 `cargo test`、`cargo fmt --check` 和 `cargo clippy --all-targets -- -D warnings`，使用工作区默认 target。
- `python -m unittest discover -s tools -p 'test_ci_routing.py' -v`、actionlint 及 `tools/ci_routing.py` 的变更文档检查；Compose 以本次 example env 执行 `docker compose --profile worker config --quiet`。

算法迁移还对比了改名前后的 AST：除异常类去除 prototype 依赖、模型 prompt/调用
移回离线模块外，正式候选与 catalog 算法的函数定义未改变。最终 diff 已自审；
本次以 `f688918b` 为基线的工作区验证不替代交付 PR 自身的 required checks。

这里不把程序回归等同于新的真实模型内容验收。本次没有重跑付费模型生成，
没有声称人物完整生平、跨批次全历史或产品背景已经实现；分别由子任务交付。
