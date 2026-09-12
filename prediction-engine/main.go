// Prediction engine: functional module (course requirement §2.6).
//
// Exposes an HTTP API (net/http, goroutine-per-request) that:
//   - POST /ratings — derives every team's rating and recent form from match
//     history, fanned out across a worker pool of goroutines.
//   - POST /predict — turns two teams' ratings into a win probability via a
//     logistic model whose scale constant is calibrated on historical data
//     (see scripts/calibrate.py).
//
// Rating model: every team starts at baseRating and earns tier-weighted points
// per result over a rolling window of its most recent ratingWindow matches.
// A win at a tier-1 event is worth twice a tier-2 win and four times a tier-3
// one, so the strength of the opposition pool is priced into the points
// themselves rather than corrected for afterwards. Because the window sums
// independent per-team results, teams are processed concurrently.
package main

import (
	"encoding/json"
	"log"
	"math"
	"net/http"
	"os"
	"runtime"
	"sort"
	"strconv"
	"sync"
)

const (
	// Only a team's most recent matches count, so the rating tracks current
	// strength instead of growing with career volume: a win is worth more
	// than a loss costs, so without a window any team above a ~33% win rate
	// would climb indefinitely just by playing often.
	ratingWindow = 20

	formWindow = 5
)

// Starting rating by the strongest tier a team has been observed in. Without
// this, a team sweeping 20 tier-2 qualifier matches outranks a tier-1 team
// that went 10-10 at a major, because lower-tier teams play far more matches
// per window. The gap encodes "a team that belongs at tier 1 starts above a
// team that belongs at tier 2", which the per-result points alone cannot.
var baseRatingByTier = map[string]float64{
	"tier1": 1000,
	"tier2": 750,
	"tier3": 500,
}

const unknownTierBaseRating = 250.0

func baseRatingForTier(tier string) float64 {
	if r, ok := baseRatingByTier[tier]; ok {
		return r
	}
	return unknownTierBaseRating
}

// bestTier returns the strongest tier among a team's matches, which decides
// both its starting rating and the tier reported to the rest of the system.
func bestTier(games []teamGame) string {
	best := UnknownTier
	for _, g := range games {
		if tierRank(g.tier) < tierRank(best) {
			best = g.tier
		}
	}
	return best
}

func tierRank(tier string) int {
	switch tier {
	case "tier1":
		return 1
	case "tier2":
		return 2
	case "tier3":
		return 3
	default:
		return 4
	}
}

// Points awarded per result, by the tier of the league the match was played
// in. Each tier down halves the stake.
type tierPoints struct {
	win  float64
	loss float64
}

var pointsByTier = map[string]tierPoints{
	"tier1": {win: 50, loss: 25},
	"tier2": {win: 25, loss: 13},
	"tier3": {win: 13, loss: 7},
}

// Matches whose league tier could not be determined are scored on the same
// halving pattern, one step below tier 3.
var unknownTierPoints = tierPoints{win: 7, loss: 4}

func pointsForTier(tier string) tierPoints {
	return pointsForTierIn(pointsByTier, tier)
}

func pointsForTierIn(table map[string]tierPoints, tier string) tierPoints {
	if p, ok := table[tier]; ok {
		return p
	}
	if p, ok := table[UnknownTier]; ok {
		return p
	}
	return unknownTierPoints
}

// UnknownTier is the key used for matches whose league tier could not be
// determined, both in the points table and in incoming match data.
const UnknownTier = "unknown"

type MatchResult struct {
	RadiantTeamID int64  `json:"radiant_team_id"`
	DireTeamID    int64  `json:"dire_team_id"`
	RadiantWin    bool   `json:"radiant_win"`
	StartTime     int64  `json:"start_time"`
	LeagueTier    string `json:"league_tier"`
}

type teamGame struct {
	startTime int64
	win       bool
	tier      string
}

type teamStats struct {
	rating float64
	form   float64
	tier   string
}

