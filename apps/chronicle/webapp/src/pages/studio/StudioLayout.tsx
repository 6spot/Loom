import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { Badge } from "../../components/ui/badge";
import { Button } from "../../components/ui/button";
import { useStudioAuth } from "../../lib/studio-auth";

export default function StudioLayout() {
  const auth = useStudioAuth();
  const navigate = useNavigate();

  return (
    <div className="studio-shell" data-view="studio">
      <header className="studio-topbar">
        <div className="studio-brand">
          <span className="studio-brand-mark">S</span>
          <div>
            <strong>Chronicle Studio</strong>
            <small>engineering surface · shadcn foundation</small>
          </div>
        </div>
        <nav className="studio-nav" aria-label="Studio 导航">
          <NavLink to="/studio" end>总览</NavLink>
          <NavLink to="/studio/imports">Imports</NavLink>
          <NavLink to="/studio/review">Review</NavLink>
          <NavLink to="/studio/sources">Sources / Corpus</NavLink>
        </nav>
        <div className="studio-user">
          {auth.username ? (
            <>
              <Badge>{auth.username}</Badge>
              <Button
                variant="outline"
                size="sm"
                onClick={() => {
                  auth.logout();
                  navigate("/studio/login", { replace: true });
                }}
              >
                退出
              </Button>
            </>
          ) : (
            <Button variant="outline" size="sm" onClick={() => navigate("/studio/login")}>
              登录
            </Button>
          )}
        </div>
      </header>
      <main className="studio-main">
        <Outlet />
      </main>
    </div>
  );
}
