package main

import (
	"math"
	"testing"
)

func TestEloFavorsWinner(t *testing.T) {
	matches := []MatchResult{
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: true, StartTime: 100},
	}
	ratings := computeElo(matches, nil)
	if ratings[1] <= initialRating {
		t.Errorf("expected winner rating > %v, got %v", initialRating, ratings[1])
	}
	if ratings[2] >= initialRating {
		t.Errorf("expected loser rating < %v, got %v", initialRating, ratings[2])
	}
}

func TestEloUsesInitialRatingSeed(t *testing.T) {
	matches := []MatchResult{
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: true, StartTime: 100},
	}
	seeded := computeElo(matches, map[int64]float64{1: 1800, 2: 1800})
	unseeded := computeElo(matches, nil)
	if seeded[1] <= unseeded[1] {
		t.Errorf("expected a higher seed to carry through to the post-match rating: seeded=%v unseeded=%v", seeded[1], unseeded[1])
	}
}

func TestExpectedScoreSymmetric(t *testing.T) {
	a := expectedScore(1600, 1400)
	b := expectedScore(1400, 1600)
	if math.Abs(a+b-1.0) > 1e-9 {
		t.Errorf("expected scores to sum to 1, got %v + %v = %v", a, b, a+b)
	}
}

func TestComputeFormRecentWindow(t *testing.T) {
	matches := []MatchResult{
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: true, StartTime: 1},
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: true, StartTime: 2},
		{RadiantTeamID: 1, DireTeamID: 2, RadiantWin: false, StartTime: 3},
	}
	form := computeForm(matches)
	if form[1] != 2.0/3.0 {
		t.Errorf("expected team 1 form 2/3, got %v", form[1])
	}
	if form[2] != 1.0/3.0 {
		t.Errorf("expected team 2 form 1/3, got %v", form[2])
	}
}
