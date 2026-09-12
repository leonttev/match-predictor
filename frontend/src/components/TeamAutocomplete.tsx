import { useEffect, useRef, useState } from "react";
import type { Team } from "../api/client";

interface Props {
  teams: Team[];
  placeholder: string;
  value: string;
  onChange: (query: string, teamId: number | "") => void;
}

const MAX_SUGGESTIONS = 12;

export default function TeamAutocomplete({ teams, placeholder, value, onChange }: Props) {
  const [open, setOpen] = useState(false);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    function handleClickOutside(e: MouseEvent) {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener("mousedown", handleClickOutside);
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, []);

  const query = value.trim().toLowerCase();
  const suggestions = query
    ? teams.filter((t) => t.name.toLowerCase().includes(query)).slice(0, MAX_SUGGESTIONS)
    : teams.slice(0, MAX_SUGGESTIONS);

  function resolve(query: string): number | "" {
    const match = teams.find((t) => t.name.trim().toLowerCase() === query.trim().toLowerCase());
    return match ? match.id : "";
  }

  function selectTeam(t: Team) {
    onChange(t.name, t.id);
    setOpen(false);
  }

  return (
    <div className="autocomplete" ref={containerRef}>
      <input
        className="predict-input"
        placeholder={placeholder}
        value={value}
        onChange={(e) => onChange(e.target.value, resolve(e.target.value))}
        onFocus={() => setOpen(true)}
        autoComplete="off"
      />
      {open && suggestions.length > 0 && (
        <ul className="autocomplete-list">
          {suggestions.map((t) => (
            <li key={t.id} onMouseDown={() => selectTeam(t)}>
              {t.name}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
