import { Link, NavLink, Outlet, useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { useStudioAuth } from "../../lib/studio-auth";

const NAV = [
  ["/studio", "工作台", "◫"], ["/studio/imports", "生产任务", "↗"], ["/studio/review", "内容审核", "✓"],
  ["/studio/sources", "史料管理", "▤"], ["/studio/coverage", "资料覆盖", "◎"],
];
export default function StudioLayout() {
  const auth = useStudioAuth();
  const navigate = useNavigate();
  return <div className="studio-shell" data-view="studio">
    <header className="studio-topbar">
      <Link className="studio-brand" to="/studio"><span className="studio-brand-mark">史</span><div><strong>Chronicle</strong><small>历史内容工作台</small></div></Link>
      <nav className="studio-nav" aria-label="Studio 导航">{NAV.map(([path, title, mark]) => <NavLink key={path} to={path} end={path === "/studio"}><span aria-hidden="true">{mark}</span>{title}</NavLink>)}</nav>
      <Link className="studio-reader-link" to="/history">查看历史阅读页 <span aria-hidden="true">↗</span></Link>
      <div className="studio-user">{auth.username ? <><span className="studio-user-avatar" aria-hidden="true">{auth.username.slice(0, 1).toUpperCase()}</span><span>{auth.username}</span><Button variant="ghost" size="sm" onClick={() => { auth.logout(); navigate("/studio/login", { replace: true }); }}>退出</Button></> : <Button variant="outline" onClick={() => navigate("/studio/login")}>登录</Button>}</div>
    </header>
    <main className="studio-main"><Outlet /></main>
  </div>;
}
