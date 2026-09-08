# C2-R1-T02 第一輪驗收語料（兩部著作，四個完整自然章）

任務：C2-R1-T02（Issue #552）。狀態：實現中，待交付 PR 與默認分支對賬。
本文只記錄選擇、邊界與可重複操作，不複製章節/審核契約規範。

## 凍結版本（不再留待選篇目）

| # | 著作 / 章 | 來源頁與固定版本 | 下載字節 / 規範化字符 | SHA-256（原始字節） | normalized_sha256（`decode_source` 規範化後） |
| --- | --- | --- | ---: | --- | --- |
| 1 | 三國志·蜀書·先主傳 | `三國志/卷32` oldid `2583378`，`section=先主 劉備` | 37474 / 12572 | `ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8` | `ea40a7087560fe9e693e6f81cb7d1689704f888a40b5b8a8bf7169ec272994e8` |
| 2 | 三國志·吳書·周瑜傳 | `三國志/卷54` oldid `2387393`，`section=周瑜` | 14996 / 5018 | `63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e` | `63db082c4e763be3b56c87cb56e2bed904af5325e9a498b07d932d3b5af1f43e` |
| 3 | 三國志·吳書·魯肅傳 | `三國志/卷54` oldid `2387393`，`section=魯肅` | 10715 / 3583 | `1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d` | `1550e1735f44eda7adb9bf27f4ed2cbc9c2185baf6634400140cd52ac312553d` |
| 4 | 資治通鑑·卷第六十五（漢紀五十七，建安十一年至十三年） | `資治通鑑/卷065` oldid `2306420`，整頁全文 | 31786 / 10680 | `c7f80c6baff73a0caa0bbf365117b9ae91892da590ab3830392deb9bcb46fd38` | `c7f80c6baff73a0caa0bbf365117b9ae91892da590ab3830392deb9bcb46fd38` |

規範化規則與 `apps/chronicle/persistence/documents.py::decode_source`
一致（嚴格 UTF-8、去單個 BOM、CRLF/CR→LF；`normalized_sha256` 為規範化文本
UTF-8 編碼的 SHA-256，字符數為 `chars-normalized-utf8`）。本批四份原文均為
無 BOM 的 LF 文本，故規範化 hash 與原始 hash 相同——此為核驗結論而非省略
記錄的理由，四份 hash 均已記入 `sources/prepared.json`、
`ingest-manifest.json` 與 `scale-report.json` 並由測試重算校驗。

- 前三章與 `c1-t13` 提交的固定 oldid 文本逐字節一致（上表 SHA 與
  `c1-t13/sources/prepared.json` 相同），未重新生成不同版本，也未把三章當三部著作。
- 第四章為任務首選的卷六十五全文：覆蓋建安十三年與赤壁之戰的編年體對照。
  整卷 10680 字符 ≤ 32768 上限，**無需相鄰卷替換**，此即凍結結論與替換理由
  （首選即合規，故無替換）。
- 永久鏈格式：`https://zh.wikisource.org/w/index.php?title=<page>&oldid=<oldid>`
  （見 `sources/prepared.json` 每條 `source_label`）。底層史著為公有領域；
  Wikisource 站點文本按 CC BY-SA 署名，`source-pack.json` 登記了授權說明。

## 文件一覽

- `source-pack.json`：4 條來源清單（3 條 `section` 復用＋1 條 `full_page`），
  `transform_version=mediawiki-text-v0.2`（section 邏輯與 v0.1 一致，新增整頁
  模式見下）。
- `sources/`：4 份固定原文（tracked）＋ `prepared.json`（prepare 報告，
  含 `manifest_sha256=ff51bf140b1ce4aaa6ef8eb2184a2c2260481cf17257bfff048b62b5524db012`）。
- `ingest/sanguozhi-three-chapters.md`：`# 三國志` ＋ 3 個 `##` 章，
  21215 字符，`a5dc345f7163cc01632e443cad93fbb85015b8dd277713e56c722ddfa5236076`。
  單文件＝單 revision，三章共享同一 ingest SHA 作 revision 定位。
