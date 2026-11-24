package main

import (
	"encoding/json"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/hex"
	"net/http"
	"net/http/httptest"
	"os"
	"os/exec"
	"strings"
	"testing"
	"time"
)

func signedT16TestToken(key []byte, payload string) string {
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte(payload))
	return payload + "." + hex.EncodeToString(mac.Sum(nil))
}

func TestT16BearerVerifierRejectsTamperingExpiryAndWrongScope(t *testing.T) {
	key := []byte("0123456789abcdef0123456789abcdef")
	payload := "AN-CAP-V1|agent-native|agent-native-api|100|200|user-1|tenant-a|catalog.read~/v1/records/fixture-0001~-~0"
	token := signedT16TestToken(key, payload)
	identity, err := verifyT16Bearer("Bearer "+token, key, time.Unix(150, 0))
	if err != nil || identity.principalID != "user-1" || identity.tenantID != "tenant-a" {
		t.Fatalf("valid signed token rejected: identity=%+v err=%v", identity, err)
	}
	if allowed, reason := authorizeT16(identity, "catalog.read", "/v1/records/fixture-0001", time.Unix(150, 0)); !allowed || reason != "ALLOW" {
		t.Fatalf("valid scoped capability rejected: %v %s", allowed, reason)
	}
	if allowed, reason := authorizeT16(identity, "jobs.create", "/v1/jobs", time.Unix(150, 0)); allowed || reason != "MISSING_CAPABILITY" {
		t.Fatalf("missing capability was not denied: %v %s", allowed, reason)
	}
	if allowed, reason := authorizeT16(identity, "catalog.read", "/v1/records/fixture-0002", time.Unix(150, 0)); allowed || reason != "RESOURCE_SCOPE" {
		t.Fatalf("out-of-scope resource was not denied: %v %s", allowed, reason)
	}
	replacement := "0"
	if token[len(token)-1] == '0' { replacement = "1" }
	tampered := token[:len(token)-1] + replacement
	if _, err := verifyT16Bearer("Bearer "+tampered, key, time.Unix(150, 0)); err == nil {
		t.Fatal("tampered token was accepted")
	}
	if _, err := verifyT16Bearer("Bearer "+token, key, time.Unix(201, 0)); err == nil {
		t.Fatal("expired token was accepted")
	}
	if _, err := verifyT16Bearer("Bearer "+token, []byte("wrong-signing-key-0123456789abcdef"), time.Unix(150, 0)); err == nil {
		t.Fatal("token signed by another key was accepted")
	}
}

