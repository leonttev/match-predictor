import { useState } from "react";
import "./App.css";
import Login from "./pages/Login";
import Register from "./pages/Register";
import TwoFactorVerify from "./pages/TwoFactorVerify";
import TwoFactorSetup from "./pages/TwoFactorSetup";
import Dashboard from "./pages/Dashboard";

type View = "login" | "register" | "2fa-verify" | "2fa-setup" | "dashboard";

const TOKEN_STORAGE_KEY = "match-predictor-token";

export default function App() {
  const [view, setView] = useState<View>(
    localStorage.getItem(TOKEN_STORAGE_KEY) ? "dashboard" : "login",
  );
  const [token, setToken] = useState<string | null>(localStorage.getItem(TOKEN_STORAGE_KEY));
  const [pendingToken, setPendingToken] = useState<string | null>(null);

  function completeLogin(newToken: string) {
    localStorage.setItem(TOKEN_STORAGE_KEY, newToken);
    setToken(newToken);
    setView("dashboard");
  }

  function logout() {
    localStorage.removeItem(TOKEN_STORAGE_KEY);
    setToken(null);
    setView("login");
  }

  return (
    <div className="app">
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
          onEnabled={() => setView("dashboard")}
          onSkip={() => setView("dashboard")}
        />
      )}

      {view === "dashboard" && token && (
        <Dashboard token={token} onLogout={logout} onSetup2fa={() => setView("2fa-setup")} />
      )}
    </div>
  );
}
