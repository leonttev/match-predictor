package main

import (
	"math"
	"testing"
)

func ratingOf(games []teamGame) float64 {
	return ratingFromGames(games, nil, 0)
}

func TestTierPointsAreAwardedAsSpecified(t *testing.T) {
	cases := []struct {
		tier     string
		wantWin  float64
		wantLoss float64
	}{
		{"tier1", 1000 + 50, 1000 - 25},
		{"tier2", 750 + 25, 750 - 13},
		{"tier3", 500 + 13, 500 - 7},
		{UnknownTier, 250 + 7, 250 - 4},
	}

	for _, c := range cases {
		won := ratingOf([]teamGame{{startTime: 1, win: true, tier: c.tier}})
		lost := ratingOf([]teamGame{{startTime: 1, win: false, tier: c.tier}})
		if won != c.wantWin {
			t.Errorf("%s win: expected %v, got %v", c.tier, c.wantWin, won)
		}
		if lost != c.wantLoss {
			t.Errorf("%s loss: expected %v, got %v", c.tier, c.wantLoss, lost)
		}
	}
}

func TestHigherTierResultsAreWorthMore(t *testing.T) {
	tiers := []string{"tier1", "tier2", "tier3", UnknownTier}
	for i := 0; i < len(tiers)-1; i++ {
		higher, lower := pointsForTier(tiers[i]), pointsForTier(tiers[i+1])
		if higher.win <= lower.win {
			t.Errorf("expected %s win > %s win, got %v vs %v",
				tiers[i], tiers[i+1], higher.win, lower.win)
		}
		if higher.loss <= lower.loss {
			t.Errorf("expected %s loss penalty > %s, got %v vs %v",
				tiers[i], tiers[i+1], higher.loss, lower.loss)
		}
	}
}

func TestStartingRatingFallsWithTier(t *testing.T) {
	tiers := []string{"tier1", "tier2", "tier3", UnknownTier}
	for i := 0; i < len(tiers)-1; i++ {
		higher, lower := baseRatingForTier(tiers[i]), baseRatingForTier(tiers[i+1])
		if higher <= lower {
			t.Errorf("expected %s to start above %s, got %v vs %v",
				tiers[i], tiers[i+1], higher, lower)
		}
	}
}

func TestTierBaseKeepsAQualifierSweepBelowATierOneTeam(t *testing.T) {
	// The regression this rule exists for: a tier-2 team sweeping a full
	// window of qualifier matches must not outrank a tier-1 team with a
	// middling record at a major.
	sweep := make([]teamGame, 0, ratingWindow)
	for i := 0; i < ratingWindow; i++ {
		sweep = append(sweep, teamGame{startTime: int64(i), win: true, tier: "tier2"})
	}

	middling := make([]teamGame, 0, ratingWindow)
	for i := 0; i < ratingWindow; i++ {
		middling = append(middling, teamGame{startTime: int64(i), win: i%2 == 0, tier: "tier1"})
	}

	if ratingOf(sweep) > ratingOf(middling) {
		t.Errorf("tier-2 sweep (%v) should not outrank a .500 tier-1 team (%v)",
			ratingOf(sweep), ratingOf(middling))
	}
}

func TestBestTierPicksTheStrongestObserved(t *testing.T) {
	games := []teamGame{
		{startTime: 1, win: true, tier: "tier3"},
		{startTime: 2, win: false, tier: "tier1"},
		{startTime: 3, win: true, tier: "tier2"},
	}
	if got := bestTier(games); got != "tier1" {
		t.Errorf("expected tier1, got %v", got)
	}
	if got := bestTier(nil); got != UnknownTier {
		t.Errorf("expected %v with no matches, got %v", UnknownTier, got)
	}
}

func TestRatingIsOrderIndependentWithinWindow(t *testing.T) {
	// The window sums points, so shuffling results inside it must not change
	// the rating — time order only decides which matches fall in the window.
	forward := ratingOf([]teamGame{
		{startTime: 1, win: true, tier: "tier1"},
		{startTime: 2, win: false, tier: "tier2"},
		{startTime: 3, win: true, tier: "tier3"},
	})
	reordered := ratingOf([]teamGame{
		{startTime: 1, win: true, tier: "tier3"},
		{startTime: 2, win: true, tier: "tier1"},
		{startTime: 3, win: false, tier: "tier2"},
	})
	if forward != reordered {
		t.Errorf("expected an order-independent sum, got %v vs %v", forward, reordered)
	}
}

func TestRatingCountsOnlyTheMostRecentWindow(t *testing.T) {
	// One more win than the window holds: the oldest must fall out, capping
	// the rating at exactly ratingWindow tier-1 wins.
	games := make([]teamGame, 0, ratingWindow+1)
	for i := 0; i <= ratingWindow; i++ {
		games = append(games, teamGame{startTime: int64(i), win: true, tier: "tier1"})
	}
	want := baseRatingForTier("tier1") + float64(ratingWindow)*pointsForTier("tier1").win
	if got := ratingOf(games); got != want {
		t.Errorf("expected the window to cap the rating at %v, got %v", want, got)
	}
}

func TestRatingHonoursOverriddenPointsAndWindow(t *testing.T) {
	// The calibration script fits these, so overrides must actually apply.
	games := []teamGame{
		{startTime: 1, win: true, tier: "tier1"},
		{startTime: 2, win: true, tier: "tier1"},
	}
	table := map[string]tierPoints{"tier1": {win: 100, loss: 100}}

	if got := ratingFromGames(games, table, 0); got != baseRatingForTier("tier1")+200 {
		t.Errorf("expected overridden points to apply, got %v", got)
	}
	if got := ratingFromGames(games, table, 1); got != baseRatingForTier("tier1")+100 {
		t.Errorf("expected overridden window to apply, got %v", got)
	}
}

func TestComputeTeamStatsScoresBothSides(t *testing.T) {
	matches := []MatchResult{
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: true, StartTime: 1, LeagueTier: "tier1"},
	}
	stats := computeTeamStats(matches, nil, 0)
	if stats[1].rating != 1000+50 {
		t.Errorf("expected the winner at %v, got %v", 1000+50, stats[1].rating)
	}
	if stats[2].rating != 1000-25 {
		t.Errorf("expected the loser at %v, got %v", 1000-25, stats[2].rating)
	}
}

func TestFormUsesRecentWindow(t *testing.T) {
	matches := []MatchResult{
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: true, StartTime: 1, LeagueTier: "tier1"},
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: true, StartTime: 2, LeagueTier: "tier1"},
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: false, StartTime: 3, LeagueTier: "tier1"},
	}
	stats := computeTeamStats(matches, nil, 0)
	if stats[1].form != 2.0/3.0 {
		t.Errorf("expected team 1 form 2/3, got %v", stats[1].form)
	}
	if stats[2].form != 1.0/3.0 {
		t.Errorf("expected team 2 form 1/3, got %v", stats[2].form)
	}
}

func TestLogisticIsSymmetricAndNeutralAtEqualRatings(t *testing.T) {
	if p := logistic(0, ratingScale); p != 0.5 {
		t.Errorf("expected 50%% at equal ratings, got %v", p)
	}
	a, b := logistic(120, ratingScale), logistic(-120, ratingScale)
	if math.Abs(a+b-1.0) > 1e-9 {
		t.Errorf("expected probabilities to sum to 1, got %v + %v", a, b)
	}
	if a <= 0.5 {
		t.Errorf("expected the higher-rated team to be favoured, got %v", a)
	}
}
