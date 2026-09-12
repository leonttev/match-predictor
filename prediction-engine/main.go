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
	// Kept deliberately low: the ingested match sample is small and often
	// dominated by a single low-tier qualifier bracket running "right now",
	// disconnected from the wider pro scene. A high K-factor lets a team
	// snowball a large rating swing off just 3-4 wins inside that isolated
	// bracket, which can push it above seeded elite teams that simply
	// haven't played within the sampled window. A low K-factor keeps each
	// team's seeded (OpenDota long-history) rating dominant and lets
	// observed matches nudge it rather than override it.
	kFactor    = 8.0
	formWindow = 5
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
// initialRatings seeds teams that have a known prior strength (e.g. from
// OpenDota's own long-history rating) instead of starting everyone at a flat
// initialRating — without this, a team that hasn't played within the ingested
// match window stays parked at 1500 while a team that went on a short win
// streak in a handful of low-tier qualifier matches can rank above it, which
// inverts the real strength ordering.
func computeElo(matches []MatchResult, initialRatings map[int64]float64) map[int64]float64 {
	sorted := make([]MatchResult, len(matches))
	copy(sorted, matches)
	sort.Slice(sorted, func(i, j int) bool { return sorted[i].StartTime < sorted[j].StartTime })

	ratings := make(map[int64]float64)
	getRating := func(id int64) float64 {
		if r, ok := ratings[id]; ok {
			return r
		}
		if r, ok := initialRatings[id]; ok {
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
	// InitialRatings seeds specific teams (keyed by team id as a string,
	// since JSON object keys are always strings) with a known prior rating
	// instead of the flat default. Teams not present here still start at
	// initialRating.
	InitialRatings map[string]float64 `json:"initial_ratings"`
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

	initialRatings := make(map[int64]float64, len(req.InitialRatings))
	for idStr, rating := range req.InitialRatings {
		id, err := strconv.ParseInt(idStr, 10, 64)
		if err != nil {
			continue
		}
		initialRatings[id] = rating
	}
	ratings := computeElo(req.Matches, initialRatings)

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
	TeamATier   string  `json:"team_a_tier"`
	TeamBRating float64 `json:"team_b_rating"`
	TeamBForm   float64 `json:"team_b_form"`
	TeamBTier   string  `json:"team_b_tier"`
}

type predictResponse struct {
	TeamAWinProb   float64 `json:"team_a_win_prob"`
	EloComponent   float64 `json:"elo_component"`
	FormComponent  float64 `json:"form_component"`
	TierAdjustment float64 `json:"tier_adjustment"`
}

// Elo points earned inside a tier-2 bracket are not worth the same as points
// earned at a tier-1 event: the two pools barely play each other, so their
// ratings drift apart independently (the classic disconnected-rating-pool
// problem). Each tier step therefore shifts a team's effective rating before
// the logistic is applied. Without this, a tier-1 team on a bad run at a major
// is predicted to lose to a tier-2 team that went undefeated in a qualifier.
const tierOffsetStep = 150.0

func tierRank(tier string) int {
	switch tier {
	case "tier1":
		return 1
	case "tier2":
		return 2
	case "tier3":
		return 3
	default: // "unknown" — no observed tier-level play
		return 4
	}
}

func tierOffset(tier string) float64 {
	return float64(4-tierRank(tier)) * tierOffsetStep
}

// Recent form is only directly comparable within a tier: going 5-0 in a
// tier-2 qualifier is not the same achievement as going 5-0 at a tier-1
// major, and a tier-1 team's 0-5 run came against tier-1 opposition. The
// further apart the two tiers are, the less the form gap between them is
// allowed to move the prediction.
func formShrink(tierA, tierB string) float64 {
	distance := tierRank(tierA) - tierRank(tierB)
	if distance < 0 {
		distance = -distance
	}
	return 1.0 / (1.0 + float64(distance))
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

	tierAdjustment := tierOffset(req.TeamATier) - tierOffset(req.TeamBTier)
	eloComponent := expectedScore(req.TeamARating+tierAdjustment, req.TeamBRating)

	shrink := formShrink(req.TeamATier, req.TeamBTier)
	formComponent := clamp(0.5+(req.TeamAForm-req.TeamBForm)*0.5*shrink, 0, 1)
	// Weighted blend: Elo (long-run strength) dominates, recent form nudges it.
	combined := clamp(0.7*eloComponent+0.3*formComponent, 0.01, 0.99)

	writeJSON(w, predictResponse{
		TeamAWinProb:   combined,
		EloComponent:   eloComponent,
		FormComponent:  formComponent,
		TierAdjustment: tierAdjustment,
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
