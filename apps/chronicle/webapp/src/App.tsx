import { Suspense, lazy, useEffect, useState } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate, useParams } from "react-router-dom";
import HistoricalTimeBar from "./components/HistoricalTimeBar";
import { StudioAuthProvider, useStudioAuth } from "./lib/studio-auth";
import { withHistoricalTime } from "./lib/historical-time";
import ChronicleIcon from "./components/ChronicleIcon";
import PublicDialog from "./components/PublicDialog";
import HomePage from "./pages/public/HomePage";
import { chapterPath, readingPath } from "./lib/routes";
import EntityPage from "./pages/public/EntityPage";
import EventPage from "./pages/public/EventPage";
import SearchPage from "./pages/public/SearchPage";
import TimelinePage from "./pages/public/TimelinePage";
import WorldPage from "./pages/public/WorldPage";
import ChapterIndexPage from "./pages/public/ChapterIndexPage";
import ChapterPage from "./pages/public/ChapterPage";
import ReadingIndexPage from "./pages/public/ReadingIndexPage";
import ReadingPage from "./pages/public/ReadingPage";
import { NotFoundState } from "./components/shared";
import "./styles/chronicle.css";
import "./styles/world.css";
import "./styles/studio.css";
import "./styles/review-evidence.css";
import "./styles/chapter-reader.css";
import "./styles/public-reading.css";

const StudioLayout = lazy(() => import("./pages/studio/StudioLayout"));
const StudioHomePage = lazy(() => import("./pages/studio/StudioHomePage"));
const StudioLoginPage = lazy(() => import("./pages/studio/StudioLoginPage"));
const StudioImportsPage = lazy(() => import("./pages/studio/StudioImportsPage"));
const StudioImportDetailPage = lazy(() => import("./pages/studio/StudioImportDetailPage"));
const StudioReviewPage = lazy(() => import("./pages/studio/StudioReviewPage"));
const StudioReviewDetailPage = lazy(() => import("./pages/studio/StudioReviewDetailPage"));
const StudioSourcesPage = lazy(() => import("./pages/studio/StudioSourcesPage"));
const StudioCoveragePage = lazy(() => import("./pages/studio/StudioCoveragePage"));

function StudioGuard({ children }: { children: JSX.Element }) {
  const auth = useStudioAuth();
  const location = useLocation();
  if (!auth.username) return <Navigate to="/studio/login" replace state={{ from: location.pathname }} />;
  return children;
}

function PublicChrome({ children, timeBar = true }: { children: React.ReactNode; timeBar?: boolean }) {
  const navigate = useNavigate();
  const location = useLocation();
  const [tool, setTool] = useState<"search" | "menu" | null>(null);
  const reading = location.pathname.startsWith("/read/");
  useEffect(() => setTool(null), [location.pathname, location.search]);
  return (
    <div className={`public-site${reading ? " public-site-reading" : ""}`}>
      <a className="public-skip-link" href="#app">跳到正文</a>
      <header className="site-header">
        <Link className="brand" to="/" aria-label="Chronicle 首页">
          <span className="brand-mark" aria-hidden="true">纪</span>
          <span><strong>Chronicle</strong></span>
        </Link>
        <nav className="site-nav" aria-label="主要导航">
          <Link to="/" aria-current={location.pathname === "/" ? "page" : undefined}>探索</Link>
          <button className="public-icon-button" type="button" aria-label="搜索历史" onClick={() => setTool("search")}><ChronicleIcon name="search" /></button>
          <button className="public-icon-button" type="button" aria-label="更多导航" onClick={() => setTool("menu")}><ChronicleIcon name="more" /></button>
        </nav>
      </header>
      {timeBar ? <HistoricalTimeBar /> : null}
      <main id="app" className="app-shell" tabIndex={-1}>{children}</main>
      {tool === "search" ? <PublicDialog title="寻找一段历史" onClose={() => setTool(null)} compact>
        <form
          className="history-search"
          action="/search"
          method="get"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            const query = String(form.get("q") ?? "").trim();
            if (query) {
              setTool(null);
              navigate(withHistoricalTime(`/search?q=${encodeURIComponent(query)}`, location.search));
            }
          }}
        >
          <label className="public-sr-only" htmlFor="global-search-q">搜索人物、地点或事件</label>
          <input id="global-search-q" name="q" autoComplete="off" placeholder="时期、事件、人物或地点" autoFocus />
          <button className="public-icon-button" type="submit" aria-label="搜索"><ChronicleIcon name="search" /></button>
        </form>
      </PublicDialog> : null}
      {tool === "menu" ? <PublicDialog title="探索与资料" onClose={() => setTool(null)} compact>
        <nav className="public-menu" aria-label="更多导航">
          <Link to="/timeline">历史时刻</Link>
          <Link to="/read">已收录正文</Link>
          <Link to="/chapters">史料原文</Link>
          <Link to="/studio">内容管理</Link>
        </nav>
      </PublicDialog> : null}
    </div>
  );
}