func groupByTeam(matches []MatchResult) map[int64][]teamGame {
	perTeam := make(map[int64][]teamGame)
	for _, m := range matches {
		perTeam[m.RadiantTeamID] = append(
			perTeam[m.RadiantTeamID], teamGame{m.StartTime, m.RadiantWin, m.LeagueTier},
		)
		perTeam[m.DireTeamID] = append(
			perTeam[m.DireTeamID], teamGame{m.StartTime, !m.RadiantWin, m.LeagueTier},
		)
	}
	return perTeam
}

// lastN returns the tail of a time-ordered slice.
func lastN(games []teamGame, n int) []teamGame {
	if len(games) <= n {
		return games
	}
	return games[len(games)-n:]
}

// A nil table or a non-positive window mean "use the production defaults", so
// the function is correct however it is called.
func ratingFromGames(games []teamGame, table map[string]tierPoints, window int) float64 {
	if table == nil {
		table = pointsByTier
	}
	if window <= 0 {
		window = ratingWindow
	}

	rating := baseRatingForTier(bestTier(games))
	for _, g := range lastN(games, window) {
		points := pointsForTierIn(table, g.tier)
		if g.win {
			rating += points.win
		} else {
			rating -= points.loss
		}
	}
	return rating
}

func formFromGames(games []teamGame) float64 {
	recent := lastN(games, formWindow)
	if len(recent) == 0 {
		return 0.5
	}
	wins := 0
	for _, g := range recent {
		if g.win {
			wins++
		}
	}
	return float64(wins) / float64(len(recent))
}

// computeTeamStats derives each team's rating and recent form. One team's
// history is independent of every other's, so the work is fanned out across a
// pool of goroutines sized to the available CPUs.
//
// The points table and window are parameters rather than fixed constants so
// that scripts/calibrate.py can fit them on historical results; callers that
// pass nothing get the production defaults.
func computeTeamStats(
	matches []MatchResult, table map[string]tierPoints, window int,
) map[int64]teamStats {
	perTeam := groupByTeam(matches)

	type job struct {
		teamID int64
		games  []teamGame
	}
	type result struct {
		teamID int64
		stats  teamStats
	}

	jobs := make(chan job, len(perTeam))
	results := make(chan result, len(perTeam))

	workers := runtime.NumCPU()
	if workers < 1 {
		workers = 1
	}

	var wg sync.WaitGroup
	for w := 0; w < workers; w++ {
		wg.Add(1)
		go func() {
			defer wg.Done()
			for j := range jobs {
				games := j.games
				sort.Slice(games, func(a, b int) bool {
					return games[a].startTime < games[b].startTime
				})
				results <- result{j.teamID, teamStats{
					rating: ratingFromGames(games, table, window),
					form:   formFromGames(games),
					tier:   bestTier(games),
				}}
			}
		}()
	}

	for teamID, games := range perTeam {
		jobs <- job{teamID, games}
	}
	close(jobs)

	go func() {
		wg.Wait()
		close(results)
	}()

	stats := make(map[int64]teamStats, len(perTeam))
	for r := range results {
		stats[r.teamID] = r.stats
	}
	return stats
}

func clamp(x, lo, hi float64) float64 {
	if x < lo {
		return lo
	}
	if x > hi {
		return hi
	}
	return x
}

type ratingsRequest struct {
	Matches []MatchResult `json:"matches"`
	// Optional overrides used by the calibration script; empty means the
	// production defaults.
	PointsByTier map[string]tierPointsPayload `json:"points_by_tier"`
	RatingWindow int                          `json:"rating_window"`
}

type tierPointsPayload struct {
	Win  float64 `json:"win"`
	Loss float64 `json:"loss"`
}

