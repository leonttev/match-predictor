import { useState } from "react";
import { api, ApiError } from "../api/client";

interface Props {
  onLoggedIn: (token: string) => void;
  onNeed2fa: (pendingToken: string) => void;
  onGoRegister: () => void;
}

export default function Login({ onLoggedIn, onNeed2fa, onGoRegister }: Props) {
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.login(username, password);
      if (res.status === "2fa_required") {
        onNeed2fa(res.token);
      } else {
        onLoggedIn(res.token);
      }
    } catch (err) {
      setError(err instanceof ApiError ? "Неверный логин или пароль" : "Ошибка сети");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-card">
      <h2>Вход</h2>
      <form onSubmit={handleSubmit}>
        <label>
          Логин
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          Пароль
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={loading}>
          {loading ? "..." : "Войти"}
        </button>
      </form>
      <p className="switch-link">
        Нет аккаунта? <a onClick={onGoRegister}>Зарегистрироваться</a>
      </p>
    </div>
  );
}
