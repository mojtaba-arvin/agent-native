package main

import (
	"net/http"
	"net/http/httptest"
	"os"
	"strings"
	"testing"
)

func TestT16ProductRoutesUseAuthenticatedPostgresContract(t *testing.T) {
	dsn := os.Getenv("T16_PSQL_DSN")
	if dsn == "" {
		t.Skip("requires T16_PSQL_DSN and psql client")
	}
	t.Setenv("T16_READ_TOKEN", "test-read-token")
	t.Setenv("T16_DENY_TOKEN", "test-deny-token")
	t.Setenv("T16_TENANT_ID", "tenant-a")
	product, err := newProductServiceFromEnv()
	if err != nil {
		t.Fatal(err)
	}
	defer product.pool.close()
	handler := newHandler(maxConcurrent, workDeadline)
	handler.(*application).product = product

	request := func(method, path, token, requestID, body string) *httptest.ResponseRecorder {
		recorder := httptest.NewRecorder()
		req := httptest.NewRequest(method, path, strings.NewReader(body))
		req.Header.Set("Authorization", "Bearer "+token)
		req.Header.Set("X-Tenant-ID", "tenant-a")
		req.Header.Set("X-Request-ID", requestID)
		if body != "" {
			req.Header.Set("Content-Type", "application/json")
		}
		if path == "/v1/jobs" {
			req.Header.Set("Idempotency-Key", requestID)
		}
		handler.ServeHTTP(recorder, req)
		return recorder
	}

	read := request(http.MethodGet, "/v1/records/fixture-0001", "test-read-token", "go-read-1", "")
	if read.Code != http.StatusOK || !strings.Contains(read.Body.String(), `"data"`) {
		t.Fatalf("authorized read failed: %d %s", read.Code, read.Body.String())
	}
	plan := request(http.MethodPost, "/v1/operations/validate", "test-read-token", "go-plan-1",
		`{"contract_version":"v1","operation":"catalog.read","resource_id":"fixture-0001"}`)
	if plan.Code != http.StatusOK || !strings.Contains(plan.Body.String(), `"decision": "allow"`) {
		t.Fatalf("plan validation failed: %d %s", plan.Code, plan.Body.String())
	}
	job := request(http.MethodPost, "/v1/jobs", "test-read-token", "go-job-1",
		`{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"go"}}`)
	if job.Code != http.StatusAccepted || !strings.Contains(job.Body.String(), `"status": "queued"`) {
		t.Fatalf("job admission failed: %d %s", job.Code, job.Body.String())
	}
	denied := request(http.MethodPost, "/v1/jobs", "test-deny-token", "go-deny-1",
		`{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"denied"}}`)
	if denied.Code != http.StatusForbidden || !strings.Contains(denied.Body.String(), "CAPABILITY_DENIED") {
		t.Fatalf("expected capability denial failed: %d %s", denied.Code, denied.Body.String())
	}
	unauthorized := httptest.NewRecorder()
	handler.ServeHTTP(unauthorized, httptest.NewRequest(http.MethodGet, "/v1/records/fixture-0001", nil))
	if unauthorized.Code != http.StatusUnauthorized {
		t.Fatalf("missing bearer token status = %d", unauthorized.Code)
	}
}
