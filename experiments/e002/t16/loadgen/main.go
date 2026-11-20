// Command t16-loadgen sends the T16 product request mix at a fixed open-loop rate.
package main

import (
	"bufio"
	"context"
	"encoding/json"
	"errors"
	"flag"
	"fmt"
	"io"
	"math/rand"
	"net/http"
	"net/url"
	"os"
	"runtime"
	"path/filepath"
	"sort"
	"strconv"
	"strings"
	"sync"
	"time"
)

type operation string

const (
	authorizedRead operation = "authorized_read"
	validatePlan   operation = "validate_plan"
	jobAdmission   operation = "job_admission"
	expectedDenial operation = "expected_denial"
)

type settings struct {
	target       string
	requests     int
	concurrency  int
	warmup       int
	targetRPS    int
	timeout      time.Duration
	seed         int64
	runID        string
	readToken    string
	denyToken    string
	tenant       string
	outputPrefix string
}

type observation struct {
	Index       int       `json:"index"`
	RequestID   string    `json:"request_id"`
	Operation   operation `json:"operation"`
	Method      string    `json:"method"`
	Path        string    `json:"path"`
	TenantID    string    `json:"tenant_id"`
	AuthProfile string    `json:"auth_profile"`
	IdempotencyKey string `json:"idempotency_key,omitempty"`
	RequestBody string    `json:"request_body,omitempty"`
	Status      int       `json:"status"`
	Expected    int       `json:"expected_status"`
	LatencyMS   float64   `json:"latency_ms"`
	Completed   bool      `json:"completed"`
	Functional  bool      `json:"functional_success"`
	ResponseBody string  `json:"response_body,omitempty"`
	Error       string    `json:"error,omitempty"`
}

type summary struct {
	Target                   string             `json:"target"`
	RunID                    string             `json:"run_id"`
	Seed                     int64              `json:"seed"`
	GoVersion                string             `json:"go_version"`
	OfferedRequests          int                `json:"offered_requests"`
	CompletedRequests        int                `json:"completed_requests"`
	Concurrency              int                `json:"concurrency"`
	TargetRPS                int                `json:"target_rps"`
	WarmupRequests           int                `json:"warmup_requests"`
	ElapsedSeconds           float64            `json:"elapsed_seconds"`
	CompletedRPS             float64            `json:"completed_requests_per_second"`
	LatencyMS                map[string]float64 `json:"latency_ms"`
	OperationCounts          map[string]int     `json:"operation_counts"`
	StatusCounts             map[string]int     `json:"status_counts"`
	ExpectedDenialsCompleted int                `json:"expected_denials_completed"`
	FailedResponses          int                `json:"failed_responses"`
	FunctionalSuccess        bool               `json:"functional_success"`
	ArrivalModel             string             `json:"arrival_model"`
	ConnectionPolicy         string             `json:"connection_policy"`
}

func parseSettings(args []string) (settings, error) {
	flags := flag.NewFlagSet("t16-loadgen", flag.ContinueOnError)
	flags.SetOutput(io.Discard)
	var cfg settings
	flags.StringVar(&cfg.target, "target", "http://127.0.0.1:8080", "candidate base URL")
	flags.IntVar(&cfg.requests, "requests", 5000, "measured offered requests; must be divisible by 10")
	flags.IntVar(&cfg.concurrency, "concurrency", 32, "maximum in-flight requests")
	flags.IntVar(&cfg.warmup, "warmup", 250, "warm-up requests")
	flags.IntVar(&cfg.targetRPS, "target-rps", 100, "fixed open-loop offered rate")
	flags.DurationVar(&cfg.timeout, "timeout", 5*time.Second, "per-request timeout")
	flags.Int64Var(&cfg.seed, "seed", 20261120, "deterministic workload shuffle seed")
	flags.StringVar(&cfg.runID, "run-id", "", "unique run identifier; scopes request and idempotency keys")
	flags.StringVar(&cfg.readToken, "read-token", os.Getenv("T16_READ_TOKEN"), "authorized benchmark bearer token")
	flags.StringVar(&cfg.denyToken, "deny-token", os.Getenv("T16_DENY_TOKEN"), "insufficient-capability bearer token")
	flags.StringVar(&cfg.tenant, "tenant", "tenant-a", "trusted fixture tenant asserted by the client")
	flags.StringVar(&cfg.outputPrefix, "output-prefix", "", "output prefix for .jsonl and .json")
	if err := flags.Parse(args); err != nil {
		return settings{}, err
	}
	parsed, err := url.Parse(cfg.target)
	if err != nil || parsed.Scheme != "http" || parsed.Host == "" {
		return settings{}, errors.New("target must be an absolute HTTP URL")
	}
	if cfg.requests < 1 || cfg.requests%10 != 0 || cfg.warmup < 0 ||
		cfg.concurrency != 32 || cfg.targetRPS != 100 || cfg.timeout <= 0 {
		return settings{}, errors.New("T16 requires requests divisible by 10, concurrency 32, target-rps 100, and a positive timeout")
	}
	if cfg.runID == "" || cfg.readToken == "" || cfg.denyToken == "" || cfg.tenant == "" || cfg.outputPrefix == "" {
		return settings{}, errors.New("run-id, read-token, deny-token, tenant, and output-prefix are required")
	}
	return cfg, nil
}

