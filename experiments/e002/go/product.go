package main

import (
	"bufio"
	"bytes"
	"encoding/json"
	"encoding/hex"
	"errors"
	"crypto/hmac"
	"crypto/sha256"
	"fmt"
	"io"
	"net/http"
	"os"
	"os/exec"
	"strings"
	"strconv"
	"time"
	"unicode/utf8"
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


type t16Grant struct {
	capability string
	resourcePrefix string
	expiresAt *int64
}

type t16Principal struct {
	principalID string
	tenantID string
	expiresAt int64
	grants []t16Grant
}

func validT16Capability(value string) bool {
	if value == "" || len(value) > 128 { return false }
	for _, char := range value {
		if !(char >= 'a' && char <= 'z') && !(char >= 'A' && char <= 'Z') &&
			!(char >= '0' && char <= '9') && char != '.' && char != '-' && char != '_' {
			return false
		}
	}
	return true
}

func validT16ResourcePrefix(value string) bool {
	if !strings.HasPrefix(value, "/") || strings.Contains(value, "//") ||
		strings.ContainsAny(value, "|~,;?#%\\\\") {
		return false
	}
	for _, segment := range strings.Split(value, "/") {
		if segment == "." || segment == ".." { return false }
	}
	for _, char := range value {
		if char < 0x20 || char == 0x7f { return false }
	}
	return true
}

func verifyT16Bearer(authorization string, key []byte, now time.Time) (t16Principal, error) {
	var identity t16Principal
	if len(key) < 32 { return identity, errors.New("invalid_signing_key") }
	if !strings.HasPrefix(authorization, "Bearer ") { return identity, errors.New("invalid_bearer_scheme") }
	token := strings.TrimPrefix(authorization, "Bearer ")
	if token == "" || len(token) > 8192 {
		return identity, errors.New("malformed_bearer_token")
	}
	separator := strings.LastIndex(token, ".")
	if separator <= 0 { return identity, errors.New("malformed_bearer_token") }
	payload, suppliedText := token[:separator], token[separator+1:]
	supplied, err := hex.DecodeString(suppliedText)
	if err != nil || len(supplied) != sha256.Size { return identity, errors.New("invalid_token_signature_encoding") }
	mac := hmac.New(sha256.New, key)
	_, _ = mac.Write([]byte(payload))
	if !hmac.Equal(mac.Sum(nil), supplied) { return identity, errors.New("invalid_token_signature") }
	fields := strings.Split(payload, "|")
	if len(fields) != 8 || fields[0] != "AN-CAP-V1" || fields[1] != "agent-native" || fields[2] != "agent-native-api" {
		return identity, errors.New("invalid_token_claims")
	}
	issuedAt, err1 := strconv.ParseInt(fields[3], 10, 64)
	expiresAt, err2 := strconv.ParseInt(fields[4], 10, 64)
	current := now.Unix()
	if err1 != nil || err2 != nil || issuedAt < 0 || issuedAt > current ||
		expiresAt <= current || expiresAt <= issuedAt || expiresAt-issuedAt > 900 {
		return identity, errors.New("token_expired_or_outside_validity_window")
	}
	if !validT16Header(fields[5]) || !validT16Header(fields[6]) || fields[7] == "" {
		return identity, errors.New("invalid_token_identity_or_grants")
	}
	grantItems := strings.Split(fields[7], ",")
	if len(grantItems) > 128 { return identity, errors.New("too_many_token_grants") }
	identity.principalID, identity.tenantID, identity.expiresAt = fields[5], fields[6], expiresAt
	for _, item := range grantItems {
		grantFields := strings.Split(item, "~")
		if len(grantFields) != 4 || !validT16Capability(grantFields[0]) || !validT16ResourcePrefix(grantFields[1]) {
			return t16Principal{}, errors.New("invalid_token_grant")
		}
		var grantExpiry *int64
		if grantFields[2] != "-" {
			value, parseErr := strconv.ParseInt(grantFields[2], 10, 64)
			if parseErr != nil || value < 0 { return t16Principal{}, errors.New("invalid_token_grant_expiry") }
			grantExpiry = &value
		}
		depth, parseErr := strconv.Atoi(grantFields[3])
		if parseErr != nil || depth < 0 { return t16Principal{}, errors.New("invalid_token_grant_depth") }
		identity.grants = append(identity.grants, t16Grant{
			capability: grantFields[0], resourcePrefix: grantFields[1], expiresAt: grantExpiry,
		})
	}
	if len(identity.grants) == 0 { return t16Principal{}, errors.New("empty_token_grants") }
	return identity, nil
}

func authorizeT16(identity t16Principal, capability, resource string, now time.Time) (bool, string) {
	if now.Unix() >= identity.expiresAt { return false, "TOKEN_EXPIRED" }
	matchedCapability, liveGrant := false, false
	for _, grant := range identity.grants {
		if grant.capability != capability { continue }
		matchedCapability = true
		if grant.expiresAt != nil && now.Unix() >= *grant.expiresAt { continue }
		liveGrant = true
		prefix := strings.TrimSuffix(grant.resourcePrefix, "/")
		if prefix == "" { prefix = "/" }
		if resource == prefix || strings.HasPrefix(resource, strings.TrimSuffix(prefix, "/")+"/") {
			return true, "ALLOW"
		}
	}
	if !matchedCapability { return false, "MISSING_CAPABILITY" }
	if !liveGrant { return false, "EXPIRED_GRANT" }
	return false, "RESOURCE_SCOPE"
}

type productService struct {
	pool *psqlPool
	signingKey []byte
}

func newProductServiceFromEnv() (*productService, error) {
	keyHex := os.Getenv("T16_SIGNING_KEY")
	if keyHex == "" { return nil, nil }
	signingKey, err := hex.DecodeString(keyHex)
	if err != nil || len(signingKey) < 32 {
		return nil, errors.New("t16_signing_key_must_be_32_bytes_of_hex")
	}
	dsn := os.Getenv("T16_PSQL_DSN")
	if dsn == "" {
		dsn = "postgresql://postgres@127.0.0.1:5432/agent_native?sslmode=disable"
	}
	pool, err := newPsqlPool(dsn, 32)
	if err != nil {
		return nil, err
	}
	return &productService{pool: pool, signingKey: signingKey}, nil
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

func consumeUniqueJSONValue(decoder *json.Decoder) error {
	token, err := decoder.Token()
	if err != nil {
		return err
	}
	delimiter, ok := token.(json.Delim)
	if !ok {
		return nil
	}
	switch delimiter {
	case '{':
		seen := make(map[string]struct{})
		for decoder.More() {
			keyToken, err := decoder.Token()
			if err != nil {
				return err
			}
			key, ok := keyToken.(string)
			if !ok {
				return errors.New("json_object_key_must_be_string")
			}
			if _, exists := seen[key]; exists {
				return errors.New("duplicate_json_object_key")
			}
			seen[key] = struct{}{}
			if err := consumeUniqueJSONValue(decoder); err != nil {
				return err
			}
		}
		closing, err := decoder.Token()
		if err != nil || closing != json.Delim('}') {
			return errors.New("invalid_json_object")
		}
	case '[':
		for decoder.More() {
			if err := consumeUniqueJSONValue(decoder); err != nil {
				return err
			}
		}
		closing, err := decoder.Token()
		if err != nil || closing != json.Delim(']') {
			return errors.New("invalid_json_array")
		}
	default:
		return errors.New("unexpected_json_delimiter")
	}
	return nil
}

func validateUniqueJSONKeys(raw []byte) error {
	if !utf8.Valid(raw) {
		return errors.New("request_body_must_be_valid_utf8")
	}
	decoder := json.NewDecoder(bytes.NewReader(raw))
	decoder.UseNumber()
	if err := consumeUniqueJSONValue(decoder); err != nil {
		return err
	}
	if _, err := decoder.Token(); err != io.EOF {
		return errors.New("request_body_must_contain_one_json_value")
	}
	return nil
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
	if err := validateUniqueJSONKeys(raw); err != nil {
		return nil, err
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

func writeT16Error(w http.ResponseWriter, status int, code string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	_ = json.NewEncoder(w).Encode(map[string]any{"error": map[string]string{"code": code}})
}

func (app *application) serveProduct(w http.ResponseWriter, request *http.Request) {
	if app.product == nil {
		writeT16Error(w, http.StatusServiceUnavailable, "PRODUCT_WORKLOAD_NOT_CONFIGURED")
		return
	}
	if request.URL.RawQuery != "" {
		writeT16Error(w, http.StatusBadRequest, "QUERY_NOT_SUPPORTED")
		return
	}
	requestID := request.Header.Get("X-Request-ID")
	assertedTenant := request.Header.Get("X-Tenant-ID")
	if !validT16Header(requestID) || !validT16Header(assertedTenant) {
		writeT16Error(w, http.StatusBadRequest, "INVALID_REQUEST_CONTEXT")
		return
	}

	identity, authErr := verifyT16Bearer(request.Header.Get("Authorization"), app.product.signingKey, time.Now())
	if authErr != nil {
		writeT16Error(w, http.StatusUnauthorized, "UNAUTHORIZED")
		return
	}

	operation, resourceID, expectedStatus := "", "", http.StatusOK
	requiredCapability, protectedResource := "", ""
	targetOperation := "catalog.read"
	var body json.RawMessage
	switch {
	case request.Method == http.MethodGet && request.URL.Path == "/v1/records/fixture-0001":
		operation, resourceID = "authorized_read", "fixture-0001"
		requiredCapability, protectedResource = "catalog.read", "/v1/records/fixture-0001"
	case request.Method == http.MethodPost && request.URL.Path == "/v1/operations/validate":
		var decoded validateRequest
		raw, err := decodeT16Body(request, &decoded)
		if err != nil {
			writeT16Error(w, http.StatusBadRequest, "INVALID_CONTRACT")
			return
		}
		body = raw
		resourceID = decoded.ResourceID
		requiredCapability, protectedResource = "catalog.read", "/v1/records/"+decoded.ResourceID
		if decoded.ResourceID == "" { protectedResource = "/v1/records/fixture-0001" }
		operation = "validate_plan"
		targetOperation = "operations.validate"
	case request.Method == http.MethodPost && request.URL.Path == "/v1/jobs":
		targetOperation = "jobs.create"
		var decoded jobRequest
		raw, err := decodeT16Body(request, &decoded)
		if err != nil {
			writeT16Error(w, http.StatusBadRequest, "INVALID_CONTRACT")
			return
		}
		body = raw
		requiredCapability, protectedResource = "jobs.create", "/v1/jobs"
		if !validT16Header(request.Header.Get("Idempotency-Key")) {
			writeT16Error(w, http.StatusBadRequest, "IDEMPOTENCY_KEY_REQUIRED")
			return
		}
		operation, targetOperation = "job_admission", "jobs.create"
	default:
		http.NotFound(w, request)
		return
	}

	reasonCode := "CAPABILITY_DENIED"
	authorized, decision := authorizeT16(identity, requiredCapability, protectedResource, time.Now())
	if assertedTenant != identity.tenantID {
		authorized, reasonCode = false, "TENANT_SCOPE_MISMATCH"
	} else if !authorized {
		reasonCode = decision
	}
	if !authorized {
		operation, expectedStatus = "expected_denial", http.StatusForbidden
	} else if operation == "job_admission" {
		expectedStatus = http.StatusAccepted
	}
	if body == nil {
		body = json.RawMessage("{}")
	}
	value := map[string]any{
		"request_id": requestID,
		"principal_id": identity.principalID,
		"tenant_id": identity.tenantID,
		"operation": operation,
		"target_operation": targetOperation,
		"resource_id": resourceID,
		"body": body,
	}
	if operation == "job_admission" || operation == "expected_denial" {
		value["idempotency_key"] = request.Header.Get("Idempotency-Key")
	}
	if operation == "expected_denial" {
		value["reason_code"] = reasonCode
	}

	result, err := app.product.pool.query(value)
	if err != nil {
		writeT16Error(w, http.StatusServiceUnavailable, "DURABLE_OPERATION_FAILED")
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

