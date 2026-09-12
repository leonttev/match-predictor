import { useEffect, useState } from "react";
import { api, type Match, type PredictResponse, type Team } from "../api/client";

interface Props {
  token: string;
  onLogout: () => void;
  onSetup2fa: () => void;
}

export default function Dashboard({ token, onLogout, onSetup2fa }: Props) {
  const [teams, setTeams] = useState<Team[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [teamAId, setTeamAId] = useState<number | "">("");
  const [teamBId, setTeamBId] = useState<number | "">("");
  const [prediction, setPrediction] = useState<PredictResponse | null>(null);
  const [ingestStatus, setIngestStatus] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);

  async function loadData() {
    try {
      const [t, m] = await Promise.all([api.listTeams(token), api.listMatches(token, 30)]);
      t.sort((a, b) => b.rating - a.rating);
      setTeams(t);
      setMatches(m);
      setLoadError(null);
    } catch {
      setLoadError("Не удалось загрузить данные с бэкенда");
    }
  }

  useEffect(() => {
    loadData();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token]);

  async function handleIngest() {
    setIngesting(true);
    setIngestStatus(null);
    try {
      const res = await api.runIngestion(token);
      setIngestStatus(
        `Загружено команд: ${res.teams_ingested}, матчей: ${res.matches_ingested}, рейтингов обновлено: ${res.ratings_updated}`,
      );
      await loadData();
    } catch {
      setIngestStatus("Ошибка загрузки данных из OpenDota");
    } finally {
      setIngesting(false);
    }
  }

  async function handlePredict(e: React.FormEvent) {
    e.preventDefault();
    if (teamAId === "" || teamBId === "" || teamAId === teamBId) return;
    setPredicting(true);
    setPrediction(null);
    try {
      const res = await api.predict(token, Number(teamAId), Number(teamBId));
      setPrediction(res);
    } catch {
      setLoadError("Не удалось построить прогноз");
    } finally {
      setPredicting(false);
    }
  }

  return (
    <div className="dashboard">
      <header>
        <h1>Система прогнозирования матчей — Dota 2</h1>
        <div className="header-actions">
          <button className="secondary" onClick={onSetup2fa}>
            Настроить 2FA
          </button>
          <button className="secondary" onClick={onLogout}>
            Выйти
          </button>
        </div>
      </header>

      <section className="panel">
        <h2>Данные</h2>
        <p className="hint">
          Источник: OpenDota API (Dota 2, публичные данные профессиональных команд и матчей).
        </p>
        <button onClick={handleIngest} disabled={ingesting}>
          {ingesting ? "Загрузка..." : "Обновить данные и пересчитать рейтинги"}
        </button>
        {ingestStatus && <p className="hint">{ingestStatus}</p>}
        {loadError && <p className="error">{loadError}</p>}
      </section>

      <section className="panel">
        <h2>Прогноз матча</h2>
        <form className="predict-form" onSubmit={handlePredict}>
          <select value={teamAId} onChange={(e) => setTeamAId(Number(e.target.value) || "")}>
            <option value="">Команда A</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({Math.round(t.rating)})
              </option>
            ))}
          </select>
          <span>vs</span>
          <select value={teamBId} onChange={(e) => setTeamBId(Number(e.target.value) || "")}>
            <option value="">Команда B</option>
            {teams.map((t) => (
              <option key={t.id} value={t.id}>
                {t.name} ({Math.round(t.rating)})
              </option>
            ))}
          </select>
          <button type="submit" disabled={predicting || teamAId === "" || teamBId === ""}>
            {predicting ? "..." : "Спрогнозировать"}
          </button>
        </form>

        {prediction && (
          <div className="prediction-result">
            <div className="prob-bar">
              <div
                className="prob-fill"
                style={{ width: `${(prediction.team_a_win_prob * 100).toFixed(1)}%` }}
              />
            </div>
            <p>
              <strong>{prediction.team_a.name}</strong> победит с вероятностью{" "}
              <strong>{(prediction.team_a_win_prob * 100).toFixed(1)}%</strong> против{" "}
              <strong>{prediction.team_b.name}</strong>
            </p>
            <p className="hint">
              Elo-компонента: {(prediction.elo_component * 100).toFixed(1)}% · форма:{" "}
              {(prediction.form_component * 100).toFixed(1)}%
            </p>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Команды по рейтингу ({teams.length})</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Команда</th>
                <th>Рейтинг (Elo)</th>
                <th>Форма</th>
              </tr>
            </thead>
            <tbody>
              {teams.slice(0, 20).map((t) => (
                <tr key={t.id}>
                  <td>{t.name}</td>
                  <td>{Math.round(t.rating)}</td>
                  <td>{Math.round(t.recent_form * 100)}%</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section className="panel">
        <h2>Последние матчи</h2>
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Radiant</th>
                <th>Dire</th>
                <th>Результат</th>
                <th>Лига</th>
              </tr>
            </thead>
            <tbody>
              {matches.map((m) => (
                <tr key={m.id}>
                  <td>{m.radiant_team_name}</td>
                  <td>{m.dire_team_name}</td>
                  <td>{m.radiant_win ? "Radiant win" : "Dire win"}</td>
                  <td>{m.league_name ?? "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </div>
  );
}
