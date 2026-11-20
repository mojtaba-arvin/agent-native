package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"errors"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"sync"
)

const t16MaxBodyBytes = 16 * 1024

type psqlWorker struct {
	command *exec.Cmd
	stdin   io.WriteCloser
	stdout  *bufio.Reader
	mu      sync.Mutex
}

type psqlPool struct {
	workers chan *psqlWorker
}

func startPsqlWorker(dsn string) (*psqlWorker, error) {
	binary, err := exec.LookPath("psql")
	if err != nil {
		return nil, errors.New("psql_client_required")
	}
	command := exec.Command(binary, "-X", "-q", "-A", "-t", dsn)
	stdin, err := command.StdinPipe()
	if err != nil {
		return nil, err
	}
	stdout, err := command.StdoutPipe()
	if err != nil {
		return nil, err
	}
	command.Stderr = io.Discard
	if err := command.Start(); err != nil {
		return nil, err
	}
	return &psqlWorker{command: command, stdin: stdin, stdout: bufio.NewReader(stdout)}, nil
}

func (worker *psqlWorker) query(value map[string]any) (string, error) {
	worker.mu.Lock()
	defer worker.mu.Unlock()
	encoded, err := json.Marshal(value)
	if err != nil {
		return "", err
	}
	quoted := strings.ReplaceAll(string(encoded), "'", "''")
	if _, err := fmt.Fprintf(worker.stdin, "SELECT t16_handle('%s'::jsonb)::text;\n\\echo __T16_DONE__\n", quoted); err != nil {
		return "", err
	}
	var result string
	for {
		line, err := worker.stdout.ReadString('\n')
		if err != nil {
			return "", err
		}
		line = strings.TrimSuffix(strings.TrimSuffix(line, "\n"), "\r")
		if line == "__T16_DONE__" {
			break
		}
		if line != "" {
			if result != "" {
				return "", errors.New("postgres_returned_multiple_rows")
			}
			result = line
		}
	}
	if result == "" || !json.Valid([]byte(result)) {
		return "", errors.New("postgres_product_operation_failed")
	}
	return result, nil
}

func newPsqlPool(dsn string, size int) (*psqlPool, error) {
	if size < 1 {
		return nil, errors.New("invalid_psql_pool_size")
	}
	pool := &psqlPool{workers: make(chan *psqlWorker, size)}
	for i := 0; i < size; i++ {
		worker, err := startPsqlWorker(dsn)
		if err != nil {
			for len(pool.workers) > 0 {
				(<-pool.workers).close()
			}
			return nil, fmt.Errorf("start_postgres_worker_%d: %w", i, err)
		}
		pool.workers <- worker
	}
	return pool, nil
}

func (worker *psqlWorker) close() {
	_ = worker.stdin.Close()
	if worker.command.Process != nil {
		_ = worker.command.Process.Kill()
		_, _ = worker.command.Process.Wait()
	}
}

func (pool *psqlPool) query(value map[string]any) (string, error) {
	worker := <-pool.workers
	defer func() { pool.workers <- worker }()
	return worker.query(value)
}

func (pool *psqlPool) close() {
	close(pool.workers)
	for worker := range pool.workers {
		worker.close()
	}
}

type productService struct {
	pool      *psqlPool
	readToken string
	denyToken string
	tenant    string
}

func newProductServiceFromEnv() (*productService, error) {
	readToken, denyToken := os.Getenv("T16_READ_TOKEN"), os.Getenv("T16_DENY_TOKEN")
	if readToken == "" && denyToken == "" {
		return nil, nil
	}
	if readToken == "" || denyToken == "" {
		return nil, errors.New("both_t16_bearer_fixtures_required")
	}
	dsn := os.Getenv("T16_PSQL_DSN")
	if dsn == "" {
		dsn = "postgresql://postgres@127.0.0.1:5432/agent_native?sslmode=disable"
	}
	tenant := os.Getenv("T16_TENANT_ID")
	if tenant == "" {
		tenant = "tenant-a"
	}
	pool, err := newPsqlPool(dsn, 32)
	if err != nil {
		return nil, err
	}
	return &productService{pool: pool, readToken: readToken, denyToken: denyToken, tenant: tenant}, nil
}

func validT16Header(value string) bool {
	if value == "" || len(value) > 128 {
		return false
	}
	for _, char := range value {
		if !(char >= 'a' && char <= 'z') && !(char >= 'A' && char <= 'Z') &&
			!(char >= '0' && char <= '9') && char != '-' && char != '_' {
			return false
		}
	}
	return true
}

