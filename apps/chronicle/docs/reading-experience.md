# Chronicle 第二轮：阅读界面与交互验收

状态：待实施；属于 [#549](https://github.com/6spot/Loom/issues/549)。数据含义、路由和发布边界以 [continuous-reading.md](continuous-reading.md) 为准。此文固定布局、交互和可观察结果；task 文档记录任务范围、接口前置和验收要求。

新增背景设计见 [background-art.md](background-art.md)：按时代制作淡彩背景，AI 可建议位置，用户明确触发生成/上传并校验保存后才展示。仅页面背景，不插入正文；滚动和内容生产均不自动生成图片。技能/离线候选库由 D01 提供，产品上传、保存/关联和背景渲染另待拆分，当前没有可评阅的完整阅读页面原型。

## 1. 页面组织

新增 `/read` 目录与 `/read/{stream_id}?catalog={sha}&at={unit_id}` 连续阅读页。`at` 可省略以从首段开始；入口解析后 URL 固定 catalog。第一轮篇章目录/详情保留，并提供连续阅读入口；已有 Timeline / Event Detail 提供“进入相关正文”。新的主体不是一串每段各带边框的事件卡片。

桌面宽度 >= 1200px：左侧 140–180px 阅读时间轴，中间最大 42rem 正文，右侧 220–260px 当前人物/地点。正文优先取得空间，三列含间距总宽不超过 1440px。768–1199px：保留窄时间轴与正文，人物地点移到可展开区域。<768px：单栏正文，当前叙事时间及“人物地点”入口置于紧凑 sticky 阅读栏，时间轴按需展开为可关闭的列表。不出现挤压正文的三栏缩放版。

正文默认 18px、line-height 1.85，窄屏不小于 17px，段落间距 1em；中文正文字体优先系统 Songti SC / Noto Serif CJK SC / serif，控件沿用系统无衬线。章标题、来源、正文、辅助入口有清楚层级；不额外下载阻塞首屏的外部字体。采用现有色系与 token，轴线低对比、当前区段有清晰文字和形状提示。内部 schema、canonical、hash、grounding 等术语不放在默认阅读文案中，审计信息保留到来源详情。

顶层原 HistoricalTimeBar 不与阅读轴重复控制同一正文。阅读页的 compact bar 显示 active unit 的叙事时间，unknown 原样表达；只有显式“在历史时间线查看”才把有依据的 normalized 年/范围转换为既有筛选参数。进入或滚动正文不修改 World 时间、不创建 Runtime Timeline，也不通过 `withHistoricalTime` 把回溯事件的年份覆盖阅读 URL。

## 2. 合成交互示例

以下仅为界面合同示例，不是史料译文：

| 阅读顺序 | 本段正在叙述 | 正文中的旁及 | 轴与侧栏 |
| --- | --- | --- | --- |
| A / u01 | 建安十三年，史料历法八月 | 无 | 显示年 + 史料八月；人物甲、地点甲 |
| A / u02 | 同一时段，显式继承 u01 | 提到更早事件 E | 继续同一轴区段；悬停 E 不改叙事时间 |
| A / u03 | 同年史料九月 | 无 | 只新增九月标记；更新为本段人物/地点 |
| A / u04 | 下一年，仅知年份 | 回忆赤壁事件 R | 新年、“月份未明确”；R 可预览/主动定位 |
| B / v07 | R 的发生叙述，另一来源 | 无 | 主动切换到 B 并更新轴；一键返回 A/u04 |
| A / u05 | 时间未明确 | 同名但未确定的事件 | 未知区段；没有静默跳转链接 |

真实示例任务用第一轮固定四章找出对应材料；缺少某种情况时使用明确标为 synthetic 的负例，不虚构真实书籍存在该段。

## 3. 连续内容与窗口

正文以 unit 为滚动定位单元；不对译文重新分句或按词切字。API 分页可跨章，章标题仅在实际边界出现。相邻页相同 group_id 不重复显示年份/月标记，来源边界不丢失。

使用一个正文窗口组件：默认预取相邻一页，前后页双向加载，保留测得高度的占位区以避免移除上方页面时跳动。正常最多 120 个已渲染 unit；正在聚焦、文本选择或展开引用的 unit 固定保留，最多额外 20 个，若不能安全回收则停止预取并显示显式加载入口，不移除用户正在操作的 DOM。远处目标通过 locate 直接加载，而非连续下载前面所有页。

窗口组件负责页合并/去重、占位高度、加载失败与“重试/上一段/下一段”入口；阅读控制器负责 active unit、路由和恢复。两者通过 typed callbacks 交接，不能各有一套滚动/历史控制。文字大小、窗口宽度变化使缓存高度失效时，重新测量并优先保持当前 unit。不得仅按旧 scrollY 恢复。

## 4. 当前片段的确定

单一 controller 维护 `{stream, catalog, active_unit, narrative_time, navigation_state}`。阅读参考线位于 sticky header 下方可用视口高度的 30%；取穿过参考线的 unit，落在间隙则取紧随其后的可见 unit，末尾取最后一个。并列按 ordinal 确定。用 IntersectionObserver 配合有界测量和 requestAnimationFrame 合批，不每个 scroll 事件扫描全文。

滚动改变 active unit 时，轴和人物地点用同一个状态更新。第二轮仅消费 unit 自带 context，不计算长期身份。第三轮按 [person-state-reading.md](person-state-reading.md) 订阅同一 locator，一次有界获取本 unit 的人物资料；不发全世界查询或逐人状态请求，不增加另一个滚动控制器。

预览开启不改 active unit；展开原文引起布局变化时先保持触发 unit，用户再次滚动才恢复跟读。主动跳转有独立 restoring 状态：目标页到达、字体/尺寸稳定后滚动并聚焦目标段；旧请求不能抢回视口。用户 wheel/touch/键盘滚动可取消未完成的自动恢复。网络失败保持已读正文和明确错误，不清空整页。

## 5. 事件预览与来源

事件词呈现克制的下划线/颜色提示，正文仍是普通文本。resolved span 才是可操作事件入口；ambiguous/unresolved 不冒充唯一事件链接，可显示明确的不确定提示。

鼠标具备 hover 能力时停留约 180ms 打开轻量卡，离开 trigger/card 后约 120ms 关闭，指针移进卡片不会闪退。键盘 focus 打开预览，Escape 关闭并回到触发词；Tab 可进入卡片按钮，无焦点陷阱。触屏点击打开同一内容的 popover 或窄屏底部面板，不能以首次 tap 直接离开正文。遵守 reduced-motion；开合只用 <=160ms 的 opacity/transform，不做改变正文高度的弹跳。

预览包含事件名、来源时间/分歧、简短已有译文摘录或来源说明，以及“查看事件”“定位发生位置”“其他记载”。默认不塞入完整事件详情；来源和人物角色保留归属。targets 多个时在卡片/面板内让用户选来源、章和位置；无 current target 如实提示，没有自动跳到回溯 mentions。

同一时刻一个预览；关闭/换词后晚返回请求不得覆盖新卡。缓存按 catalog + event_id，合并并发同请求并设置有界缓存（最多 100 个事件、总 payload 至多 2 MiB、每条不超过协议响应上限，LRU 淘汰）；仅在 hover/focus/tap 时加载，不为全文所有事件预先请求。等待/失败时触发词和正文保持可用，提供重试。

引用复用第一轮 ChapterSourceReference 及唯一 source API。片段→上下文→整章按需展开；关闭恢复原触发焦点及 reading locator，不切换叙事时间，不将旧 publication 的来源换成最新文件。

## 6. URL、历史和返回

稳定 locator 为 `{stream_id, catalog_sha, unit_id}`；local bookmark 另外保存 history entry key、unit 内相对位置、触发焦点标识和来源展开状态。URL 保存可分享的 locator，sessionStorage 保存当前 tab 的细节；最多 20 个返回项并限制存储大小，不保存全文或认证信息。存储不可用时仍可用 URL 定位。

自然滚动只在 active unit 稳定约 250ms 后 replace 当前 URL，不向浏览器历史压入每段。点击轴、进入事件、选其他来源等明确导航使用 push，导航前记录原 locator；后退/前进读取自己的 history entry。不得只调用 history.back()：没有本站前项或从新标签页打开时仍有正常入口。

从事件/实体详情“返回阅读”使用本站 sessionStorage 中的不可预测 return token 指向 typed locator。刷新详情后 token 仍可恢复；token 缺失/失效显示“进入相关正文”，不跳到外部 return_to。任何 URL 只由校验过的 stream/unit/catalog 字段构建，不接收模型生成 URL。跨来源 A→B→事件→返回，按栈逐层恢复。过期或不存在的 locator 显式提示，用户可回该 stream 目录，不能静默换新版或首段冒充恢复成功。

恢复先校验 snapshot/stream/unit，调用 locate，等待目标真实 DOM，再恢复 unit 内位置与焦点；浏览器 back、forward、刷新及直接深链接分别测试。引用/预览正常开关不改 URL 历史，重复操作不积累返回项。metadata hash 是缓存版本边界，不把源文件 raw bytes 坐标当译文滚动坐标。

## 7. 必测场景与预算

协议和数据库测试拥有数据正确性，真实浏览器拥有交互/布局证明，人工内容核对拥有主叙事和来源判断；不得互相替代。

- 时间：同月多段、跨月/年、仅年份、未知、source month 与 Gregorian 不等价、闰月 opaque、range/mixed/分歧、倒叙、页边界同 group、跨章同年与较早年份。
- 事件：同名不同 ID、重复译文词的第二次 occurrence、跨 Unicode 扩展汉字位置、重叠 span 拒绝、一个当前事件/多个目标/只有回溯/无目标、加载失败、迟到响应、不能按名称静默跳转。
- 当前片段：人物没有直接 Claim 仍能经原文支持出现；从有人段转到无人段正确清空；同人去重但角色来源不丢；地点不冒充人物位置，事件角色不变成长久官职。
- 导航：连续加载/反向加载、远端定位、字体/窗口变化、引用展开、A→B→Event→返回、back/forward、刷新、存储失效、旧 stream 与新 snapshot、失效 locator、恢复中主动滚动。
- 可操作性：1440×900、1024×768、390×844、320×568，200% 字体/缩放，无横向正文溢出；键盘完整完成预览/选择/来源/返回；触屏面板可关闭且不遮最后一段；reduced-motion；焦点可见、按钮至少 44×44 CSS px，正文与控件对比度满足 WCAG AA。
- 数据规模：第一轮四个完整自然章真实阅读，另用明确合成的 5,000 units / 1,000 groups 验证窗口和定位。测量而非声称大规模历史能力。

性能检查在固定 Chromium/viewport、同机本地 Rust→Python→PG fixture 栈上记录环境和 5 次结果：排除网络请求后的 active-unit 到侧栏更新 p95 <=100ms；已取得 locate/page 数据后恢复 p95 <=250ms；1,000 次段落推进中 mounted unit 不超过上述窗口规则，event preview 不产生 N+1 全量预取。连续滚动 30 秒记录 Long Tasks，不能出现阅读代码引起的 >=200ms 主线程任务；网络/来源错误不制造正文跳位。未达到预算就查明原因并修复，不能临时放宽数字让门禁变绿。

真实内容验收使用新环境经 Studio 联合生成 0.2、审核、发布，逐条核对至少 12 个真实定位点；报告包含候选 commit、publication/stream/catalog、操作录像或截图、原文锚点和判断。fixture 只能证明行为，不证明译文/事件对应正确。没有能力或样本证明的内容明确记为未验证。

## 8. 开发与验证入口

任务清单给出每个模块的检查命令；现有仓库命令仍为 Python unittest、webapp `npm test` / `npm run build` / `npm run smoke:dist`、Rust cargo test/clippy/fmt。本轮测试脚本由对应任务创建，未存在前不能宣称已运行。

独立组件在自己的 Vite fixture scene 中验证，不提前接 App，不写生产 dist；修改生产页面的集成任务必须同次提交匹配 web/dist 和 Rust 资源注册。package 安装、build 以及 dist 写入在共享工作区预约串行窗口。

新 `webapp/scripts/reading-component-smoke.mjs` 由组件基座任务提供统一只读浏览器 driver，接口固定为 `--base-url http://127.0.0.1:5173 --suite harness|content|axis|position|events|context|all --output <directory>`；fixture 页面通过 Vite 提供，不能当成真实后端验收。harness 只验证基座；all 必须五个组件 suite 均存在且通过，不能跳过未实现的场景。每个组件任务拥有自己的 scene/spec 文件，避免改一个共享脚本。

集成后的 `webapp/scripts/reading-flow-smoke.mjs` 由最终自动验收任务提供，接口 `--base-url http://127.0.0.1:18080 --fixture-manifest <path> --suite flow|accessibility|performance|all --output <directory>`；真实 Rust/Python/PG 数据和 manifest 由同一验收任务准备，不用 HTTP mock 冒充整链。统一薄入口 `acceptance/second_round_gate.py --mode fixture|live --env-file PATH --source-pack PATH --evidence-dir PATH` 使用从第一轮提取的同一 gate_runtime 生命周期，管理隔离 Compose 栈、Studio/API、browser driver 和清理，不能复制另一套产品写入路径。fixture 可使用固定测试决定；live 禁用 fixture 并等待人工身份审核，人工内容核对期间保留受控会话。单独 browser 命令只用于仍在运行的栈；UI gate 接入当前 Chronicle workflow，真实 provider 验收另记录内容证据。T16 的 reading-acceptance.md 是实施后的唯一运行说明。
