// C2-R3-D02 交互状态矩阵（仅测试使用）。
//
// 每条矩阵行都必须在 harness DOM 中有一个带 `data-state` 的元素，浏览器 spec
// 逐条断言；缺失即失败，避免“设计了但没实现”。

export interface MatrixRow {
  readonly state: string;
  readonly label: string;
  /** 契约要求的确定呈现。 */
  readonly presentation: string;
}

export const INTERACTION_MATRIX: readonly MatrixRow[] = [
  { state: "clear", label: "明確", presentation: "實心 ●＋「明確」可訪問名稱、正常墨色、可點依據" },
  { state: "uncertain", label: "不明確", presentation: "空心 ○＋「存疑」、灰墨色、非 disabled、原因可查" },
  { state: "no-record", label: "暫無記載", presentation: "顯示「暫無記載」，不生成虛構候選身份" },
  { state: "stage-unknown", label: "階段未明確", presentation: "顯示「階段未明確」材料，不當作此前任職或當前身份" },
  { state: "loading", label: "載入中", presentation: "顯式載入狀態，不用上一段身份冒充當前段" },
  { state: "load-error", label: "載入失敗", presentation: "顯式錯誤＋重試，已讀正文保留，不偽造狀態" },
  { state: "concurrent", label: "兼任", presentation: "多項並列，不壓成最高官職" },
  { state: "process", label: "多階段過程", presentation: "保留全過程並標明階段順序" },
  { state: "ambiguous", label: "多解釋", presentation: "分別呈現材料，不壓成唯一標籤" },
  { state: "disagreement", label: "來源分歧", presentation: "保留雙方歸屬與各自主張，不取勝者" },
  { state: "partial-clarity", label: "同人部分明確", presentation: "同人不同項一明一暗，不整體標暗" },
  { state: "empty", label: "空段", presentation: "明確「本段還沒有關聯人物或地點」，不清空正文" },
];

export const D02_TASK = "C2-R3-D02";
