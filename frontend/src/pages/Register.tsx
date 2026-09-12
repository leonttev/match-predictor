import { useState } from "react";
import { api, ApiError } from "../api/client";

interface Props {
  onRegistered: () => void;
  onGoLogin: () => void;
}

export default function Register({ onRegistered, onGoLogin }: Props) {
  const [username, setUsername] = useState("");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.register(username, email, password);
      onRegistered();
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 409
          ? "Такой логин уже занят"
          : "Не удалось зарегистрироваться",
      );
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-card">
      <h2>Регистрация</h2>
      <form onSubmit={handleSubmit}>
        <label>
          Логин
          <input value={username} onChange={(e) => setUsername(e.target.value)} required />
        </label>
        <label>
          Email
          <input
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            required
          />
        </label>
        <label>
          Пароль
          <input
            type="password"
            minLength={8}
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={loading}>
          {loading ? "..." : "Создать аккаунт"}
        </button>
      </form>
      <p className="switch-link">
        Уже есть аккаунт? <a onClick={onGoLogin}>Войти</a>
      </p>
    </div>
  );
}
