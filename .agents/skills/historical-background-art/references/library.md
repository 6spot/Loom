# 候选素材库

`scripts/library.py` 使用 Python 标准库，负责本地归档、检索和完整性检查。它不生成图片、不发送请求、不写数据库，也没有“启用/发布”命令。

所有归档记录固定为 `draft`。候选文件的可见范围取决于所在仓库/目录的权限；生产应用不能把这个目录当作公开素材目录或扫描它自动启用图片。产品中的“保存并显示”必须由人对具体图片和位置触发。

## 目录和身份

```text
<library>/
  drafts/bg_<content-id>/
    image.png | image.jpg | image.webp
    prompt.txt
    brief.json
    manifest.json
```

素材 ID 由原图、完整提示词和规范化 brief 的组合 hash 派生。相同组合重复归档返回已有候选；任何图像/提示词/brief 改动形成新候选。原始图像字节保留，不原地裁剪、重编码或覆盖。`derived_from` 可记录已有候选 ID；该关系用于素材复用，不创造历史实体等价。

manifest 记录 UTC 创建时间、`draft` 状态、文件名、字节数和 SHA-256。精确复用时使用素材 ID 与 hash，不靠文件名、题材名称或“最新一张”替换已启用图。

## 元数据

复制 [brief.json](../assets/brief.json) 并填入实际内容。该文件只是示例，不代表已经生成了赤壁图。

| 字段 | 要求 |
| --- | --- |
| title | 可读名称 |
| subject | kind 为 event/person/place/period/theme；name 是题材名称，不是确认的产品绑定 |
| era / region | 自由文本，按史料精度填写；支持任意时代和地区 |
| style / palette | 实际画风与 1–8 个 HEX 色值 |
| composition | 画幅、主体位置、文字安全区及必要的移动端说明 |
| origin | kind 为 generated/uploaded；tool/model 如实记录，未知用 null；source 记录已知来源，rights 记录实际授权或来源说明 |
| tags | 检索标签 |
| proposed_placement | 配图位置建议；不会被工具转换成已启用绑定 |
| derived_from | 选填的已有候选 ID，用于记录衍生关系 |

生成图必须附实际完整提示词。上传已有图时可以没有提示词，工具会明确记录“未提供”，不伪造生成历史。不要在 brief 或 prompt 中保存 API key、凭据或无权提交的参考资料。

## 命令

以下命令在 Loom 仓库根运行；其他项目替换脚本和 `--library` 路径。

```bash
# 仅在已经有真实候选图后归档；先把模板改成该图的实际元数据。
python3 .agents/skills/historical-background-art/scripts/library.py \
  --library apps/chronicle/assets/backgrounds archive \
  --image /absolute/path/candidate.png \
  --brief /absolute/path/brief.json \
  --prompt /absolute/path/final-prompt.txt

# 上传来源的 brief.origin.kind 填 uploaded；确实没有提示词时可省略 --prompt。
python3 .agents/skills/historical-background-art/scripts/library.py \
  --library apps/chronicle/assets/backgrounds list --query 赤壁

python3 .agents/skills/historical-background-art/scripts/library.py \
  --library apps/chronicle/assets/backgrounds list --era 民国 --kind place

python3 .agents/skills/historical-background-art/scripts/library.py \
  --library apps/chronicle/assets/backgrounds show bg_<实际素材ID>

python3 .agents/skills/historical-background-art/scripts/library.py \
  --library apps/chronicle/assets/backgrounds verify
```

`list` 返回题材、时代、画风及原图路径；`show` 先校验归档完整性再返回清单、brief 和准确路径。拿到路径后用图像查看工具打开原图。`verify` 检查全库，损坏时非零退出，不静默修复。归档不支持 GIF/SVG；仅以签名识别 PNG/JPEG/WebP，不承担未来 HTTP 上传服务的完整解码、尺寸和资源消耗验证。

生成失败时没有真实图就不建素材记录；归档失败可以重试同一组合。候选文件使用临时目录完成写入后再一次移入 `drafts`，读者不会看到半份清单。
