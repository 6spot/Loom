# Chronicle 历史背景图：人工制作、保存与展示

状态：产品设计、后端素材/关联基础设施、Studio 候选管理/人工保存界面、阅读页的已保存关联读取/渲染，以及 C3-T17 的位置切换、相邻预加载、阅读开关和迟到图丢弃已实现；完整真实资料内容质量验收仍按任务单执行。[D01/#588](https://github.com/6spot/Loom/issues/588) 交付的可复用技能与离线候选归档工具仍与生产素材库分离。本文件不改变既有古文文本上传接口或阅读产物 schema。

## 1. 用户确认的流程

**AI 建议配图位置 → 用户明确触发生成，或上传已有图 → 预览、校验与调整 → 用户“保存并显示” → 阅读到已关联位置时展示背景。**

图片仅是页面背景。正文保持原有文本与引用，不插入图片段落。AI 可以建议“这里适合配图”、给出理由、题材与提示词，但建议本身不会触发图像生成，也不会让图片出现在读者页面。

用户可在自己的技能环境中生成图片，保留到候选素材库，再通过 Studio 上传所选文件。已有图片同样进入预览流程。未来即使 Studio 提供“生成候选”按钮，也必须由操作者明确触发；滚动、阅读 GET、导入、翻译/抽取、发布章节和后台缺图检查均不触发生成。

生成或上传后，图片首先是候选。工具保留候选文件便于预览和复用，不代表用户已确认展示。用户针对具体版本、位置和效果点击一次“保存并显示”，系统成功保存后该背景才可公开读取。取消、暂不保存、失败或未检查的候选都不可出现在阅读页。一般性的“支持 AI 图片”指示不等于对以后每张图的生成或保存授权。

## 2. Studio 交互目标

从阅读片段或素材库进入“设置背景”，保留原阅读位置。在一个工作面板里完成：

1. **选择位置**：显示历史时期、附近事件、相关正文和起止范围，可从已有事件/主要人物关联辅助选择。AI 推荐只预填待确认建议，不静默形成绑定。
2. **选择图片**：上传本地文件、选择已有素材，或明确点击“生成候选”。显示候选来源、时代与实际提示词；重复生成仍需人工触发。
3. **预览背景**：同时看到正文和背景，调整浓淡、主体位置与遮罩，检查桌面/窄屏效果；可以直接回到纯纸色作比较。
4. **保存并显示**：确认素材版本、关联范围与渲染设置。在成功前维持已有背景；失败保留候选和错误，不能出现“文件传完即启用”的中间状态。

单纯选择素材库里的图片，也不会立刻更改所有同名事件/人物的背景。用户保存的是明确的使用位置。一张图片可以被多个位置复用，各处关联独立；替换原图、生成新候选或添加新版本均不自动改动现有绑定。停用一个背景关联不会删除其他位置还在使用的图片。

## 3. 素材、版本与位置分别保存

| 记录 | 含义与展示权限 |
| --- | --- |
| 配图建议 | 位置、理由、题材、时代、提示词；可以没有图片，不可展示 |
| 候选素材 | 实际图像、来源、提示词、校验值和制作信息；可预览、查找，不可作为已启用背景公开读取 |
| 人工保存的关联 | 明确素材版本、阅读位置/范围、构图与浓淡设置、确认记录；是读者背景展示的依据 |

生产的“保存并显示”需要在唯一的 Chronicle 应用写入路径中，校验文件已完整可读、图片版本和目标存在、操作者有权保存，再原子地提交关联。保存失败不部分启用。图片标识及文件路径由服务端生成；不能让模型生成 URL、相对文件名或人物名字决定展示身份。

图片的版本和使用关联独立于不可变正文 publication，不回写翻译、古文锚点或 canonical 人物/事件等价。主阅读关联固定综合历史的 `{version, paragraph_id}` 起止范围，不把来源 stream/unit 坐标冒充综合正文位置。全局版本扩展后按其发布映射校验；具体存储和接口由产品任务写入本合同。新正文版本不静默继承旧段落坐标，须重新确认适用范围。

读取的是当前被人工启用的素材版本和关联。替换时，已有会话如何固定背景版本由实现合同进一步确定；无论采用何种刷新策略，都不能越过人工保存边界。无关联、已停用、素材不存在或加载失败时回到纯纸色，不能自动生成、借用另一张图或把上一事件的背景一直留到无关正文。

## 4. 后端格式与 HTTP 合同

后端素材库由 Chronicle 自己的 PostgreSQL schema 和持久文件目录共同组成。它不读取 Runtime、World、Timeline、Work 或 Loom Binding authority，也不调用图像模型。

### 4.1 素材候选与版本

- `POST /api/v1/studio/background-assets?filename=...&source=...&era=...&prompt=...&metadata=<JSON>` 接收原始 PNG、JPEG 或 WebP 请求体；如提供 `Content-Type` 或文件名，二者必须与实际解码格式一致。上传只创建候选，不创建公开关联。
- `POST /api/v1/studio/background-assets/{asset_id}/versions?filename=...` 可向同一候选素材追加一个新的不可变图片版本；已有 binding 仍固定原来明确保存的 `asset_version_id`，不会因追加版本自动切换。
- 服务端为素材和版本生成 UUIDv7，并记录 SHA-256、实际格式、媒体类型、字节数、宽高、来源、时代、实际 prompt 和 JSON metadata。第一版单文件上限为 8 MiB、像素上限为 40,000,000；部署可用 `CHRONICLE_BACKGROUND_MAX_UPLOAD_BYTES` 进一步降低字节上限，不能提高 8 MiB 上限。
- 服务端使用 Pillow 对编码流执行实际格式识别、`verify` 和完整像素解码；SVG、HTML、伪 MIME、截断数据、路径穿越文件名和超限图片都会失败。文本古文的 `documents`/revision API 保持原合同，不接受图片。
- 候选只能经 `GET /api/v1/studio/background-assets` 查询，通过 `GET /api/v1/studio/background-assets/{asset_id}/preview`（或 `/content`）预览。上述 Studio 路由由 Rust 的 Basic Auth 边界保护。

### 4.2 保存、替换与停用

`POST /api/v1/studio/background-bindings` 使用 JSON 保存明确关联：

```json
{
  "edition_version": "<published SHA-256>",
  "start_paragraph_id": "hp_<24 hex>",
  "end_paragraph_id": "hp_<24 hex>",
  "asset_id": "<UUIDv7>",
  "asset_version_id": "<UUIDv7>",
  "display": {
    "opacity": 0.35,
    "position": {"x": 0.5, "y": 0.5},
    "scale": 1.0,
    "mask": null
  },
  "actor": "studio-admin"
}
```

保存只接受已发布的精确历史 edition、属于该 edition 的起止段落和文件完整性校验通过的素材版本；起止范围按综合正文段落序号闭区间保存，同一 edition 的 active 范围不能重叠。`opacity` 为 0–1、`scale` 为 0.1–4、位置坐标为 0–1，mask 只允许受控的边缘值与 `rect`/`gradient` 形状。

变更必须显式调用 `POST /api/v1/studio/background-bindings/{binding_id}/replace`，停用可调用 `POST .../disable` 或 `DELETE .../{binding_id}`；`GET .../{binding_id}/audit` 返回 created/replaced/disabled 审计记录。响应包含 `revision` 与 `etag`，替换/停用可用 `expected_revision` 或 `expected_etag` 做并发保护。一张素材可以被多个位置复用，停用一个关联不会删除素材或其他关联；新 edition 不继承旧段落坐标。

文件先以服务端生成的相对 storage key 原子写入，再在同一保存边界注册数据库记录；注册失败会清理新文件。绑定保存前后均会再次验证文件大小、hash 和完整解码，避免数据库记录或公开资源指向半成品。

### 4.3 公开读取边界

Rust 对外提供匿名 GET `/api/v1/public/backgrounds?version=<edition>&paragraph_id=<paragraph>` 返回当前 active 关联的 metadata/display；图片字节通过 `/api/v1/public/background-assets/{asset_id}?version=<edition>&paragraph_id=<paragraph>` 或 `/api/v1/public/background-resources/{binding_id}?version=<edition>&paragraph_id=<paragraph>` 读取。Python sidecar 内部对应 `/v0/backgrounds`、`/v0/background-assets` 和 `/v0/background-resources`，不会直接把 `/v0` 暴露给公共入口。

公开图片读取必须同时命中当前 active binding、精确 edition/paragraph（资源 id 也必须与该关联匹配）并通过文件完整性校验。未保存候选、停用关联、错误 edition/段落或猜测的 asset/binding ID 都返回 404；ID 不映射为可猜的文件系统路径。阅读层拿到的 `display`/revision/etag 应直接使用返回配置，缺图时回退纸底，不自动生成或借用其他图片。

## 5. 存放、备份和调阅

- 可复用技能：仓库 [.agents/skills/historical-background-art](../../../.agents/skills/historical-background-art/SKILL.md)，支持其他项目自己的图库路径。
- 开发候选素材：[assets/backgrounds](../assets/backgrounds/README.md)。保留原图、实际提示词、元数据和 hash；由技能工具 archive/list/show/verify 管理，不是 HTTP 上传或启用接口。
- 生产图片：使用 Chronicle 应用自有的持久素材存储和产品元数据，通过受鉴权的 Studio 上传、预览、保存及管理。默认目录是 `CHRONICLE_SOURCE_DIR/background-assets`，也可用 `CHRONICLE_BACKGROUND_DIR` 指定；原件、素材版本和关联都应可备份、重启后可取回。
- Compose 默认把该目录放在 `${CHRONICLE_DATA_DIR}/sources/background-assets`，由 `chronicle-source-init` 与 source 文件一起准备权限。备份必须同时覆盖 PostgreSQL（素材 metadata、binding、audit）和该目录的图片文件；只备份其中一侧不能恢复可读背景。
- 技能的生成输出必须复制到选定图库；生产界面不能引用开发机绝对路径、工具临时目录或扫描仓库目录推断是否已保存。

现有 [documents.md](documents.md) 只允许 UTF-8 `.txt/.md` 古文原料，不扩成图片接口。背景图片使用本节独立的 `background-assets` API、格式/尺寸/体积限制、实际解码校验和受控读取；不能复用文本 revision API 或混入史料内容生产链。

## 6. 时代、颜色和阅读层次

保留现代书卷感。页面基础色与图像题材色分别设计：

| 层 | 设计起点 |
| --- | --- |
| 纸底 | 沿用 `--paper: #F5F1E8`，必要时使用 `--paper-strong: #FFFDF8` 形成正文遮罩 |
| 正文与操作 | 沿用墨色 `#1F2528`、辅助灰 `#667074`、主操作朱红 `#7D2F2F`；不随事件换一套按钮颜色 |
| 古代图像 | 淡彩水墨/设色可以使用青灰、墨灰、灰绿、赭黄、少量灰朱红；不限定纯黑白 |
| 民国图像 | 根据城市与具体年代选择旧书刊、水彩、石印或版画语言；用暖灰、褪色靛蓝、米黄、灰红等建立层次 |
| 现代及其他地域 | 选择相符的现代插画、纪实题材绘画或当地视觉语言；不把古装、宣纸和中国历史分期套到所有背景 |

一幅图建议一主色、一辅助色和少量暖色点缀。正文中央维持大面积低细节留白，人物面部、舟船、建筑主要分布在页边空白。原图保留层次，页面通过遮罩/透明度控制干扰；可从页边 10%–18%、正文覆盖区更淡的效果开始试验，但最终以实际叠加后的可读性决定，不凭单一透明度数字验收。

赤壁可采用青灰江面、远处船阵和少量赭红火光。民国和现代应重新选择适当媒介及时代细节。人物意象图不当作真实肖像；生成的摄影感图片不冒充档案照片。图像来源和性质在素材详情可查，不把制作术语铺满默认阅读界面。

## 7. 随阅读显示

消费 [reading-experience.md](reading-experience.md) 的同一 active unit。人工关联可以覆盖一段连续叙事，范围内保持同图；跨入另一已确认范围才切换。正文回忆过去事件、悬停事件词、打开引用或移动鼠标不改背景。多个位置重叠的处理应在保存前让操作者看清并解决，不能临时由模型决定优先级。

背景改变只影响视觉层，不修改叙事时间、人物身份或阅读 URL。图片不占正文高度、不挡点击，不能造成布局跳动；切换可用约 160–240ms 的透明度淡入淡出，reduced-motion 直接切换。正文与控件按实际叠加效果满足 WCAG AA，对背景关闭和失败状态同样检查。提供关闭背景的阅读设置，窄屏保留文字优先的安全区。

预加载只针对当前及相邻的已保存背景，加载失败不清空正文、不请求生成，也不无限重试。一次读取不会为全书生成或下载所有图片。

## 8. 后续任务与验收边界

技能与离线库由 D01 交付。以下产品工作按[产品收敛任务](../../../docs/tasks/chronicle/product-convergence/README.md)拆分，不能以 D01 完成宣称已具备：

1. 阅读背景组件、已保存关联读取、单一阅读 controller 接线与无图回退。T16 已交付按精确 `{version, paragraph_id}` 读取 active binding、按保存 display 渲染独立背景层和缺图/停用/错误回退纸底；T17 补齐了由同一 active position 驱动的当前/相邻预加载、阅读设置开关、迟到图丢弃和 reduced-motion 切换行为。
2. 无自动生成、未保存不可见、确认后仅指定位置可见、失败/替换/停用/重启/跨 revision/窄屏/无障碍验收。

原第二轮 T01–T17 的生产任务保持其现有范围；背景产品链路需要独立交付与真实阅读验收。任务状态由现用管理工具维护，不要求默认分支 Task Ledger 对账。
