import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Button } from "../../components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "../../components/ui/card";
import { Input, Label } from "../../components/ui/input";
import { useStudioAuth } from "../../lib/studio-auth";

export default function StudioLoginPage() {
  const auth = useStudioAuth();
  const navigate = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState(false);

  const submit = async (event: React.FormEvent) => {
    event.preventDefault();
    setPending(true);
    setError(null);
    try {
      await auth.login(username, password);
      navigate("/studio", { replace: true });
    } catch (err) {
      setError(err instanceof Error && err.message === "unauthorized" ? "unauthorized：用户名或密码不正确" : "登录失败：无法连接 Studio 状态接口");
    } finally {
      setPending(false);
    }
  };

  return (
    <div className="studio-auth-wrap" data-view="studio-login">
      <Card className="studio-auth-card">
        <CardHeader>
          <CardTitle>Studio 登录</CardTitle>
          <CardDescription>
            使用环境配置的管理员账号登录。认证由服务端强制执行；浏览器只负责携带凭据，不做任何权限判定。
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={submit} className="studio-form">
            <div>
              <Label htmlFor="studio-username">用户名</Label>
              <Input
                id="studio-username"
                autoComplete="username"
                value={username}
                onChange={(event) => setUsername(event.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="studio-password">密码</Label>
              <Input
                id="studio-password"
                type="password"
                autoComplete="current-password"
                value={password}
                onChange={(event) => setPassword(event.target.value)}
              />
            </div>
            {error ? <p className="studio-error">{error}</p> : null}
            <Button type="submit" disabled={pending}>
              {pending ? "登录中…" : "登录 Studio"}
            </Button>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
