// C2-R2-T02 阅读组件独立 fixture 入口（仅测试使用，不进生产构建）。
//
// 发现接口：main.tsx 用 import.meta.glob 受控发现 `cases/*/scene.tsx`。
// 各组件任务只新增自己的 `cases/<suite>/scene.tsx`，不改本文件。
// 注册结果挂到 window.__READING_HARNESS__，主 harness 据此判断 suite 是否存在，
// 缺失的组件 suite 必须显式失败，不能假 PASS。

import { createRoot } from "react-dom/client";
import { COMPONENT_SUITES, SUITE_NAMES, type ReadingScene, type SuiteName } from "./cases/types";

interface RegistryScene {
  suite: SuiteName;
  name: string;
  label: string;
  synthetic: boolean;
}

interface Registry {
  fixture: "reading";
  builtFor: "C2-R2-T02";
  suites: Record<SuiteName, { scenes: RegistryScene[] }>;
}

const modules = import.meta.glob("./cases/*/scene.tsx", { eager: true }) as Record<
  string,
  { default: ReadingScene | ReadingScene[] }
>;

const scenes: ReadingScene[] = [];
const seenNames = new Set<string>();
for (const [path, mod] of Object.entries(modules)) {
  const exported = mod.default;
  const list = Array.isArray(exported) ? exported : [exported];
  for (const scene of list) {
    if (!scene || !scene.suite || !scene.name) {
      throw new Error(`reading fixture: ${path} exported an invalid ReadingScene`);
    }
    const key = `${scene.suite}/${scene.name}`;
    if (seenNames.has(key)) {
      throw new Error(`reading fixture: duplicate scene ${key}`);
    }
    seenNames.add(key);
    scenes.push(scene);
  }
}

const registry: Registry = {
  fixture: "reading",
  builtFor: "C2-R2-T02",
  suites: Object.fromEntries(
    SUITE_NAMES.map((suite) => [
      suite,
      {
        scenes: scenes
          .filter((scene) => scene.suite === suite)
          .map((scene) => ({
            suite: scene.suite,
            name: scene.name,
            label: scene.label,
            synthetic: scene.synthetic,
          })),
      },
    ]),
  ) as Registry["suites"],
};

(window as unknown as { __READING_HARNESS__: Registry }).__READING_HARNESS__ = registry;

function RegistryIndex() {
  return (
    <main data-test="reading-registry">
      <h1>Chronicle 阅读组件 fixture 注册表</h1>
      <p data-test="reading-synthetic-note">仅测试使用；不是真实后端，也不是真实模型输出。</p>
      {SUITE_NAMES.map((suite) => (
        <section data-test="reading-registry-suite" data-suite={suite} key={suite}>
          <h2>
            {suite}
            {COMPONENT_SUITES.includes(suite) ? "（组件 suite）" : "（基座 suite）"}
          </h2>
          <ul>
            {registry.suites[suite].scenes.map((scene) => (
              <li data-test="reading-registry-scene" data-scene={`${suite}/${scene.name}`} key={scene.name}>
                <a href={`?case=${suite}/${scene.name}`}>{scene.label}</a>
              </li>
            ))}
            {registry.suites[suite].scenes.length === 0 ? (
              <li data-test="reading-registry-empty">尚未注册场景</li>
            ) : null}
          </ul>
        </section>
      ))}
    </main>
  );
}

const root = createRoot(document.getElementById("root")!);
const params = new URLSearchParams(window.location.search);
const requested = params.get("case");

if (!requested) {
  root.render(<RegistryIndex />);
} else {
  const scene = scenes.find((candidate) => `${candidate.suite}/${candidate.name}` === requested);
  if (!scene) {
    root.render(
      <main data-test="reading-scene-missing">没有该场景：{requested}（显式失败，不静默回退）</main>,
    );
  } else {
    root.render(scene.render(params));
  }
}
