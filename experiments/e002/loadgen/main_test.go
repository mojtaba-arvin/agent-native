package main

import (
	"encoding/json"
	"net/http"
	"net/http/httptest"
	"os"
	"path/filepath"
	"strings"
	"testing"
	"time"
)

func TestParseSettingsRejectsInvalidTargetAndConcurrency(t *testing.T) {
	cases := [][]string{
		{"--target", "file:///tmp"},
		{"--concurrency", "0"},
		{"--concurrency", "257"},
		{"--warmup", "-1"},
		{"--timeout", "0s"},
	}
	for _, args := range cases {
		if _, err := parseSettings(args); err == nil {
			t.Errorf("parseSettings(%v) unexpectedly succeeded", args)
		}
	}
}

func TestParseSettingsRequiresWarmupForWarmupOnly(t *testing.T) {
	if _, err := parseSettings([]string{"--warmup-only", "--warmup", "0"}); err == nil {
		t.Fatal("warmup-only without requests should fail")
	}
	cfg, err := parseSettings([]string{"--warmup-only", "--warmup", "3"})
	if err != nil || !cfg.warmupOnly {
		t.Fatalf("expected valid warm-up config, got %#v, %v", cfg, err)
	}
}

func TestValidRequiresExactSuccessStatusAndBody(t *testing.T) {
	validItem := observation{Status: http.StatusOK, Body: "completed:0"}
	if !valid(validItem) {
		t.Fatal("valid response was rejected")
	}
	invalid := []observation{
		{Status: http.StatusOK, Body: "completed:0\n"},
		{Status: http.StatusServiceUnavailable, Body: "completed:0"},
		{Status: http.StatusOK, Body: "wrong"},
		{Status: http.StatusOK, Body: "completed:0", Error: stringPointer("transport")},
	}
	for index, item := range invalid {
		if valid(item) {
			t.Errorf("invalid response %d was accepted", index)
		}
	}
}

func TestPercentileUsesNearestRank(t *testing.T) {
	values := []float64{4, 1, 3, 2}
	if got := percentile(values, .50); got != 2 {
		t.Fatalf("p50=%v, want 2", got)
	}
	if got := percentile(values, .99); got != 4 {
		t.Fatalf("p99=%v, want 4", got)
	}
}

func TestRunWritesRequestLevelTraceAndSummary(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.URL.Path != "/work" || r.URL.RawQuery != "ms=0" {
			http.Error(w, "unexpected request", http.StatusBadRequest)
			return
		}
		_, _ = w.Write([]byte("completed:0"))
	}))
	defer server.Close()

	prefix := filepath.Join(t.TempDir(), "run", "candidate")
	cfg := settings{
		target: server.URL, requests: 20, concurrency: 4, warmup: 5,
		timeout: 2 * time.Second, outputPrefix: prefix,
	}
	if err := run(cfg); err != nil {
		t.Fatalf("run failed: %v", err)
	}

	raw, err := os.ReadFile(prefix + ".jsonl")
	if err != nil {
		t.Fatal(err)
	}
	lines := strings.Split(strings.TrimSpace(string(raw)), "\n")
	if len(lines) != cfg.requests {
		t.Fatalf("raw trace has %d lines, want %d", len(lines), cfg.requests)
	}
	for _, line := range lines {
		var item observation
		if err := json.Unmarshal([]byte(line), &item); err != nil {
			t.Fatalf("invalid JSONL record %q: %v", line, err)
		}
		if !valid(item) {
			t.Fatalf("unexpected trace observation: %#v", item)
		}
	}
	var got summary
	data, err := os.ReadFile(prefix + ".json")
	if err != nil {
		t.Fatal(err)
	}
	if err := json.Unmarshal(data, &got); err != nil {
		t.Fatal(err)
	}
	if !got.FunctionalSuccess || got.Requests != cfg.requests || got.StatusCounts["200"] != cfg.requests {
		t.Fatalf("unexpected summary: %#v", got)
	}
}

func stringPointer(value string) *string { return &value }