func workload(count int, seed int64) []operation {
	items := make([]operation, 0, count)
	for i := 0; i < count/10; i++ {
		items = append(items,
			authorizedRead, authorizedRead, authorizedRead,
			authorizedRead, authorizedRead, authorizedRead,
			validatePlan, validatePlan, jobAdmission, expectedDenial,
		)
	}
	rand.New(rand.NewSource(seed)).Shuffle(len(items), func(i, j int) {
		items[i], items[j] = items[j], items[i]
	})
	return items
}

func buildRequest(ctx context.Context, cfg settings, runID string, index int, op operation) (*http.Request, int, error) {
	method, path, token, body, expected := http.MethodGet, "/v1/records/fixture-0001", cfg.readToken, "", http.StatusOK
	switch op {
	case authorizedRead:
	case validatePlan:
		method, path, body = http.MethodPost, "/v1/operations/validate",
			`{"contract_version":"v1","operation":"catalog.read","resource_id":"fixture-0001"}`
	case jobAdmission:
		method, path, body, expected = http.MethodPost, "/v1/jobs",
			fmt.Sprintf(`{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"t16","request_index":%d}}`, index),
			http.StatusAccepted
	case expectedDenial:
		method, path, token, body, expected = http.MethodPost, "/v1/jobs", cfg.denyToken,
			fmt.Sprintf(`{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"t16-denied","request_index":%d}}`, index),
			http.StatusForbidden
	default:
		return nil, 0, fmt.Errorf("unknown workload operation %q", op)
	}
	requestID := fmt.Sprintf("%s-%05d", runID, index)
	request, err := http.NewRequestWithContext(ctx, method, cfg.target+path, strings.NewReader(body))
	if err != nil {
		return nil, 0, err
	}
	request.Header.Set("Authorization", "Bearer "+token)
	request.Header.Set("X-Tenant-ID", cfg.tenant)
	request.Header.Set("X-Request-ID", requestID)
	request.Header.Set("Accept", "application/json")
	if body != "" {
		request.Header.Set("Content-Type", "application/json")
	}
	if op == jobAdmission || op == expectedDenial {
		request.Header.Set("Idempotency-Key", requestID)
	}
	return request, expected, nil
}

func newClient(timeout time.Duration, concurrency int) *http.Client {
	return &http.Client{
		Transport: &http.Transport{
			DisableKeepAlives: true,
			MaxConnsPerHost: concurrency,
		},
		Timeout: timeout,
	}
}

func sendOne(client *http.Client, cfg settings, runID string, index int, op operation) observation {
	started := time.Now()
	ctx, cancel := context.WithTimeout(context.Background(), cfg.timeout)
	defer cancel()
	request, expected, err := buildRequest(ctx, cfg, runID, index, op)
	item := observation{Index: index, RequestID: fmt.Sprintf("%s-%05d", runID, index), Operation: op, Expected: expected}
	if err != nil {
		item.Error = err.Error()
		item.LatencyMS = float64(time.Since(started).Nanoseconds()) / 1e6
		return item
	}
	item.Method, item.Path = request.Method, request.URL.Path
	item.TenantID = cfg.tenant
	if op == expectedDenial {
		item.AuthProfile = "insufficient_capability"
	} else {
		item.AuthProfile = "authorized_benchmark_principal"
	}
	item.IdempotencyKey = request.Header.Get("Idempotency-Key")
	if bodyReader, bodyErr := request.GetBody(); bodyErr == nil {
		if requestBody, readErr := io.ReadAll(bodyReader); readErr == nil {
			item.RequestBody = string(requestBody)
		}
	}
	response, err := client.Do(request)
	if err != nil {
		item.Error = err.Error()
		item.LatencyMS = float64(time.Since(started).Nanoseconds()) / 1e6
		return item
	}
	defer response.Body.Close()
	body, readErr := io.ReadAll(io.LimitReader(response.Body, 65537))
	item.Status = response.StatusCode
	item.Completed = readErr == nil
	if readErr != nil {
		item.Error = readErr.Error()
	}
	item.ResponseBody = string(body)
	item.Functional = item.Completed && item.Status == expected && validateResponse(op, item.RequestID, item.ResponseBody)
	item.LatencyMS = float64(time.Since(started).Nanoseconds()) / 1e6
	return item
}

