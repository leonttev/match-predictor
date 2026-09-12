import { useState } from "react";
import { api, ApiError } from "../api/client";

interface Props {
  pendingToken: string;
  onVerified: (token: string) => void;
  onCancel: () => void;
}

export default function TwoFactorVerify({ pendingToken, onVerified, onCancel }: Props) {
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const res = await api.loginWith2fa(pendingToken, code);
      onVerified(res.token);
    } catch (err) {
      setError(err instanceof ApiError ? "Неверный код" : "Ошибка сети");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-card">
      <h2>Код подтверждения (2FA)</h2>
      <p className="hint">Введите 6-значный код из приложения-аутентификатора.</p>
      <form onSubmit={handleSubmit}>
        <label>
          Код
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
            maxLength={6}
            required
            autoFocus
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={loading}>
          {loading ? "..." : "Подтвердить"}
        </button>
      </form>
      <p className="switch-link">
        <a onClick={onCancel}>Назад</a>
      </p>
    </div>
  );
}
