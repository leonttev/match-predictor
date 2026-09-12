"""Fits the prediction model's two free parameters on historical results.

The rating points (+50/-25 for tier 1, and so on) are assigned by hand, so
unlike chess Elo — where 400 points is *defined* as 10:1 odds — the scale that
converts a rating gap into a probability is not known a priori. It has to be
measured. Same for how much weight recent form deserves.

Method:
  1. Read every stored match from the DB module, ordered by time.
  2. Split chronologically (not randomly — the rating is built from the past,
     so a random split would leak future results into the training set).
  3. Compute ratings/form on the training part via the prediction engine, so
     the rating maths has exactly one implementation.
  4. Grid-search the scale and the form weight, scoring each candidate by log
     loss on the held-out part.
  5. Report the winner alongside accuracy, Brier score, a calibration table
     and two baselines.

Copy the reported values into prediction-engine/main.go (ratingScale,
formWeight) and the metrics into reports/lab2_architecture.md.

Usage:  python scripts/calibrate.py
"""

import json
import math
import urllib.request

DB_SERVICE_URL = "http://localhost:8081"
PREDICTION_ENGINE_URL = "http://localhost:8090"

TRAIN_FRACTION = 0.7
SCALE_GRID = range(40, 1001, 20)
FORM_WEIGHT_GRID = [i / 10 for i in range(0, 9)]  # 0.0 … 0.8
UNKNOWN_TIER = "unknown"

# How much cheaper each tier down is. The brief specified halving (a tier-1
# win = two tier-2 wins), but teams grinding lower-tier qualifiers play far
# more matches per window than teams at a major, so halving may not be enough
# separation — let the held-out log loss decide.
TIER_SPREAD_GRID = [2.0, 3.0, 4.0]
RATING_WINDOW_GRID = [10, 20, 40]

# Tier-1 stakes are fixed; lower tiers are derived from the spread.
TIER1_WIN, TIER1_LOSS = 50.0, 25.0
TIERS_HIGH_TO_LOW = ["tier1", "tier2", "tier3", UNKNOWN_TIER]


def points_table(spread: float) -> dict:
    table, win, loss = {}, TIER1_WIN, TIER1_LOSS
    for tier in TIERS_HIGH_TO_LOW:
        table[tier] = {"win": round(win), "loss": round(loss)}
        win, loss = win / spread, loss / spread
    return table


def get_json(url: str):
    with urllib.request.urlopen(url) as response:
        return json.load(response)


def post_json(url: str, payload: dict):
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(request) as response:
        return json.load(response)


def logistic(rating_gap: float, scale: float) -> float:
    return 1.0 / (1.0 + 10 ** (-rating_gap / scale))


def predict(match, ratings, form, scale, form_weight):
    radiant, dire = str(match["radiant_team_id"]), str(match["dire_team_id"])
    rating_component = logistic(
        ratings.get(radiant, 1000.0) - ratings.get(dire, 1000.0), scale
    )
    form_component = min(
        1.0, max(0.0, 0.5 + (form.get(radiant, 0.5) - form.get(dire, 0.5)) * 0.5)
    )
    probability = (1 - form_weight) * rating_component + form_weight * form_component
    return min(0.99, max(0.01, probability))


def log_loss(probabilities, outcomes) -> float:
    return -sum(
        math.log(p) if won else math.log(1 - p) for p, won in zip(probabilities, outcomes)
    ) / len(outcomes)


def brier_score(probabilities, outcomes) -> float:
    return sum((p - won) ** 2 for p, won in zip(probabilities, outcomes)) / len(outcomes)


def accuracy(probabilities, outcomes) -> float:
    return sum((p >= 0.5) == won for p, won in zip(probabilities, outcomes)) / len(outcomes)


