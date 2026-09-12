// Prediction engine: functional module (course requirement §2.6).
//
// Exposes an HTTP API (net/http, goroutine-per-request) that:
//   - POST /ratings — replays match history sequentially to derive Elo ratings,
//     and computes each team's recent-form win rate concurrently (worker pool
//     of goroutines, one per CPU core).
//   - POST /predict — combines the Elo rating gap and recent form into a match
//     win probability via a logistic model.
//
// Elo update is inherently sequential per team (each match changes the rating
// that the next match for that team depends on), so it runs as a single pass
// over the time-ordered match list. Recent-form aggregation, in contrast, is
// embarrassingly parallel across teams, so it is fanned out across goroutines
// via a jobs/results channel pair.
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
	initialRating = 1500.0
	kFactor       = 32.0
	formWindow    = 5
)

type MatchResult struct {
	RadiantTeamID int64 `json:"radiant_team_id"`
	DireTeamID    int64 `json:"dire_team_id"`
	RadiantWin    bool  `json:"radiant_win"`
	StartTime     int64 `json:"start_time"`
}

func expectedScore(ratingA, ratingB float64) float64 {
	return 1.0 / (1.0 + math.Pow(10, (ratingB-ratingA)/400.0))
}

// computeElo runs a single sequential pass over time-ordered matches.
func computeElo(matches []MatchResult) map[int64]float64 {
	sorted := make([]MatchResult, len(matches))
	copy(sorted, matches)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].StartTime < sorted[j].StartTime })

	ratings := make(map[int64]float64)
	getRating := func(id int64) float64 {
		if r, ok := ratings[id]; ok {
			return r
		}
		return initialRating
	}

	for _, m := range sorted {
		ra := getRating(m.RadiantTeamID)
		rb := getRating(m.DireTeamID)

		expectedRadiant := expectedScore(ra, rb)
		actualRadiant := 0.0
		if m.RadiantWin {
			actualRadiant = 1.0
		}

		ratings[m.RadiantTeamID] = ra + kFactor*(actualRadiant-expectedRadiant)
		ratings[m.DireTeamID] = rb + kFactor*((1.0-actualRadiant)-(1.0-expectedRadiant))
	}

	return ratings
}

type teamGame struct {
	startTime int64
	win       bool
}

// computeForm derives each team's win rate over its last formWindow matches.
// Teams are processed concurrently by a fixed pool of goroutines since one
// team's history is independent of another's.
func computeForm(matches []MatchResult) map[int64]float64 {
	perTeam := make(map[int64][]teamGame)
	for _, m := range matches {
		perTeam[m.RadiantTeamID] = append(perTeam[m.RadiantTeamID], teamGame{m.StartTime, m.RadiantWin})
		perTeam[m.DireTeamID] = append(perTeam[m.DireTeamID], teamGame{m.StartTime, !m.RadiantWin})
	}

	type job struct {
		teamID int64
		games  []teamGame
	}
	type result struct {
		teamID  int64
		winRate float64
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
				sort.Slice(games, func(a, b int) bool { return games[a].startTime < games[b].startTime })

				start := len(games) - formWindow
				if start < 0 {
					start = 0
				}
				recent := games[start:]

				wins := 0
				for _, g := range recent {
					if g.win {
						wins++
					}
				}
				rate := 0.5
				if len(recent) > 0 {
					rate = float64(wins) / float64(len(recent))
				}
				results <- result{j.teamID, rate}
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

	form := make(map[int64]float64)
	for r := range results {
		form[r.teamID] = r.winRate
	}
	return form
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
}

type ratingsResponse struct {
	Ratings          map[string]float64 `json:"ratings"`
	Form             map[string]float64 `json:"form"`
	TeamsCount       int                `json:"teams_count"`
	MatchesProcessed int                `json:"matches_processed"`
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

	matchesProcessed := len(req.Matches)
	form := computeForm(req.Matches)
	ratings := computeElo(req.Matches)

	resp := ratingsResponse{
		Ratings:          make(map[string]float64, len(ratings)),
		Form:             make(map[string]float64, len(form)),
		TeamsCount:       len(ratings),
		MatchesProcessed: matchesProcessed,
	}
	for id, v := range ratings {
		resp.Ratings[strconv.FormatInt(id, 10)] = v
	}
	for id, v := range form {
		resp.Form[strconv.FormatInt(id, 10)] = v
	}

	writeJSON(w, resp)
}

type predictRequest struct {
	TeamARating float64 `json:"team_a_rating"`
	TeamAForm   float64 `json:"team_a_form"`
	TeamBRating float64 `json:"team_b_rating"`
	TeamBForm   float64 `json:"team_b_form"`
}

type predictResponse struct {
	TeamAWinProb  float64 `json:"team_a_win_prob"`
	EloComponent  float64 `json:"elo_component"`
	FormComponent float64 `json:"form_component"`
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

	eloComponent := expectedScore(req.TeamARating, req.TeamBRating)
	formComponent := clamp(0.5+(req.TeamAForm-req.TeamBForm)*0.5, 0, 1)
	// Weighted blend: Elo (long-run strength) dominates, recent form nudges it.
	combined := clamp(0.7*eloComponent+0.3*formComponent, 0.01, 0.99)

	writeJSON(w, predictResponse{
		TeamAWinProb:  combined,
		EloComponent:  eloComponent,
		FormComponent: formComponent,
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
