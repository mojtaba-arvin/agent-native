// Command loadgen is the non-Python HTTP load generator for E-002.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math"
	"net/http"
	"net/url"
	"os"
	"path/filepath"
	"runtime"
	"sort"
	"strconv"
	"sync"
	"time"
)

type observation struct {
	Index     int     `json:"index"`
	Status    int     `json:"status"`
	LatencyMS float64 `json:"latency_ms"`
	Body      string  `json:"body"`
	Error     *string `json:"error"`
}

type summary struct {
	Target                   string             `json:"target"`
	GoVersion                string             `json:"go_version"`
	Requests                 int                `json:"requests"`
	Concurrency              int                `json:"concurrency"`
	Warmup                   int                `json:"warmup"`
	ElapsedSeconds           float64            `json:"elapsed_seconds"`
	ThroughputRequestsPerSec float64            `json:"throughput_requests_per_second"`
	LatencyMS                map[string]float64 `json:"latency_ms"`
	StatusCounts             map[string]int     `json:"status_counts"`
	FailedResponseCount      int                `json:"failed_response_count"`
	FunctionalSuccess        bool               `json:"functional_success"`
	ConnectionPolicy         string             `json:"connection_policy"`
}

type settings struct {
	target       string
	requests     int
	concurrency  int
	warmup       int
	timeout      time.Duration
	outputPrefix string
	warmupOnly   bool
}

func parseSettings(args []string) (settings, error) {
	flags := flag.NewFlagSet("e002-loadgen", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	var cfg settings
	flags.StringVar(&cfg.target, "target", "http://127.0.0.1:8080", "candidate base URL")
	flags.IntVar(&cfg.requests, "requests", 5000, "number of measured requests")
	flags.IntVar(&cfg.concurrency, "concurrency", 32, "maximum in-flight requests")
	flags.IntVar(&cfg.warmup, "warmup", 250, "successful warm-up requests")
	flags.DurationVar(&cfg.timeout, "timeout", 5*time.Second, "per-request timeout")
	flags.StringVar(&cfg.outputPrefix, "output-prefix", "", "output prefix for .jsonl and .json")
	flags.BoolVar(&cfg.warmupOnly, "warmup-only", false, "run warm-up requests only")
	if err := flags.Parse(args); err != nil {
		return settings{}, err
	}
	parsed, err := url.Parse(cfg.target)
	if err != nil || parsed.Scheme != "http" || parsed.Host == "" {
		return settings{}, errors.New("target must be an absolute HTTP URL")
	}
	if cfg.concurrency < 1 || cfg.concurrency > 256 || cfg.warmup < 0 || cfg.timeout <= 0 {
		return settings{}, errors.New("concurrency, warmup, or timeout is outside the supported range")
	}
	if cfg.warmupOnly {
		if cfg.warmup < 1 {
			return settings{}, errors.New("warmup-only requires at least one warm-up request")
		}
	} else if cfg.requests < 1 || cfg.outputPrefix == "" {
		return settings{}, errors.New("measured runs require positive requests and --output-prefix")
	}
	return cfg, nil
}

func newClient(timeout time.Duration, concurrency int) *http.Client {
	transport := &http.Transport{
		DisableKeepAlives:   true,
		MaxConnsPerHost:     concurrency,
		MaxIdleConns:        concurrency,
		MaxIdleConnsPerHost: concurrency,
	}
	return &http.Client{Transport: transport, Timeout: timeout}
}

func one(ctx context.Context, client *http.Client, target string, index int) observation {
	started := time.Now()
	request, err := http.NewRequestWithContext(ctx, http.MethodGet, target+"/work?ms=0", nil)
	if err != nil {
		message := err.Error()
		return observation{Index: index, LatencyMS: float64(time.Since(started).Nanoseconds()) / 1e6, Error: &message}
	}
	response, err := client.Do(request)
	if err != nil {
		message := err.Error()
		latency := float64(time.Since(started).Nanoseconds()) / 1e6
		return observation{Index: index, LatencyMS: latency, Error: &message}
	}
	defer response.Body.Close()
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 4097))
	latency := float64(time.Since(started).Nanoseconds()) / 1e6
	if readErr != nil {
		message := readErr.Error()
		return observation{Index: index, Status: response.StatusCode, LatencyMS: latency, Error: &message}
	}
	return observation{Index: index, Status: response.StatusCode, LatencyMS: latency, Body: string(body)}
}