func decodeT16Body(request *http.Request, target any) (json.RawMessage, error) {
	raw, err := io.ReadAll(io.LimitReader(request.Body, t16MaxBodyBytes+1))
	if err != nil {
		return nil, err
	}
	if len(raw) > t16MaxBodyBytes {
		return nil, errors.New("request_body_too_large")
	}
	if len(bytes.TrimSpace(raw)) == 0 {
		raw = []byte("{}")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	if err := decoder.Decode(target); err != nil {
		return nil, err
	}
	if decoder.Decode(new(any)) != io.EOF {
		return nil, errors.New("request_body_must_contain_one_json_value")
	}
	return json.RawMessage(raw), nil
}

type validateRequest struct {
	ContractVersion string `json:"contract_version"`
	Operation        string `json:"operation"`
	ResourceID       string `json:"resource_id"`
}

type jobRequest struct {
	ContractVersion string         `json:"contract_version"`
	Operation        string         `json:"operation"`
	Payload          map[string]any `json:"payload"`
}

func (app *application) serveProduct(w http.ResponseWriter, request *http.Request) {
	if app.product == nil {
		http.Error(w, "product_workload_not_configured", http.StatusServiceUnavailable)
		return
	}
	if request.URL.RawQuery != "" {
		http.Error(w, "query_not_supported", http.StatusBadRequest)
		return
	}
	requestID := request.Header.Get("X-Request-ID")
	assertedTenant := request.Header.Get("X-Tenant-ID")
	if !validT16Header(requestID) || !validT16Header(assertedTenant) {
		http.Error(w, "invalid_request_context", http.StatusBadRequest)
		return
	}

	principal, allowed := "", false
	switch request.Header.Get("Authorization") {
	case "Bearer " + app.product.readToken:
		principal, allowed = "benchmark-reader", true
	case "Bearer " + app.product.denyToken:
		principal, allowed = "benchmark-limited", false
	default:
		http.Error(w, "unauthorized", http.StatusUnauthorized)
		return
	}

	operation, resourceID, expectedStatus := "", "", http.StatusOK
	targetOperation := "catalog.read"
	var body json.RawMessage
	switch {
	case request.Method == http.MethodGet && request.URL.Path == "/v1/records/fixture-0001":
		operation, resourceID = "authorized_read", "fixture-0001"
	case request.Method == http.MethodPost && request.URL.Path == "/v1/operations/validate":
		var decoded validateRequest
		raw, err := decodeT16Body(request, &decoded)
		if err != nil {
			http.Error(w, "invalid_contract", http.StatusBadRequest)
			return
		}
		body = raw
		operation = "validate_plan"
		targetOperation = "operations.validate"
	case request.Method == http.MethodPost && request.URL.Path == "/v1/jobs":
		targetOperation = "jobs.create"
		var decoded jobRequest
		raw, err := decodeT16Body(request, &decoded)
		if err != nil {
			http.Error(w, "invalid_contract", http.StatusBadRequest)
			return
		}
		body = raw
		if !validT16Header(request.Header.Get("Idempotency-Key")) {
			http.Error(w, "idempotency_key_required", http.StatusBadRequest)
			return
		}
		if allowed && assertedTenant == app.product.tenant {
			operation, expectedStatus = "job_admission", http.StatusAccepted
			targetOperation = "jobs.create"
		} else {
			operation, expectedStatus = "expected_denial", http.StatusForbidden
		}
	default:
		http.NotFound(w, request)
		return
	}

	if assertedTenant != app.product.tenant {
		operation, expectedStatus = "expected_denial", http.StatusForbidden
	}
	if operation == "validate_plan" && !allowed {
		operation, expectedStatus = "expected_denial", http.StatusForbidden
	}
	if operation == "authorized_read" && assertedTenant != app.product.tenant {
		operation, expectedStatus = "expected_denial", http.StatusForbidden
	}
	if body == nil {
		body = json.RawMessage("{}")
	}
	value := map[string]any{
		"request_id": requestID,
		"principal_id": principal,
		"tenant_id": app.product.tenant,
		"operation": operation,
		"target_operation": targetOperation,
		"resource_id": resourceID,
		"body": body,
	}
	if operation == "job_admission" || operation == "expected_denial" {
		value["idempotency_key"] = request.Header.Get("Idempotency-Key")
	}
	if operation == "expected_denial" {
		if assertedTenant != app.product.tenant {
			value["reason_code"] = "TENANT_SCOPE_MISMATCH"
		} else {
			value["reason_code"] = "CAPABILITY_DENIED"
		}
	}

	result, err := app.product.pool.query(value)
	if err != nil {
		http.Error(w, "durable_operation_failed", http.StatusServiceUnavailable)
		return
	}
	if strings.Contains(result, "IDEMPOTENCY_CONFLICT") {
		expectedStatus = http.StatusConflict
	} else if strings.Contains(result, "INVALID_CONTRACT") {
		expectedStatus = http.StatusBadRequest
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(expectedStatus)
	_, _ = io.WriteString(w, result)
}