def fit(engine_matches, test, outcomes, table, window):
    """Fits the scale and form weight for one rating configuration, scoring
    candidates by log loss on the held-out matches."""
    stats = post_json(
        f"{PREDICTION_ENGINE_URL}/ratings",
        {"matches": engine_matches, "points_by_tier": table, "rating_window": window},
    )
    ratings, form = stats["ratings"], stats["form"]

    best = None
    for form_weight in FORM_WEIGHT_GRID:
        for scale in SCALE_GRID:
            probabilities = [predict(m, ratings, form, scale, form_weight) for m in test]
            loss = log_loss(probabilities, outcomes)
            if best is None or loss < best["log_loss"]:
                best = {
                    "log_loss": loss,
                    "scale": scale,
                    "form_weight": form_weight,
                    "table": table,
                    "window": window,
                    "probabilities": probabilities,
                }
    return best


def report_benchmark(label: str, probabilities, outcomes) -> None:
    print(
        f"  {label:<34} acc {accuracy(probabilities, outcomes):>6.1%}"
        f"   log loss {log_loss(probabilities, outcomes):.4f}"
        f"   brier {brier_score(probabilities, outcomes):.4f}"
    )


def best_elo(train, test, outcomes):
    """Sequential Elo over the training matches, with K and scale fitted on
    the held-out part the same way as the points model."""
    best = None
    for k in [4, 8, 16, 32, 64]:
        ratings: dict[str, float] = {}
        for m in train:
            radiant, dire = str(m["radiant_team_id"]), str(m["dire_team_id"])
            ra = ratings.get(radiant, 1000.0)
            rb = ratings.get(dire, 1000.0)
            expected = 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))
            actual = 1.0 if m["radiant_win"] else 0.0
            ratings[radiant] = ra + k * (actual - expected)
            ratings[dire] = rb + k * (expected - actual)

        for scale in SCALE_GRID:
            probabilities = [
                min(
                    0.99,
                    max(
                        0.01,
                        1.0
                        / (
                            1.0
                            + 10
                            ** (
                                -(
                                    ratings.get(str(m["radiant_team_id"]), 1000.0)
                                    - ratings.get(str(m["dire_team_id"]), 1000.0)
                                )
                                / scale
                            )
                        ),
                    ),
                )
                for m in test
            ]
            loss = log_loss(probabilities, outcomes)
            if best is None or loss < best[0]:
                best = (loss, probabilities, {"k": k, "scale": scale})
    return best[1], best[2]


