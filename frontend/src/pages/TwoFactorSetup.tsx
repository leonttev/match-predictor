import { useEffect, useState } from "react";
import QRCode from "qrcode";
import { api } from "../api/client";

interface Props {
  token: string;
  onEnabled: () => void;
  onSkip: () => void;
}

export default function TwoFactorSetup({ token, onEnabled, onSkip }: Props) {
  const [secret, setSecret] = useState("");
  const [qrDataUrl, setQrDataUrl] = useState("");
  const [code, setCode] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  useEffect(() => {
    api.setup2fa(token).then(async (res) => {
      setSecret(res.secret);
      setQrDataUrl(await QRCode.toDataURL(res.provisioning_uri));
    });
  }, [token]);

  async function handleEnable(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await api.enable2fa(token, code);
      onEnabled();
    } catch {
      setError("Неверный код — попробуйте снова");
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className="auth-card">
      <h2>Настройка 2FA</h2>
      <p className="hint">
        Отсканируйте QR-код в приложении-аутентификаторе (Google Authenticator, Authy) или
        введите ключ вручную:
      </p>
      {qrDataUrl && <img className="qr" src={qrDataUrl} alt="TOTP QR code" />}
      <code className="secret">{secret}</code>
      <form onSubmit={handleEnable}>
        <label>
          Код из приложения
          <input
            value={code}
            onChange={(e) => setCode(e.target.value)}
            inputMode="numeric"
            maxLength={6}
            required
          />
        </label>
        {error && <p className="error">{error}</p>}
        <button type="submit" disabled={loading || !secret}>
          {loading ? "..." : "Включить 2FA"}
        </button>
      </form>
      <p className="switch-link">
        <a onClick={onSkip}>Пропустить</a>
      </p>
    </div>
  );
}
