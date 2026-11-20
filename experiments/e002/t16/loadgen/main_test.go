package main

import (
	"context"
	"fmt"
	"net/http"
	"net/http/httptest"
	"testing"
	"time"
)

func testSettings() settings {
	return settings{
		target: "http://127.0.0.1:8080", requests: 5000, concurrency: 32,
		warmup: 250, targetRPS: 100, timeout: time.Second, seed: 42,
		runID: "rep-01", readToken: "read-secret", denyToken: "deny-secret",
		tenant: "tenant-a", outputPrefix: "/tmp/t16",
	}
}

func TestWorkloadHasExactRequestMixAndIsDeterministic(t *testing.T) {
	first, second := workload(5000, 20261120), workload(5000, 20261120)
	counts := map[operation]int{}
	for i, op := range first {
		counts[op]++
		if op != second[i] {
			t.Fatal("same seed produced a different request sequence")
		}
	}
	want := map[operation]int{
		authorizedRead: 3000, validatePlan: 1000,
		jobAdmission: 500, expectedDenial: 500,
	}
	for op, count := range want {
		if counts[op] != count {
			t.Errorf("%s count = %d, want %d", op, counts[op], count)
		}
	}
}

func TestBuildRequestUsesTrustedFixtureHeadersAndExpectedStatuses(t *testing.T) {
	cfg := testSettings()
	cases := []struct {
		op operation
		method string
		path string
		token string
		status int
	}{
		{authorizedRead, http.MethodGet, "/v1/records/fixture-0001", "Bearer read-secret", http.StatusOK},
		{validatePlan, http.MethodPost, "/v1/operations/validate", "Bearer read-secret", http.StatusOK},
		{jobAdmission, http.MethodPost, "/v1/jobs", "Bearer read-secret", http.StatusAccepted},
		{expectedDenial, http.MethodPost, "/v1/jobs", "Bearer deny-secret", http.StatusForbidden},
	}
	for index, test := range cases {
		request, expected, err := buildRequest(context.Background(), cfg, "rep-01", index, test.op)
		if err != nil { t.Fatal(err) }
		if request.Method != test.method || request.URL.Path != test.path {
			t.Errorf("%s route = %s %s", test.op, request.Method, request.URL.Path)
		}
		if request.Header.Get("Authorization") != test.token {
			t.Errorf("%s bearer fixture mismatch", test.op)
		}
		if request.Header.Get("X-Tenant-ID") != "tenant-a" || request.Header.Get("X-Request-ID") == "" {
			t.Errorf("%s missing tenant/request identity headers", test.op)
		}
		if expected != test.status { t.Errorf("%s expected status = %d", test.op, expected) }
		if (test.op == jobAdmission || test.op == expectedDenial) && request.Header.Get("Idempotency-Key") == "" {
			t.Errorf("%s missing idempotency key", test.op)
		}
	}
}

func TestExpectedDenialIsCompletedFunctionalOutcome(t *testing.T) {
	server := httptest.NewServer(http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		if r.Header.Get("Authorization") != "Bearer deny-secret" {
			t.Errorf("unexpected denial credential")
		}
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusForbidden)
		_, _ = fmt.Fprint(w, `{"request_id":"rep-01-00001","error":{"code":"CAPABILITY_DENIED"}}`)
	}))
	defer server.Close()
	cfg := testSettings()
	cfg.target = server.URL
	base := time.Now()
	item := sendOne(server.Client(), cfg, "rep-01", 1, expectedDenial, base, base, base)
	if !item.Completed || !item.Functional || item.Status != http.StatusForbidden ||
		item.OfferedAt == "" || item.StartedAt == "" || item.FinishedAt == "" || item.ScheduledOffsetMS != 0 {
		t.Fatalf("expected 403 denial should be a completed functional response: %+v", item)
	}
}


func TestValidateResponseRequiresOperationSpecificEnvelope(t *testing.T) {
	requestID := "rep-02-00017"
	cases := []struct {
		op operation
		body string
		want bool
	}{
		{authorizedRead, `{"request_id":"rep-02-00017","data":{"id":"fixture-0001"}}`, true},
		{validatePlan, `{"request_id":"rep-02-00017","decision":"allow"}`, true},
		{jobAdmission, `{"request_id":"rep-02-00017","job_id":"job-1","status":"queued"}`, true},
		{expectedDenial, `{"request_id":"rep-02-00017","error":{"code":"CAPABILITY_DENIED"}}`, true},
		{authorizedRead, `{"request_id":"other","data":{"id":"fixture-0001"}}`, false},
		{expectedDenial, `{"request_id":"rep-02-00017","error":{"code":"INTERNAL_ERROR"}}`, false},
		{jobAdmission, `{"request_id":"rep-02-00017","job_id":"","status":"queued"}`, false},
	}
	for _, test := range cases {
		if got := validateResponse(test.op, requestID, test.body); got != test.want {
			t.Errorf("%s validateResponse() = %v, want %v", test.op, got, test.want)
		}
	}
}

func TestOpenLoopSummarySeparatesOfferedAndCompleted(t *testing.T) {
	cfg := testSettings()
	items := []observation{
		{Operation: authorizedRead, Status: 200, Completed: true, Functional: true, LatencyMS: 5},
		{Operation: expectedDenial, Status: 403, Completed: true, Functional: true, LatencyMS: 7},
		{Operation: jobAdmission, Error: "client_concurrency_limit"},
	}
	got := summarize(cfg, "rep-01", items, 0.02)
	if got.OfferedRequests != 3 || got.CompletedRequests != 2 || got.ExpectedDenialsCompleted != 1 {
		t.Fatalf("incorrect offered/completed accounting: %+v", got)
	}
	if got.FunctionalSuccess || got.ArrivalModel != "open_loop_fixed_rate" {
		t.Fatalf("incorrect failure or arrival-model accounting: %+v", got)
	}
}

func TestNewClientReusesHTTPConnectionsWithinConcurrencyLimit(t *testing.T) {
	client := newClient(time.Second, 32)
	defer client.CloseIdleConnections()
	transport, ok := client.Transport.(*http.Transport)
	if !ok {
		t.Fatal("client transport is not an HTTP transport")
	}
	if transport.DisableKeepAlives || transport.MaxConnsPerHost != 32 ||
		transport.MaxIdleConnsPerHost != 32 {
		t.Fatalf("unexpected connection policy: %+v", transport)
	}
}