function StudioFallback() {
  return <div className="studio-shell" data-view="studio-loading"><p className="studio-muted">正在加载 Studio…</p></div>;
}

function ChapterIndexRoute() {
  const navigate = useNavigate();
  return (
    <ChapterIndexPage
      hrefForPublicationId={(publicationId) => chapterPath(publicationId)}
      onSelectChapter={(publicationId) => navigate(chapterPath(publicationId))}
    />
  );
}

function ChapterDetailRoute() {
  const { publicationId } = useParams();
  if (!publicationId) return <NotFoundState />;
  return <ChapterPage key={publicationId} publicationId={publicationId} />;
}

function ReadingIndexRoute() {
  const navigate = useNavigate();
  return (
    <ReadingIndexPage
      onSelectStream={(item, catalog) => navigate(readingPath(item.stream_id, catalog))}
      hrefForStream={(streamId, catalog) => readingPath(streamId, catalog)}
    />
  );
}

function ReadingDetailRoute() {
  const { streamId } = useParams();
  if (!streamId) return <NotFoundState />;
  return <ReadingPage key={streamId} streamId={streamId} />;
}

export default function App() {
  return (
    <StudioAuthProvider>
      <Routes>
        <Route path="/studio/login" element={<Suspense fallback={<StudioFallback />}><StudioLoginPage /></Suspense>} />
        <Route path="/studio/*" element={<Suspense fallback={<StudioFallback />}><StudioLayout /></Suspense>}>
          <Route index element={<StudioGuard><Suspense fallback={<StudioFallback />}><StudioHomePage /></Suspense></StudioGuard>} />
          <Route path="imports" element={<StudioGuard><Suspense fallback={<StudioFallback />}><StudioImportsPage /></Suspense></StudioGuard>} />
          <Route path="imports/:jobId" element={<StudioGuard><Suspense fallback={<StudioFallback />}><StudioImportDetailPage /></Suspense></StudioGuard>} />
          <Route path="review" element={<StudioGuard><Suspense fallback={<StudioFallback />}><StudioReviewPage /></Suspense></StudioGuard>} />
          <Route path="review/:reviewId" element={<StudioGuard><Suspense fallback={<StudioFallback />}><StudioReviewDetailPage /></Suspense></StudioGuard>} />
          <Route path="sources" element={<StudioGuard><Suspense fallback={<StudioFallback />}><StudioSourcesPage /></Suspense></StudioGuard>} />
          <Route path="coverage" element={<StudioGuard><Suspense fallback={<StudioFallback />}><StudioCoveragePage /></Suspense></StudioGuard>} />
        </Route>
        <Route path="/" element={<PublicChrome timeBar={false}><HomePage /></PublicChrome>} />
        <Route path="/world" element={<PublicChrome><WorldPage /></PublicChrome>} />
        <Route path="/timeline" element={<PublicChrome><TimelinePage /></PublicChrome>} />
        <Route path="/search" element={<PublicChrome><SearchPage /></PublicChrome>} />
        <Route path="/events/:id" element={<PublicChrome><EventPage /></PublicChrome>} />
        <Route path="/entities/:id" element={<PublicChrome><EntityPage /></PublicChrome>} />
        <Route path="/chapters" element={<PublicChrome><ChapterIndexRoute /></PublicChrome>} />
        <Route path="/chapters/:publicationId" element={<PublicChrome><ChapterDetailRoute /></PublicChrome>} />
        <Route path="/read" element={<PublicChrome timeBar={false}><ReadingIndexRoute /></PublicChrome>} />
        <Route path="/read/:streamId" element={<PublicChrome timeBar={false}><ReadingDetailRoute /></PublicChrome>} />
        <Route path="*" element={<PublicChrome><NotFoundState /></PublicChrome>} />
      </Routes>
    </StudioAuthProvider>
  );
}
