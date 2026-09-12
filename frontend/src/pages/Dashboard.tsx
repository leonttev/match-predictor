import { useEffect, useState } from "react";
import {
  api,
  tierLabel,
  tierRank,
  type Match,
  type PredictResponse,
  type Roster,
  type Team,
} from "../api/client";
import TeamAutocomplete from "../components/TeamAutocomplete";

interface Props {
  token: string;
  twoFactorEnabled: boolean;
  onLogout: () => void;
  onSetup2fa: () => void;
}

export default function Dashboard({ token, twoFactorEnabled, onLogout, onSetup2fa }: Props) {
  const [teams, setTeams] = useState<Team[]>([]);
  const [matches, setMatches] = useState<Match[]>([]);
  const [teamAQuery, setTeamAQuery] = useState("");
  const [teamBQuery, setTeamBQuery] = useState("");
  const [teamAId, setTeamAId] = useState<number | "">("");
  const [teamBId, setTeamBId] = useState<number | "">("");
  const [prediction, setPrediction] = useState<PredictResponse | null>(null);
  const [ingestStatus, setIngestStatus] = useState<string | null>(null);
  const [ingesting, setIngesting] = useState(false);
  const [predicting, setPredicting] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [rosterTeamId, setRosterTeamId] = useState<number | null>(null);
  const [rosterCache, setRosterCache] = useState<Record<number, Roster | "loading" | "error">>(
    {},
  );

  async function loadData() {
    try {
      const [t, m] = await Promise.all([
        api.listTeams(token),
        // Only tier-1 (premium) events — lower-tier qualifiers dominate the
        // raw feed by volume and drown out the matches that matter.
        api.listMatches(token, 30, "tier1"),
      ]);
      // Tier first, rating second: a tier2 team never outranks a tier1 one.
      t.sort((a, b) => tierRank(a.tier) - tierRank(b.tier) || b.rating - a.rating);
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
        `Команд: ${res.teams_ingested}, матчей: ${res.matches_ingested} (из них tier 1: ${res.tier1_matches}), рейтингов обновлено: ${res.ratings_updated}`,
      );
      await loadData();
    } catch {
      setIngestStatus("Ошибка загрузки данных из OpenDota");
    } finally {
      setIngesting(false);
    }
  }

  function showRoster(teamId: number) {
    setRosterTeamId(teamId);
    if (rosterCache[teamId]) return;
    setRosterCache((prev) => ({ ...prev, [teamId]: "loading" }));
    api
      .getRoster(token, teamId)
      .then((roster) => setRosterCache((prev) => ({ ...prev, [teamId]: roster })))
      .catch(() => setRosterCache((prev) => ({ ...prev, [teamId]: "error" })));
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
          {twoFactorEnabled && <span className="badge-ok">2FA включена</span>}
          <button className="secondary" onClick={onSetup2fa}>
            {twoFactorEnabled ? "Пересоздать 2FA" : "Настроить 2FA"}
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
        <p className="hint">
          Доступны все {teams.length} команд из базы, а не только топ — начните вводить название.
        </p>
        <form className="predict-form" onSubmit={handlePredict}>
          <TeamAutocomplete
            teams={teams}
            placeholder="Команда A"
            value={teamAQuery}
            onChange={(q, id) => {
              setTeamAQuery(q);
              setTeamAId(id);
            }}
          />
          <span>vs</span>
          <TeamAutocomplete
            teams={teams}
            placeholder="Команда B"
            value={teamBQuery}
            onChange={(q, id) => {
              setTeamBQuery(q);
              setTeamBId(id);
            }}
          />
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
              <strong>{prediction.team_a.name}</strong>{" "}
              <span className={`tier-badge ${prediction.team_a.tier}`}>
                {tierLabel(prediction.team_a.tier)}
              </span>{" "}
              победит с вероятностью{" "}
              <strong>{(prediction.team_a_win_prob * 100).toFixed(1)}%</strong> против{" "}
              <strong>{prediction.team_b.name}</strong>{" "}
              <span className={`tier-badge ${prediction.team_b.tier}`}>
                {tierLabel(prediction.team_b.tier)}
              </span>
            </p>
            <p className="hint">
              Elo-компонента: {(prediction.elo_component * 100).toFixed(1)}% · форма:{" "}
              {(prediction.form_component * 100).toFixed(1)}% · поправка на тир:{" "}
              {prediction.tier_adjustment > 0 ? "+" : ""}
              {prediction.tier_adjustment.toFixed(0)} Elo
            </p>
          </div>
        )}
      </section>

      <section className="panel">
        <h2>Топ-10 команд</h2>
        <div className="top-teams-layout">
          <ul className="top-teams-list">
            {teams.slice(0, 10).map((t, i) => (
              <li
                key={t.id}
                className={rosterTeamId === t.id ? "active" : ""}
                onMouseEnter={() => showRoster(t.id)}
                onClick={() => showRoster(t.id)}
              >
                <span className="rank">{i + 1}</span>
                <span className="team-name">{t.name}</span>
                <span className={`tier-badge ${t.tier}`}>{tierLabel(t.tier)}</span>
              </li>
            ))}
          </ul>
          <div className="roster-panel">
            {rosterTeamId === null ? (
              <p className="hint">Наведите на команду слева, чтобы увидеть состав.</p>
            ) : (
              (() => {
                const entry = rosterCache[rosterTeamId];
                const teamName = teams.find((t) => t.id === rosterTeamId)?.name ?? "";
                if (entry === "loading" || entry === undefined) {
                  return <p className="hint">Загрузка состава...</p>;
                }
                if (entry === "error") {
                  return <p className="error">Не удалось загрузить состав</p>;
                }
                return (
                  <>
                    <h3>{teamName}</h3>
                    {entry.players.length === 0 ? (
                      <p className="hint">Действующий состав не найден в OpenDota.</p>
                    ) : (
                      <ul className="roster-players">
                        {entry.players.map((p) => (
                          <li key={p.name}>
                            {p.name} <span className="hint">{p.games_played} игр</span>
                          </li>
                        ))}
                      </ul>
                    )}
                  </>
                );
              })()
            )}
          </div>
        </div>
      </section>

      <section className="panel">
        <h2>Последние матчи (Tier 1)</h2>
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
