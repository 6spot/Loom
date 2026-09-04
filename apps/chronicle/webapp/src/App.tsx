import { Suspense, lazy } from "react";
import { Link, Navigate, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { StudioAuthProvider, useStudioAuth } from "./lib/studio-auth";
import EntityPage from "./pages/public/EntityPage";
import EventPage from "./pages/public/EventPage";
import SearchPage from "./pages/public/SearchPage";
import TimelinePage from "./pages/public/TimelinePage";
import { NotFoundState } from "./components/shared";
import "./styles/chronicle.css";
import "./styles/studio.css";

// Studio code is route-split: public browsing never loads the admin
// component surface. Each Studio route chunk loads on first navigation.
const StudioLayout = lazy(() => import("./pages/studio/StudioLayout"));
const StudioHomePage = lazy(() => import("./pages/studio/StudioHomePage"));
const StudioLoginPage = lazy(() => import("./pages/studio/StudioLoginPage"));
const StudioImportsPage = lazy(() => import("./pages/studio/StudioImportsPage"));
const StudioImportDetailPage = lazy(() => import("./pages/studio/StudioImportDetailPage"));
const StudioReviewPage = lazy(() => import("./pages/studio/StudioReviewPage"));
const StudioReviewDetailPage = lazy(() => import("./pages/studio/StudioReviewDetailPage"));
const StudioSourcesPage = lazy(() => import("./pages/studio/StudioSourcesPage"));

function StudioGuard({ children }: { children: JSX.Element }) {
  const auth = useStudioAuth();
  const location = useLocation();
  if (!auth.username) return <Navigate to="/studio/login" replace state={{ from: location.pathname }} />;
  return children;
}

function PublicChrome({ children }: { children: React.ReactNode }) {
  const navigate = useNavigate();
  return (
    <>
      <header className="site-header">
        <Link className="brand" to="/timeline" aria-label="Chronicle 时间线首页">
          <span className="brand-mark" aria-hidden="true">
            纪
          </span>
          <span>
            <strong>Chronicle</strong>
            <small>source-grounded history</small>
          </span>
        </Link>
        <nav className="site-nav" aria-label="主要导航">
          <Link to="/timeline">时间线</Link>
          <Link to="/search">搜索</Link>
          <Link to="/studio">Studio</Link>
        </nav>
        <form
          className="global-search"
          action="/search"
          method="get"
          role="search"
          onSubmit={(event) => {
            event.preventDefault();
            const form = new FormData(event.currentTarget);
            navigate(`/search?q=${encodeURIComponent(String(form.get("q") ?? "").trim())}`);
          }}
        >
          <label htmlFor="global-search-q">搜索人物、地点或事件</label>
          <input id="global-search-q" name="q" autoComplete="off" placeholder="曹操、赤壁之战、江陵…" />
          <button className="primary-button" type="submit">
            搜索
          </button>
        </form>
      </header>
      <main id="app" className="app-shell" aria-live="polite">
        {children}
      </main>
      <footer className="site-footer">
        <p>Canonical identity 用于导航；史料原文、Claim、证据与不确定性保持独立可见。</p>
      </footer>
    </>
  );
}

function StudioFallback() {
  return (
    <div className="studio-shell" data-view="studio-loading">
      <p className="studio-muted">正在加载 Studio…</p>
    </div>
  );
}

export default function App() {
  return (
    <StudioAuthProvider>
      <Routes>
        <Route
          path="/studio/login"
          element={
            <Suspense fallback={<StudioFallback />}>
              <StudioLoginPage />
            </Suspense>
          }
        />
        <Route
          path="/studio/*"
          element={
            <Suspense fallback={<StudioFallback />}>
              <StudioLayout />
            </Suspense>
          }
        >
          <Route
            index
            element={
              <StudioGuard>
                <Suspense fallback={<StudioFallback />}>
                  <StudioHomePage />
                </Suspense>
              </StudioGuard>
            }
          />
          <Route
            path="imports"
            element={
              <StudioGuard>
                <Suspense fallback={<StudioFallback />}>
                  <StudioImportsPage />
                </Suspense>
              </StudioGuard>
            }
          />
          <Route
            path="imports/:jobId"
            element={
              <StudioGuard>
                <Suspense fallback={<StudioFallback />}>
                  <StudioImportDetailPage />
                </Suspense>
              </StudioGuard>
            }
          />
          <Route
            path="review"
            element={
              <StudioGuard>
                <Suspense fallback={<StudioFallback />}>
                  <StudioReviewPage />
                </Suspense>
              </StudioGuard>
            }
          />
          <Route
            path="review/:reviewId"
            element={
              <StudioGuard>
                <Suspense fallback={<StudioFallback />}>
                  <StudioReviewDetailPage />
                </Suspense>
              </StudioGuard>
            }
          />
          <Route
            path="sources"
            element={
              <StudioGuard>
                <Suspense fallback={<StudioFallback />}>
                  <StudioSourcesPage />
                </Suspense>
              </StudioGuard>
            }
          />
        </Route>
        <Route
          path="/"
          element={
            <PublicChrome>
              <TimelinePage />
            </PublicChrome>
          }
        />
        <Route
          path="/timeline"
          element={
            <PublicChrome>
              <TimelinePage />
            </PublicChrome>
          }
        />
        <Route
          path="/search"
          element={
            <PublicChrome>
              <SearchPage />
            </PublicChrome>
          }
        />
        <Route
          path="/events/:id"
          element={
            <PublicChrome>
              <EventPage />
            </PublicChrome>
          }
        />
        <Route
          path="/entities/:id"
          element={
            <PublicChrome>
              <EntityPage />
            </PublicChrome>
          }
        />
        <Route
          path="*"
          element={
            <PublicChrome>
              <NotFoundState />
            </PublicChrome>
          }
        />
      </Routes>
    </StudioAuthProvider>
  );
}
