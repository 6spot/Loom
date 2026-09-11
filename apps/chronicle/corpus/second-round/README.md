# C2-R2-T02 第二轮阅读样例与组件浏览器基座

任务：C2-R2-T02（Issue #571），父任务 C2-R2（Issue #549）。状态：实现中，待交付 PR 与默認分支對賬。

本目錄只準備**可核對的閱讀場景材料**與**獨立組件瀏覽器基座**：

- 真實定位點從第一輪已凍結的兩部著作／四個完整自然章原文派生，不重新下載、不改寫原文；
- 閱讀期望字段遵循 [continuous-reading.md](../../docs/continuous-reading.md) 與
  [reading-experience.md](../../docs/reading-experience.md)；
- fixture/基座只演示 published DTO 形狀與受控響應，**不冒充真實後端、不冒充 0.2 模型結果**；
- 組件 suite 由後續任務（T10–T14）各自新增 scene/spec，本基座只負責發現、註冊與顯式失敗。

## 凍結原件（沿用第一輪，不重新生成）

| key | 著作／章 | 文件 | SHA-256（原始字節） | 字符 |
| --- | --- | --- | --- | ---: |
| `xianzhu-liubei` | 三國志·蜀書·先主傳 | `../first-round/sources/sanguozhi-032-xianzhu-liubei.txt` | `ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8` | 12572 |
| `zhou-yu` | 三國志·吳書·周瑜傳 | `../first-round/sources/sanguozhi-054-zhou-yu.txt` | `63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e` | 5018 |
| `lu-su` | 三國志·吳書·魯肅傳 | `../first-round/sources/sanguozhi-054-lu-su.txt` | `1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d` | 3583 |
| `zztj-065` | 資治通鑑·卷第六十五（漢紀五十七，建安十一年至十三年） | `../first-round/sources/zizhi-tongjian-065-quan.txt` | `c7f80c6baff73a0caa0bbf365117b9ae91892da590ab3830392deb9bcb46fd38` | 10680 |

固定版本、下載字節與規範化規則見第一輪 `../first-round/README.md`；本輪只讀取，
不新增來源、不搬移、不改第一輪語料或源文件。

## 文件一覽

- `reading-cases.json`：15 個真實閱讀核對點（`R2C01`–`R2C15`）＋3 個明確 `synthetic=true`
  的負例（`R2N01`–`R2N03`）。每個真實 ref 記錄 `source_key`/`file`/`quote`/
  `occurrence`/`start`/`end`，以 code point 計、與凍結原文 `[start,end)` 逐字對齊。
- `reading-walkthrough.md`：桌面／窄屏閱讀走查，說明正文順序、時間區段、當前人物地點、
  事件預覽／跳轉／返回，並標明回溯不改當前時間、跨來源切換與返回、注文不當正文。

## 核對規則

`reading-cases.json` 的 `rule` 字段是權威聲明，要點：

- `synthetic=true` 的條目**不得**作為史料發現引用；每個人造場景都帶 `synthetic` 標籤，
  其 `negative_probe` 或 `expected_reading_behavior` 說明要拒絕的行為。
- 每個真實 ref 的 `quote` 必須恰好出現在 `[start,end)`，且為文件中第 `occurrence` 次出現
  （occurrence 從 1 起），確保定位點可重定位、可重算。
- 閱讀期望不是「已實現」聲明；真實主敘事／回溯判斷仍由 T17 內容驗收獨立核對。

## 可重複檢查

```bash
# 結構合法
python3 -m json.tool apps/chronicle/corpus/second-round/reading-cases.json > /dev/null

# 逐 ref 重定位：quote 必須在 [start,end) 且為第 occurrence 次出現
python3 - <<'PY'
import json
base = "apps/chronicle/corpus/first-round"
d = json.load(open("apps/chronicle/corpus/second-round/reading-cases.json", encoding="utf-8"))
for case in d["cases"]:
    for r in case.get("refs", []):
        t = open(f"{base}/{r['file']}", encoding="utf-8").read()
        assert t[r["start"]:r["end"]] == r["quote"], (case["id"], r)
        idx = -1
        for _ in range(r["occurrence"]):
            idx = t.find(r["quote"], idx + 1)
        assert idx == r["start"], (case["id"], r)
print("reading-cases: relocatable", d["real_case_count"], "real +", d["synthetic_case_count"], "synthetic")
PY
```

## 組件瀏覽器基座

- fixture 頁面：`apps/chronicle/webapp/tests/fixtures/reading/index.html`（入口 `main.tsx`）。
- 受控場景註冊：`tests/fixtures/reading/cases/*/scene.tsx`；主 harness 用
  `import.meta.glob` 發現，各組件作者只加自己的目錄。
- 統一 driver：`apps/chronicle/webapp/scripts/reading-component-smoke.mjs`
  `--base-url <url> --suite harness|content|axis|position|events|context|all --output <dir>`。
- 主 harness：`tests/reading-browser/harness.mjs`；每個組件 suite 另加
  `tests/reading-browser/<suite>.mjs`。

約定：

- `--suite harness` 只驗基座本身（註冊發現、published DTO 形狀、受控失敗／遲到／空白、
  小尺寸佈局）。
- `--suite content|axis|position|events|context` 在對應 scene/spec 尚未提供時**顯式失敗**，
  不假 PASS；`--suite all` 只有五類組件場景都存在才成功。
- 基座不掛接生產 App/路由，不新增 package/lock，不寫 `apps/chronicle/web/dist`。

運行方法與已驗證結果見交付 PR；實施後的完整自動驗收由 T16/T17 提供。