- `ingest/zizhi-tongjian-065.md`：`# 資治通鑑` ＋ 1 個 `##` 章，
  10715 字符，`b9831c28e64a067634fc9c6c8e2b06e38ff51e95ffbcfd0e4`。
- `ingest-manifest.json`：每章到原下載文件的精確內容 hash 與 `[start,end)`
  範圍（嵌入規則見 `build_ingest.py`）。
- `cases.json`：13 個真實核對點（T02-C01…C13）＋1 個合成負例（T02-N01，
  `synthetic=true`，零命中，禁作史料引用）。
- `scale-report.json`：逐文件/逐章字節與字符預算、容量裁決、拒收樣本記錄。
- `rejected/`：合成超限拒收樣本（非自然章，期望 reject）。
- `build_ingest.py`：由 `sources/` 可重複派生 `ingest/` 與
  `ingest-manifest.json`（無網絡、無模型）。

## 嵌注策略（正文及現存嵌注全部翻譯）

- 三國志三章的〈〉裴注（如〈《典略》曰…〉〈《江表傳》曰…〉謝承《後漢書》曰…）
  原樣保留在正文中；譯文保留「某書記載／裴松之按」歸屬，不把注中轉述改寫為
  正文斷言（核對點 T02-C08/C09）。
- 通鑑卷65的「習鑿齒論曰…」為後世史論，歸屬後世論者，不得當作建安十三年
  當事人同期言論（T02-C13）；卷中「馬超…尚在關西」僅背景提及，無直接
  Claim（T02-C10）。
- 通鑑卷首兩塊為固定版本原樣：Wikisource 卷題 `資治通鑑 第065卷`（站點題籤，
  非司馬光原典但屬固定版本一部分，予以保留並在此聲明）接原典紀首
  `【漢紀五十七】起柔兆閹茂，盡著雍困敦，凡三年。`；三年年號小標
  （建安十一年／十二年／十三年）作為正文塊保留。

## 字符預算（規範化字符，`chars-normalized-utf8`）

上限 32768 字符／章（工程上限，非正確率保證）。實測：先主傳 12572、
周瑜傳 5018、魯肅傳 3583、通鑑卷65 10680，三國志合併文件 21215——全部合規。
合成拒收樣本約 42k 字符，期望整體 reject（見 `scale-report.json`）。

## 可重複命令

```bash
# 固定版本重取（含整頁模式），應重現 sources/*.txt 與 prepared.json 的全部 hash
python3 apps/chronicle/corpus/source_pack.py prepare --manifest apps/chronicle/corpus/first-round/source-pack.json --output-dir /tmp/chronicle-first-round-reprepared

# 由 sources 可重複派生 ingest 兩文件與 ingest-manifest.json
python3 apps/chronicle/corpus/first-round/build_ingest.py

# 本任務驗收測試（離線，不觸網）
python3 -m unittest discover -s apps/chronicle/corpus -p 'test_first_round_pack.py' -v
```

未調用 ingest／模型，未重置任何數據環境；既有六篇原文仍在
`apps/chronicle/corpus/c1-t13` 原位，未搬移、未加入 ignore。

## 逐章審閱模板（供 T19 內容核對沿用）

每章逐項勾選並記錄原文位置（`sources/<file>[start:end)` 或 ingest 章範圍）：

- [ ] 首尾與嵌注完整（開篇句／結尾句定位，〈〉閉合，卷首題籤聲明已讀）。
- [ ] 指代與稱謂（操／曹公、瑜／公瑾、肅／子敬、先主／備，同章回指列舉）。
- [ ] 同名異人／異地（南郡 vs 江陵等保留 uncertain 的依據）。
- [ ] 人物無直接 Claim（僅背景提及者列出，不得造 Claim）。
- [ ] 事件原文、時間與角色（赤壁：遭遇／疾疫／火攻／追擊各句定位）。
- [ ] 前文主語／後文動作跨句承接。
- [ ] 跨章／跨書匹配（先主↔周瑜↔魯肅↔通鑑，卷65 對應句）。
- [ ] 無法確認項保留 uncertain（寫明缺失的證據，不合併身份）。