type ratingsResponse struct {
	Ratings map[string]float64 `json:"ratings"`
	Form    map[string]float64 `json:"form"`
	// Tiers is derived here rather than by the caller so that the tier a team
	// is shown with is always the one its starting rating was based on.
	Tiers            map[string]string `json:"tiers"`
	TeamsCount       int               `json:"teams_count"`
	MatchesProcessed int               `json:"matches_processed"`
}

func ratingsHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", http.StatusMethodNotAllowed)
		return
	}
	var req ratingsRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	var table map[string]tierPoints
	if len(req.PointsByTier) > 0 {
		table = make(map[string]tierPoints, len(req.PointsByTier))
		for tier, p := range req.PointsByTier {
			table[tier] = tierPoints{win: p.Win, loss: p.Loss}
		}
	}

	stats := computeTeamStats(req.Matches, table, req.RatingWindow)

	resp := ratingsResponse{
		Ratings:          make(map[string]float64, len(stats)),
		Form:             make(map[string]float64, len(stats)),
		Tiers:            make(map[string]string, len(stats)),
		TeamsCount:       len(stats),
		MatchesProcessed: len(req.Matches),
	}
	for id, s := range stats {
		key := strconv.FormatInt(id, 10)
		resp.Ratings[key] = s.rating
		resp.Form[key] = s.form
		resp.Tiers[key] = s.tier
	}

	writeJSON(w, resp)
}

// ratingScale converts a rating gap into odds: a gap of ratingScale points
// means 10:1. Unlike chess Elo's 400, this figure is not inherent to the
// scoring system — the points above are assigned by hand — so it is fitted on
// historical results by scripts/calibrate.py (which also reports the log loss
// this value achieves). Re-run that script after changing the points table.
const ratingScale = 1000.0

// formWeight is how much of the final probability comes from recent form
// rather than the rating gap; also fitted by scripts/calibrate.py.
const formWeight = 0.1

func logistic(ratingGap, scale float64) float64 {
	return 1.0 / (1.0 + math.Pow(10, -ratingGap/scale))
}

type predictRequest struct {
	TeamARating float64 `json:"team_a_rating"`
	TeamAForm   float64 `json:"team_a_form"`
	TeamBRating float64 `json:"team_b_rating"`
	TeamBForm   float64 `json:"team_b_form"`
}

type predictResponse struct {
	TeamAWinProb    float64 `json:"team_a_win_prob"`
	RatingComponent float64 `json:"rating_component"`
	FormComponent   float64 `json:"form_component"`
}

func predictHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method != http.MethodPost {
		http.Error(w, "POST only", http.StatusMethodNotAllowed)
		return
	}
	var req predictRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		http.Error(w, err.Error(), http.StatusBadRequest)
		return
	}

	ratingComponent := logistic(req.TeamARating-req.TeamBRating, ratingScale)
	formComponent := clamp(0.5+(req.TeamAForm-req.TeamBForm)*0.5, 0, 1)
	combined := clamp(
		(1-formWeight)*ratingComponent+formWeight*formComponent, 0.01, 0.99,
	)

	writeJSON(w, predictResponse{
		TeamAWinProb:    combined,
		RatingComponent: ratingComponent,
		FormComponent:   formComponent,
	})
}

func healthHandler(w http.ResponseWriter, r *http.Request) {
	writeJSON(w, map[string]string{"status": "ok", "service": "prediction-engine"})
}

func writeJSON(w http.ResponseWriter, v any) {
	w.Header().Set("Content-Type", "application/json")
	if err := json.NewEncoder(w).Encode(v); err != nil {
		log.Printf("failed to write JSON response: %v", err)
	}
}

func main() {
	mux := http.NewServeMux()
	mux.HandleFunc("/health", healthHandler)
	mux.HandleFunc("/ratings", ratingsHandler)
	mux.HandleFunc("/predict", predictHandler)

	port := os.Getenv("PORT")
	if port == "" {
		port = "8090"
	}
	addr := ":" + port
	log.Printf("prediction-engine listening on %s", addr)
	log.Fatal(http.ListenAndServe(addr, mux))
}