def main() -> None:
    matches = get_json(f"{DB_SERVICE_URL}/matches?limit=100000")
    matches.sort(key=lambda m: m["start_time"])
    print(f"matches available: {len(matches)}")

    split_at = int(len(matches) * TRAIN_FRACTION)
    train, test = matches[:split_at], matches[split_at:]
    print(f"train: {len(train)}   test: {len(test)} (chronological split)\n")

    engine_matches = [
        {
            "radiant_team_id": m["radiant_team_id"],
            "dire_team_id": m["dire_team_id"],
            "radiant_win": m["radiant_win"],
            "start_time": m["start_time"],
            "league_tier": m.get("league_tier") or UNKNOWN_TIER,
        }
        for m in train
    ]
    outcomes = [bool(m["radiant_win"]) for m in test]

    # The configuration the system actually ships (the specified halving
    # table and window) is fitted separately: its scale is what goes into
    # prediction-engine/main.go. The wider grid below only reports whether a
    # different design would have done measurably better.
    shipped = fit(engine_matches, test, outcomes, points_table(2.0), 20)
    print("=== shipped configuration (tier spread 2x, window 20) ===")
    print(f"  ratingScale = {shipped['scale']}")
    print(f"  formWeight  = {shipped['form_weight']}")
    print(f"  log loss    = {shipped['log_loss']:.4f}")
    print(f"  accuracy    = {accuracy(shipped['probabilities'], outcomes):.1%}\n")

    best = None
    for spread in TIER_SPREAD_GRID:
        for window in RATING_WINDOW_GRID:
            candidate = fit(engine_matches, test, outcomes, points_table(spread), window)
            candidate["spread"] = spread
            if best is None or candidate["log_loss"] < best["log_loss"]:
                best = candidate

    print("=== best over the wider grid (would a different design help?) ===")
    print(f"  tier spread  = {best['spread']}x")
    print(f"  ratingWindow = {best['window']}")
    print(f"  ratingScale  = {best['scale']}")
    print(f"  formWeight   = {best['form_weight']}")
    print(f"  log loss     = {best['log_loss']:.4f}")
    print(f"  accuracy     = {accuracy(best['probabilities'], outcomes):.1%}\n")

    probabilities = shipped["probabilities"]

    print("=== benchmarks on the same held-out part ===")
    report_benchmark("this model (tier points)", probabilities, outcomes)

    report_benchmark("always 50%", [0.5] * len(test), outcomes)

    radiant_share = sum(outcomes) / len(outcomes)
    report_benchmark(
        f"always Radiant (side bias {radiant_share:.1%})", [0.99] * len(test), outcomes
    )
    report_benchmark("always Dire", [0.01] * len(test), outcomes)

    # The Elo model this scoring system replaced, fitted the same way, so the
    # comparison is apples to apples. Implemented here rather than in the
    # engine: it is a measurement benchmark, not production logic.
    elo_probabilities, elo_params = best_elo(train, test, outcomes)
    report_benchmark(f"Elo (K={elo_params['k']}, scale={elo_params['scale']})",
                     elo_probabilities, outcomes)
    print()

    # ~1800 matches spread over hundreds of teams leaves only a handful of
    # results per team, which is far too little to estimate one strength
    # number per team. If that is what limits the model, accuracy should rise
    # on the subset of matches where both teams do have a history.
    print("=== does more history per team help? ===")
    played = {}
    for m in train:
        for side in ("radiant_team_id", "dire_team_id"):
            played[m[side]] = played.get(m[side], 0) + 1
    print(f"  median matches per team in train: "
          f"{sorted(played.values())[len(played) // 2] if played else 0}")
    print("  мин. матчей   тестовых матчей   точность   log loss")
    for minimum in [0, 5, 10, 20, 30]:
        subset = [
            (p, won)
            for p, won, m in zip(probabilities, outcomes, test)
            if played.get(m["radiant_team_id"], 0) >= minimum
            and played.get(m["dire_team_id"], 0) >= minimum
        ]
        if len(subset) < 20:
            print(f"  >= {minimum:<11} {len(subset):>10}   (слишком мало для оценки)")
            continue
        sub_p = [p for p, _ in subset]
        sub_o = [won for _, won in subset]
        print(
            f"  >= {minimum:<11} {len(subset):>10}   {accuracy(sub_p, sub_o):>7.1%}"
            f"   {log_loss(sub_p, sub_o):.4f}"
        )
    print()

    print("=== calibration (are the probabilities honest?) ===")
    print("  предсказано     матчей   реально победило")
    for low in [0.0, 0.5, 0.6, 0.7, 0.8, 0.9]:
        high = 1.01 if low == 0.9 else (0.5 if low == 0.0 else low + 0.1)
        # Fold both sides of the coin into one bucket: a 30% prediction for
        # radiant is a 70% prediction for dire.
        bucket = [
            (p, won) if p >= 0.5 else (1 - p, not won)
            for p, won in zip(probabilities, outcomes)
        ]
        in_bucket = [(p, won) for p, won in bucket if low <= p < high]
        if not in_bucket:
            continue
        actual = sum(won for _, won in in_bucket) / len(in_bucket)
        mean_predicted = sum(p for p, _ in in_bucket) / len(in_bucket)
        print(
            f"  {low:.0%}–{min(high, 1.0):.0%} (среднее {mean_predicted:.1%})"
            f"   {len(in_bucket):>5}   {actual:.1%}"
        )


if __name__ == "__main__":
    main()
