---
task: C2-R3
issue: 550
kind: root
depends_on: []
children: [C2-R3-D01, C2-R3-D02, C2-R3-T01, C2-R3-T02, C2-R3-T03, C2-R3-T04, C2-R3-T05, C2-R3-T06, C2-R3-T07, C2-R3-T08, C2-R3-T09, C2-R3-T10, C2-R3-T11, C2-R3-T12, C2-R3-T13, C2-R3-T14, C2-R3-T15]
---

# Chronicle 第三轮：人物身份与关系随阅读阶段变化

父协调 Issue [#550](https://github.com/6spot/Loom/issues/550)，总规划 [#547](https://github.com/6spot/Loom/issues/547)。本轮拆为 **2项准备任务＋15项实现/验收任务**。此索引记录需求、输入、文件归属与验收顺序；任务状态由当前任务管理工具维护。

产品语义以 [person-state-reading.md](../../../../apps/chronicle/docs/person-state-reading.md) 为准。本次交付的是设计和任务拆分，下面的产品能力由子任务实施。

## 已收敛的范围

- 官职、爵号和明确的效力/归附关系，按有原文支持的叙事阶段显示，稳定人物身份不随头衔改变。
- 每项分别有“明确/不明确”标记；弱化项保持可读可查，不凭confidence染色，不把未知、未来、结束和没有材料混为一谈。
- 当时身份、本段角色、本段变化分开；同年不同阶段、兼任、多阶段过程、回看、来源分歧有明确规则。
- 在同一完整章0.3联合产物中抽取，按章集中核对阶段依据，发布前编译，阅读消费固定版本。
- 沿用R2人物区/移动入口、唯一controller和既有原文阅读器；背景图产品、长期联盟、亲缘图谱和全生平重建保持各自后续范围。

## 任务图

表中依赖是具体输入、接口和文件交接。跨轮接口与验收依赖保留，设计准备可先启动。

| Task | Issue | 前置 | 交付 |
| --- | --- | --- | --- |
| [D01](D01-person-state-cases.md) | [#617](https://github.com/6spot/Loom/issues/617) | [C2-R1-T02](https://github.com/6spot/Loom/issues/552) | 真实人物变化链与阶段反例语料 |
| [D02](D02-person-state-interaction-design.md) | [#618](https://github.com/6spot/Loom/issues/618) | 无 | 人物阶段资料与依据审核的桌面、窄屏交互设计 |
| [T01](T01-person-state-contract.md) | [#619](https://github.com/6spot/Loom/issues/619) | [C2-R3-D01](https://github.com/6spot/Loom/issues/617)、[C2-R2-T01](https://github.com/6spot/Loom/issues/570)、[C2-R2-T02](https://github.com/6spot/Loom/issues/571) | 0.3 阶段资料 schema、校验器与前后端共享类型 |
| [T02](T02-person-state-generation.md) | [#620](https://github.com/6spot/Loom/issues/620) | [C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R2-T03](https://github.com/6spot/Loom/issues/572) | 完整章联合生成阶段事实并接入现有 provider |
| [T03](T03-person-state-assembly.md) | [#621](https://github.com/6spot/Loom/issues/621) | [C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R2-T04](https://github.com/6spot/Loom/issues/573) | 跨章阶段依据 remap 与不可变证据组装 |
| [T04](T04-person-state-projection.md) | [#622](https://github.com/6spot/Loom/issues/622) | [C2-R3-T03](https://github.com/6spot/Loom/issues/621) | 按叙事阶段编译身份、变化与两档明确性 |
| [T05](T05-person-state-store.md) | [#623](https://github.com/6spot/Loom/issues/623) | [C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R2-T05](https://github.com/6spot/Loom/issues/574) | 阶段评估、人物投影与快照分歧索引持久化 |
| [T06](T06-person-state-review-core.md) | [#624](https://github.com/6spot/Loom/issues/624) | [C2-R3-T04](https://github.com/6spot/Loom/issues/622)、[C2-R3-T05](https://github.com/6spot/Loom/issues/623)、[C2-R1-T08](https://github.com/6spot/Loom/issues/558) | 按章冻结阶段依据审核与评估产物 |
| [T07](T07-person-state-review-api.md) | [#625](https://github.com/6spot/Loom/issues/625) | [C2-R3-T06](https://github.com/6spot/Loom/issues/624)、[C2-R1-T09](https://github.com/6spot/Loom/issues/559)、[C2-R1-T10](https://github.com/6spot/Loom/issues/560) | 混合审核队列、阶段依据详情与原文 API |
| [T08](T08-person-state-publication.md) | [#626](https://github.com/6spot/Loom/issues/626) | [C2-R3-T02](https://github.com/6spot/Loom/issues/620)、[C2-R3-T04](https://github.com/6spot/Loom/issues/622)、[C2-R3-T06](https://github.com/6spot/Loom/issues/624)、[C2-R2-T06](https://github.com/6spot/Loom/issues/575) | 将阶段审核与人物投影接入唯一生产发布事务 |
| [T09](T09-person-state-read-api.md) | [#627](https://github.com/6spot/Loom/issues/627) | [C2-R3-T04](https://github.com/6spot/Loom/issues/622)、[C2-R3-T05](https://github.com/6spot/Loom/issues/623)、[C2-R2-T07](https://github.com/6spot/Loom/issues/576)、[C2-R2-T08](https://github.com/6spot/Loom/issues/577) | 当前阅读片段的人物摘要、阶段详情与依据查询 |
| [T10](T10-person-state-http-client.md) | [#628](https://github.com/6spot/Loom/issues/628) | [C2-R3-T07](https://github.com/6spot/Loom/issues/625)、[C2-R3-T09](https://github.com/6spot/Loom/issues/627)、[C2-R3-T02](https://github.com/6spot/Loom/issues/620)、[C2-R2-T09](https://github.com/6spot/Loom/issues/578) | 统一接入阶段 API、Rust 边界与 typed client |
| [T11](T11-person-state-reader-components.md) | [#629](https://github.com/6spot/Loom/issues/629) | [C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R3-D02](https://github.com/6spot/Loom/issues/618)、[C2-R2-T14](https://github.com/6spot/Loom/issues/583) | 阅读人物区的身份、角色、变化与两档标记组件 |
| [T12](T12-person-state-review-components.md) | [#630](https://github.com/6spot/Loom/issues/630) | [C2-R3-T01](https://github.com/6spot/Loom/issues/619)、[C2-R3-D02](https://github.com/6spot/Loom/issues/618)、[C2-R1-T11](https://github.com/6spot/Loom/issues/561)、[C2-R1-T12](https://github.com/6spot/Loom/issues/562) | 按章阶段依据审核表单与连续操作组件 |
| [T13](T13-person-state-page-integration.md) | [#631](https://github.com/6spot/Loom/issues/631) | [C2-R3-T08](https://github.com/6spot/Loom/issues/626)、[C2-R3-T10](https://github.com/6spot/Loom/issues/628)、[C2-R3-T11](https://github.com/6spot/Loom/issues/629)、[C2-R3-T12](https://github.com/6spot/Loom/issues/630)、[C2-R2-T15](https://github.com/6spot/Loom/issues/584) | 统一接入阅读阶段联动、混合审核页面与生产构建 |
| [T14](T14-person-state-automated-gate.md) | [#632](https://github.com/6spot/Loom/issues/632) | [C2-R3-T13](https://github.com/6spot/Loom/issues/631)、[C2-R2-T16](https://github.com/6spot/Loom/issues/585) | 阶段资料整链、审核交互与阅读性能自动验收 |
| [T15](T15-person-state-live-acceptance.md) | [#633](https://github.com/6spot/Loom/issues/633) | [C2-R3-T14](https://github.com/6spot/Loom/issues/632)、[C2-R2-T17](https://github.com/6spot/Loom/issues/586) | 真实整章人物阶段资料与阅读体验独立验收 |

```mermaid
flowchart LR
  D01["D01 真实案例"] --> T01["T01 契约/类型/基座"]
  R201["R2-T01/T02"] --> T01
  D02["D02 交互设计"] --> T11["T11 阅读组件"]
  D02 --> T12["T12 审核组件"]
  T01 --> T02["T02 整章生成"]
  T01 --> T03["T03 证据组装"]
  T01 --> T05["T05 存储"]
  T01 --> T11
  T01 --> T12
  T03 --> T04["T04 阶段编译"]
  T04 --> T06["T06 审核核心"]
  T05 --> T06
  T06 --> T07["T07 审核 API"]
  T02 --> T08["T08 生产发布"]
  T04 --> T08
  T06 --> T08
  T04 --> T09["T09 阅读 API"]
  T05 --> T09
  T07 --> T10["T10 路由/client"]
  T09 --> T10
  T02 --> T10
  T08 --> T13["T13 页面统一接线"]
  T10 --> T13
  T11 --> T13
  T12 --> T13
  R215["R2-T15"] --> T13
  T13 --> T14["T14 自动验收"]
  R216["R2-T16"] --> T14
  T14 --> T15["T15 真实验收"]
  R217["R2-T17"] --> T15
```

图突出本轮依赖和最终接线；表格列出每项完整跨轮前置。[第一轮](../first-round/README.md)负责完整章/身份审核/引用，[第二轮](../second-round/README.md)负责阅读unit/controller/snapshot。第三轮设计或fixture通过不替代前两轮的真实内容验收。

## 并行批次与可评阅节点

1. **先交真实案例和页面设计：D01、D02可并行。** 现有古文足够，D02用已提交原文核对点和标明synthetic的交互数据开始，不等待补传材料。
2. **T01固定机器接口。** 消费D01和R2契约/基座，统一schema、类型、审核键及浏览器suite。评阅点是16案的期望、四种宽度和两档/过程/分歧效果。
3. **按文件并行实现。** T02生成、T03组装、T05存储，以及具备各自前置的T11/T12组件互不抢文件。T04接T03完成阶段算法；T06接T04/T05完成依据审核。
4. **服务层分开交付。** T07审核API、T08生产发布、T09阅读API在各自前置具备后可并行；T10统一外层路由/client。该节点独立核对API、审核决定与发布原子性。
5. **统一接线与独立验收。** T13单独接生产页面及dist；T14验证整链/浏览器/性能和CI；T15用真实模型和完整章逐案验收。

并行按写入文件和接口组织，不要求每项单独开分支。同一工作区的Git索引/提交/推送、依赖安装、build和dist写入串行安排。准备/纯组件与最终生产接线有不同验收边界，不能把fixture展示当成真实后端通过。

## 文件所有权

| 文件/入口 | 本轮所有者与交接 |
| --- | --- |
| third-round/cases 与只读定位检查 | D01 |
| docs/design/person-states 静态设计 | D02 |
| 新0.3 schemas、person_state_contract.py、person-state-types.ts、共享browser suite注册 | T01；后续模块消费同一契约 |
| chapter_contract版本注册、prompt/extraction/provider/fixture_model | T02；R2-T03之后接手 |
| assembly.py 与 person_state_assembly.py | T03；R2-T04之后接手 |
| person_state_projection.py | T04；审核/发布/API共用 |
| 0008迁移与 person_state_store.py | T05；外层事务由T08持有 |
| person_state_review.py | T06；不改身份合并规则 |
| studio_person_states.py 与 studio_reviews领域队列 | T07 |
| chapter_stage/resolve_publish/chapter_store生产接线 | T08；唯一生产发布owner |
| reading_people.py | T09；使用T05查询接口 |
| 顶层router、Rust API、typed clients、source 0.3适配 | T10 |
| 阅读人物组件/局部CSS/自己的scene与spec | T11；ReadingContextPanel从R2-T14接手 |
| 阶段审核组件/局部CSS/自己的scene与spec | T12 |
| ReadingPage/Studio页、review-session、查询hook、App/SPA/build/dist/static assets | T13；server app.rs从T10顺序接手 |
| CI、gate_runtime、第三轮整链和person-state-acceptance运行指南 | T14；从R2-T16接手共享生命周期/CI |
| 真实运行报告与验收结果索引 | T15；person-state-acceptance.md在T14之后接手 |

两个跨任务共享文件已有明确串行依赖：T10→T13的server app.rs，T14→T15的验收指南。其余任务如果发现需要修改另一owner文件，协调一次明确交接，不复制第二套实现来绕过依赖。

## 固定交接接口

| 提供方 | 消费方与交付边界 |
| --- | --- |
| D01 | T01/T15：case_id、真实/合成、source hash/selector、人物/阶段/显示预期/禁止结果 |
| T01 | 各模块：0.3 schema、Python/TS DTO、评估候选键、状态键、cursor/大小/排序与browser fixture协议 |
| T03 | T04/T06/T08：同一revision ref map及保留原章归属的evidence manifest |
| T04 | T06/T08：compile_person_state_projection；T08/T09：已编译状态和catalog分歧索引 |
| T05 | T06/T08：不可变评估/manifest/index写入；T09：list_unit_people/list_unit_person_states/list_state_item_evidence |
| T06 | T07/T08：build/open/resolve/collect阶段依据审核接口；不承担身份合并 |
| T07/T09 | T10：领域dispatcher和错误/分页合同，不直接挂顶层HTTP |
| T10 | T13：getReadingPeople/getPersonStates/getPersonStateEvidence/submitPersonStateAssessment与review_scope |
| T11/T12 | T13：受控props和来源/事件/提交回调；组件不拥有全局历史或审核状态 |
| T13 | T14/T15：同locator的实际页面、生产dist与普通Studio上传/审核/发布路径 |

## 轮次验收

- [ ] 首批类型/阶段/明确性契约有机器校验与真实/合成反例。
- [ ] 整章0.3生产保留完整译文、指代、事件/Claim、阶段依据与原文归属。
- [ ] 同年不同阶段、兼任、针对性结束/再次任职、未知任期/空态和来源分歧正确。
- [ ] 按章依据审核完整可追溯，身份决定与状态评估不互相替代。
- [ ] 公开读取和阅读联动固定同一版本，回读/刷新/返回不泄漏未来或旧请求。
- [ ] 两档标记、来源、触屏/键盘及长页连续审核达到设计与可操作性要求。
- [ ] 自动真实栈门、适用CI与真实provider逐案内容/体验验收分别留下结果。

## 交付

各leaf由自己的Issue说明目标/步骤，canonical合同拥有语义，task说明保留范围/前置/文件/验收。按[当前仓库流程](../../../development/task-completion.md)交付实现、验证、review与PR。父Issue保持阶段协调用途，任务状态以当前任务管理工具为准。