func execute(ctx context.Context, client *http.Client, target string, count, concurrency int) []observation {
	jobs := make(chan int)
	results := make(chan observation, concurrency)
	var workers sync.WaitGroup
	workers.Add(concurrency)
	for worker := 0; worker < concurrency; worker++ {
		go func() {
			defer workers.Done()
			for index := range jobs {
				results <- one(ctx, client, target, index)
			}
		}()
	}
	go func() {
		for index := 0; index < count; index++ {
			jobs <- index
		}
		close(jobs)
		workers.Wait()
		close(results)
	}()
	items := make([]observation, 0, count)
	for item := range results {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Index < items[j].Index })
	return items
}

func percentile(values []float64, p float64) float64 {
	if len(values) == 0 {
		return 0
	}
	ordered := append([]float64(nil), values...)
	sort.Float64s(ordered)
	index := int(math.Ceil(p*float64(len(ordered)))) - 1
	if index < 0 {
		index = 0
	}
	if index >= len(ordered) {
		index = len(ordered) - 1
	}
	return ordered[index]
}

func valid(item observation) bool {
	return item.Error == nil && item.Status == http.StatusOK && item.Body == "completed:0"
}

func writeOutput(prefix string, items []observation, result summary) error {
	if err := os.MkdirAll(filepath.Dir(prefix), 0o755); err != nil {
		return err
	}
	raw, err := os.Create(prefix + ".jsonl")
	if err != nil {
		return err
	}
	writer := bufio.NewWriter(raw)
	encoder := json.NewEncoder(writer)
	for _, item := range items {
		if err := encoder.Encode(item); err != nil {
			_ = raw.Close()
			return err
		}
	}
	if err := writer.Flush(); err != nil {
		_ = raw.Close()
		return err
	}
	if err := raw.Close(); err != nil {
		return err
	}
	data, err := json.MarshalIndent(result, "", "  ")
	if err != nil {
		return err
	}
	return os.WriteFile(prefix+".json", append(data, '\n'), 0o644)
}

func run(cfg settings) error {
	client := newClient(cfg.timeout, cfg.concurrency)
	defer client.CloseIdleConnections()
	if cfg.warmup > 0 {
		warm := execute(context.Background(), client, cfg.target, cfg.warmup, cfg.concurrency)
		for _, item := range warm {
			if !valid(item) {
				return fmt.Errorf("warm-up request %d failed: status=%d body=%q error=%v", item.Index, item.Status, item.Body, item.Error)
			}
		}
	}
	if cfg.warmupOnly {
		return nil
	}

	started := time.Now()
	items := execute(context.Background(), client, cfg.target, cfg.requests, cfg.concurrency)
	elapsed := time.Since(started).Seconds()
	latencies := make([]float64, 0, len(items))
	statuses := make(map[string]int)
	failures := 0
	for _, item := range items {
		latencies = append(latencies, item.LatencyMS)
		key := strconv.Itoa(item.Status)
		if item.Error != nil {
			key = "transport_error"
		}
		statuses[key]++
		if !valid(item) {
			failures++
		}
	}
	result := summary{
		Target:                   cfg.target,
		GoVersion:                runtime.Version(),
		Requests:                 len(items),
		Concurrency:              cfg.concurrency,
		Warmup:                   cfg.warmup,
		ElapsedSeconds:           elapsed,
		ThroughputRequestsPerSec: float64(len(items)) / elapsed,
		LatencyMS: map[string]float64{
			"p50": percentile(latencies, 0.50),
			"p95": percentile(latencies, 0.95),
			"p99": percentile(latencies, 0.99),
			"max": percentile(latencies, 1.0),
		},
		StatusCounts:        statuses,
		FailedResponseCount: failures,
		FunctionalSuccess:   failures == 0 && len(items) == cfg.requests,
		ConnectionPolicy:    "one HTTP/1.1 connection per request; keep-alive disabled for all candidates",
	}
	if err := writeOutput(cfg.outputPrefix, items, result); err != nil {
		return err
	}
	if !result.FunctionalSuccess {
		return fmt.Errorf("measurement had %d failed responses out of %d", failures, cfg.requests)
	}
	encoded, _ := json.Marshal(result)
	fmt.Println(string(encoded))
	return nil
}

func main() {
	cfg, err := parseSettings(os.Args[1:])
	if errors.Is(err, flag.ErrHelp) {
		fmt.Println("usage: e002-loadgen --target http://127.0.0.1:8080 --requests 5000 --concurrency 32 --warmup 250 --output-prefix PATH")
		return
	}
	if err == nil {
		err = run(cfg)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "e002-loadgen:", err)
		os.Exit(2)
	}
}