func validateResponse(op operation, requestID, body string) bool {
	var envelope map[string]any
	if err := json.Unmarshal([]byte(body), &envelope); err != nil {
		return false
	}
	if envelope["request_id"] != requestID {
		return false
	}
	switch op {
	case authorizedRead:
		data, ok := envelope["data"].(map[string]any)
		return ok && data["id"] == "fixture-0001"
	case validatePlan:
		return envelope["decision"] == "allow"
	case jobAdmission:
		return envelope["status"] == "queued" && nonEmptyString(envelope["job_id"])
	case expectedDenial:
		err, ok := envelope["error"].(map[string]any)
		return ok && err["code"] == "CAPABILITY_DENIED"
	default:
		return false
	}
}

func nonEmptyString(value any) bool {
	text, ok := value.(string)
	return ok && text != ""
}

func execute(cfg settings, client *http.Client, runID string, count int, seed int64) ([]observation, float64) {
	ops := workload(count, seed)
	started := time.Now()
	results := make(chan observation, count)
	slots := make(chan struct{}, cfg.concurrency)
	var workers sync.WaitGroup
	for index, op := range ops {
		due := started.Add(time.Duration(index) * time.Second / time.Duration(cfg.targetRPS))
		if wait := time.Until(due); wait > 0 {
			time.Sleep(wait)
		}
		select {
		case slots <- struct{}{}:
			workers.Add(1)
			go func(i int, operation operation) {
				defer workers.Done()
				defer func() { <-slots }()
				results <- sendOne(client, cfg, runID, i, operation)
			}(index, op)
		default:
			results <- observation{
				Index: index, RequestID: fmt.Sprintf("%s-%05d", runID, index),
				Operation: op, Error: "client_concurrency_limit", Functional: false,
			}
		}
	}
	workers.Wait()
	close(results)
	items := make([]observation, 0, count)
	for item := range results {
		items = append(items, item)
	}
	sort.Slice(items, func(i, j int) bool { return items[i].Index < items[j].Index })
	return items, time.Since(started).Seconds()
}

func percentile(values []float64, p float64) float64 {
	if len(values) == 0 {
		return 0
	}
	sort.Float64s(values)
	index := int(float64(len(values)-1) * p)
	return values[index]
}

func summarize(cfg settings, runID string, items []observation, elapsed float64) summary {
	latencies := make([]float64, 0, len(items))
	operations, statuses := map[string]int{}, map[string]int{}
	completed, denials, failures := 0, 0, 0
	for _, item := range items {
		operations[string(item.Operation)]++
		if item.Completed {
			completed++
			statuses[strconv.Itoa(item.Status)]++
			latencies = append(latencies, item.LatencyMS)
			if item.Operation == expectedDenial && item.Functional {
				denials++
			}
		} else {
			statuses["not_completed"]++
		}
		if !item.Functional {
			failures++
		}
	}
	rate := 0.0
	if elapsed > 0 {
		rate = float64(completed) / elapsed
	}
	return summary{
		Target: cfg.target, RunID: runID, Seed: cfg.seed, GoVersion: runtime.Version(),
		OfferedRequests: len(items), CompletedRequests: completed,
		Concurrency: cfg.concurrency, TargetRPS: cfg.targetRPS, WarmupRequests: cfg.warmup,
		ElapsedSeconds: elapsed, CompletedRPS: rate,
		LatencyMS: map[string]float64{
			"p50": percentile(append([]float64(nil), latencies...), .50),
			"p95": percentile(append([]float64(nil), latencies...), .95),
			"p99": percentile(append([]float64(nil), latencies...), .99),
			"max": percentile(append([]float64(nil), latencies...), 1),
		},
		OperationCounts: operations, StatusCounts: statuses,
		ExpectedDenialsCompleted: denials, FailedResponses: failures,
		FunctionalSuccess: failures == 0 && len(items) == cfg.requests && completed == cfg.requests,
		ArrivalModel: "open_loop_fixed_rate",
		ConnectionPolicy: "one HTTP/1.1 connection per request; keep-alive disabled",
	}
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
		warm, _ := execute(cfg, client, cfg.runID+"-warmup", cfg.warmup, cfg.seed)
		for _, item := range warm {
			if !item.Functional {
				return fmt.Errorf("warm-up request %d failed: status=%d expected=%d error=%s", item.Index, item.Status, item.Expected, item.Error)
			}
		}
	}
	items, elapsed := execute(cfg, client, cfg.runID, cfg.requests, cfg.seed)
	result := summarize(cfg, cfg.runID, items, elapsed)
	if err := writeOutput(cfg.outputPrefix, items, result); err != nil {
		return err
	}
	encoded, _ := json.Marshal(result)
	fmt.Println(string(encoded))
	if !result.FunctionalSuccess {
		return fmt.Errorf("T16 workload failed: %d completed/%d offered; %d functional failures",
			result.CompletedRequests, result.OfferedRequests, result.FailedResponses)
	}
	return nil
}

func main() {
	cfg, err := parseSettings(os.Args[1:])
	if err == nil {
		err = run(cfg)
	}
	if err != nil {
		fmt.Fprintln(os.Stderr, "t16-loadgen:", err)
		os.Exit(2)
	}
}