func TestT16ProductRoutesUseAuthenticatedPostgresContract(t *testing.T) {
	dsn := os.Getenv("T16_PSQL_DSN")
	if dsn == "" {
		t.Skip("requires T16_PSQL_DSN and psql client")
	}
	readToken, denyToken := os.Getenv("T16_READ_TOKEN"), os.Getenv("T16_DENY_TOKEN")
	if readToken == "" || denyToken == "" || os.Getenv("T16_SIGNING_KEY") == "" {
		t.Skip("requires signed T16 test tokens and T16_SIGNING_KEY")
	}
	reset := exec.Command("psql", dsn, "-X", "-v", "ON_ERROR_STOP=1", "-c", "SELECT t16_reset()")
	if output, err := reset.CombinedOutput(); err != nil {
		t.Fatalf("reset T16 database: %v: %s", err, output)
	}
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

	read := request(http.MethodGet, "/v1/records/fixture-0001", readToken, "go-read-1", "")
	if read.Code != http.StatusOK || !strings.Contains(read.Body.String(), `"data"`) {
		t.Fatalf("authorized read failed: %d %s", read.Code, read.Body.String())
	}
	plan := request(http.MethodPost, "/v1/operations/validate", readToken, "go-plan-1",
		`{"contract_version":"v1","operation":"catalog.read","resource_id":"fixture-0001"}`)
	if plan.Code != http.StatusOK || !strings.Contains(plan.Body.String(), `"decision": "allow"`) {
		t.Fatalf("plan validation failed: %d %s", plan.Code, plan.Body.String())
	}

	invalidContract := request(http.MethodPost, "/v1/operations/validate", readToken, "go-plan-invalid",
		`{"contract_version":"v1","operation":"catalog.read","resource_id":"fixture-0001","unexpected":true}`)
	if invalidContract.Code != http.StatusBadRequest || !strings.Contains(invalidContract.Body.String(), "INVALID_CONTRACT") {
		t.Fatalf("unknown contract field was not rejected: %d %s", invalidContract.Code, invalidContract.Body.String())
	}

	job := request(http.MethodPost, "/v1/jobs", readToken, "go-job-1",
		`{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"go"}}`)
	if job.Code != http.StatusAccepted || !strings.Contains(job.Body.String(), `"status": "queued"`) {
		t.Fatalf("job admission failed: %d %s", job.Code, job.Body.String())
	}
	denied := request(http.MethodPost, "/v1/jobs", denyToken, "go-deny-1",
		`{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"denied"}}`)
	if denied.Code != http.StatusForbidden || !strings.Contains(denied.Body.String(), "MISSING_CAPABILITY") {
		t.Fatalf("expected capability denial failed: %d %s", denied.Code, denied.Body.String())
	}

	// A client-supplied tenant header cannot switch the trusted tenant scope.
	crossTenant := httptest.NewRecorder()
	crossTenantRequest := httptest.NewRequest(http.MethodGet, "/v1/records/fixture-0001", nil)
	crossTenantRequest.Header.Set("Authorization", "Bearer "+readToken)
	crossTenantRequest.Header.Set("X-Tenant-ID", "tenant-b")
	crossTenantRequest.Header.Set("X-Request-ID", "go-cross-tenant-1")
	handler.ServeHTTP(crossTenant, crossTenantRequest)
	if crossTenant.Code != http.StatusForbidden || !strings.Contains(crossTenant.Body.String(), "TENANT_SCOPE_MISMATCH") {
		t.Fatalf("cross-tenant request was not denied: %d %s", crossTenant.Code, crossTenant.Body.String())
	}

	// Replays return the original job; a changed payload under the same key conflicts.
	jobRequest := func(requestID, payload string) *httptest.ResponseRecorder {
		recorder := httptest.NewRecorder()
		req := httptest.NewRequest(http.MethodPost, "/v1/jobs", strings.NewReader(payload))
		req.Header.Set("Authorization", "Bearer "+readToken)
		req.Header.Set("X-Tenant-ID", "tenant-a")
		req.Header.Set("X-Request-ID", requestID)
		req.Header.Set("Idempotency-Key", "go-idempotency-shared")
		handler.ServeHTTP(recorder, req)
		return recorder
	}
	first := jobRequest("go-idem-1", `{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"first"}}`)
	replay := jobRequest("go-idem-2", `{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"first"}}`)
	conflict := jobRequest("go-idem-3", `{"contract_version":"v1","operation":"jobs.create","payload":{"fixture":"different"}}`)
	var firstBody, replayBody map[string]any
	if err := json.Unmarshal(first.Body.Bytes(), &firstBody); err != nil { t.Fatal(err) }
	if err := json.Unmarshal(replay.Body.Bytes(), &replayBody); err != nil { t.Fatal(err) }
	if first.Code != http.StatusAccepted || replay.Code != http.StatusAccepted ||
		firstBody["job_id"] != replayBody["job_id"] {
		t.Fatalf("idempotency replay did not return original job: first=%d %s replay=%d %s",
			first.Code, first.Body.String(), replay.Code, replay.Body.String())
	}
	if conflict.Code != http.StatusConflict || !strings.Contains(conflict.Body.String(), "IDEMPOTENCY_CONFLICT") {
		t.Fatalf("idempotency payload conflict was not rejected: %d %s", conflict.Code, conflict.Body.String())
	}

	unauthorized := httptest.NewRecorder()
	unauthorizedRequest := httptest.NewRequest(http.MethodGet, "/v1/records/fixture-0001", nil)
	unauthorizedRequest.Header.Set("X-Request-ID", "go-unauthorized-1")
	unauthorizedRequest.Header.Set("X-Tenant-ID", "tenant-a")
	handler.ServeHTTP(unauthorized, unauthorizedRequest)
	var unauthorizedBody map[string]any
	if err := json.Unmarshal(unauthorized.Body.Bytes(), &unauthorizedBody); err != nil {
		t.Fatalf("missing bearer token error envelope is not JSON: %s", unauthorized.Body.String())
	}
	if unauthorized.Code != http.StatusUnauthorized || unauthorizedBody["error"].(map[string]any)["code"] != "UNAUTHORIZED" {
		t.Fatalf("missing bearer token response = %d %s", unauthorized.Code, unauthorized.Body.String())
	}
}
