// C2-R3-D02 人物階段資料交互 harness 入口（僅測試使用，不進生產構建）。
//
// 由 Vite 直接提供 `tests/fixtures/reading/scenes/person-state-harness/index.html`。
// 三個場景固定 D02 交付的交互：閱讀頁、章階段依據審核、獨立人物頁。
// T01 之後在共享 browser runner 註冊，不改本文件定義的場景名稱與選擇方式。

import { createRoot } from "react-dom/client";
import EntityHarness from "./EntityHarness";
import ReadingHarness from "./ReadingHarness";
import ReviewHarness from "./ReviewHarness";
import { D02_TASK, INTERACTION_MATRIX } from "./matrix";

export const SCENE_NAMES = ["reading", "review", "entity"] as const;
export type SceneName = (typeof SCENE_NAMES)[number];

export const SCENES: Readonly<Record<SceneName, { label: string; element: JSX.Element }>> = {
  reading: { label: "閱讀頁：緊湊狀態、人物詳情、依據與回焦、四種寬度", element: <ReadingHarness /> },
  review: { label: "章階段依據包審核：按人物變化、批量與例外、保存並下一項", element: <ReviewHarness /> },
  entity: { label: "獨立人物頁三欄：概況定位／經歷時間軸／當前階段狀態", element: <EntityHarness /> },
};

(window as unknown as { __PERSON_STATE_HARNESS__: unknown }).__PERSON_STATE_HARNESS__ = {
  fixture: "person-state-harness",
  builtFor: D02_TASK,
  synthetic: true,
  scenes: SCENE_NAMES.map((name) => ({ name, label: SCENES[name].label })),
  matrix: INTERACTION_MATRIX.map((row) => row.state),
};

function Index() {
  return (
    <main className="public-site" data-test="person-state-index">
      <h1>人物階段資料交互 harness（僅測試）</h1>
      <p>合成場景，不冒充真實史料或已發布內容。用 ?case=reading|review|entity 開啟場景。</p>
      <ul>
        {SCENE_NAMES.map((name) => (
          <li key={name}>
            <a href={`?case=${name}`}>{SCENES[name].label}</a>
          </li>
        ))}
      </ul>
      <table data-test="person-state-matrix-table">
        <thead>
          <tr>
            <th>狀態</th>
            <th>確定呈現</th>
          </tr>
        </thead>
        <tbody>
          {INTERACTION_MATRIX.map((row) => (
            <tr data-test="person-state-matrix-row" data-state={row.state} key={row.state}>
              <td>{row.label}</td>
              <td>{row.presentation}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </main>
  );
}

const params = new URLSearchParams(window.location.search);
const requested = params.get("case");
const root = createRoot(document.getElementById("root")!);

if (!requested) {
  root.render(<Index />);
} else if ((SCENE_NAMES as readonly string[]).includes(requested)) {
  root.render(SCENES[requested as SceneName].element);
} else {
  root.render(<main data-test="person-state-scene-missing">沒有該場景：{requested}（顯式失敗，不靜默回退）</main>);
}
