import { useEffect, useState } from "react";
import "./App.css";
import { api } from "./api/client";
import Login from "./pages/Login";
import Register from "./pages/Register";
import TwoFactorVerify from "./pages/TwoFactorVerify";
import TwoFactorSetup from "./pages/TwoFactorSetup";
import Dashboard from "./pages/Dashboard";

type View = "loading" | "login" | "register" | "2fa-verify" | "2fa-setup" | "dashboard";

const TOKEN_STORAGE_KEY = "match-predictor-token";

export default function App() {
  const storedToken = localStorage.getItem(TOKEN_STORAGE_KEY);
  const [view, setView] = useState<View>(storedToken ? "loading" : "login");
  const [token, setToken] = useState<string | null>(storedToken);
  const [pendingToken, setPendingToken] = useState<string | null>(null);
  const [twoFactorEnabled, setTwoFactorEnabled] = useState(false);

  // A token sitting in localStorage is not proof of a usable session: it can
  // be expired, or name a user that no longer exists. Validate it before
  // showing the dashboard, otherwise every authed request there fails.
  useEffect(() => {
    if (!storedToken) return;
    api
      .me(storedToken)
      .then((info) => {
        setTwoFactorEnabled(info.totp_enabled);
        setView("dashboard");
      })
      .catch(() => {
        localStorage.removeItem(TOKEN_STORAGE_KEY);
        setToken(null);
        setView("login");
      });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  function completeLogin(newToken: string) {
    localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
    setToken(newToken);
    api
      .me(newToken)
      .then((info) => setTwoFactorEnabled(info.totp_enabled))
      .catch(() => setTwoFactorEnabled(false));
    setView("dashboard");
  }

  function logout() {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setTwoFactorEnabled(false);
    setView("login");
  }

  return (
    <div className="app">
      {view === "loading" && <p className="hint">Проверка сессии...</p>}

      {view === "login" && (
        <Login
          onLoggedIn={completeLogin}
          onNeed2fa={(pt) => {
            setPendingToken(pt);
            setView("2fa-verify");
          }}
          onGoRegister={() => setView("register")}
        />
      )}

      {view === "register" && (
        <Register onRegistered={() => setView("login")} onGoLogin={() => setView("login")} />
      )}

      {view === "2fa-verify" && pendingToken && (
        <TwoFactorVerify
          pendingToken={pendingToken}
          onVerified={completeLogin}
          onCancel={() => setView("login")}
        />
      )}

      {view === "2fa-setup" && token && (
        <TwoFactorSetup
          token={token}
          onEnabled={() => {
            setTwoFactorEnabled(true);
            setView("dashboard");
          }}
          onSkip={() => setView("dashboard")}
        />
      )}

      {view === "dashboard" && token && (
        <Dashboard
          token={token}
          twoFactorEnabled={twoFactorEnabled}
          onLogout={logout}
          onSetup2fa={() => setView("2fa-setup")}
        />
      )}
    </div>
  );
}
