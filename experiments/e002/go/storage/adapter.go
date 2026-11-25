package storage

import (
	"bytes"
	"context"
	"crypto/rand"
	"crypto/sha256"
	"encoding/hex"
	"encoding/json"
	"errors"
	"fmt"
	"regexp"
	"strings"
)

const CanonicalizationVersion = "json-sort-keys-compact-utf8-v1"

var (
	ErrNotFound = errors.New("storage_record_not_found")
	ErrInvalid  = errors.New("storage_invalid_input")
)

type AuditEvent struct {
	EventID     string         `json:"event_id,omitempty"`
	RequestID   string         `json:"request_id"`
	TenantID    string         `json:"tenant_id"`
	OperationID string         `json:"operation_id"`
	Decision    string         `json:"decision"`
	ReasonCode  string         `json:"reason_code"`
	Outcome     map[string]any `json:"outcome"`
	CreatedAt   int64          `json:"created_at"`
}

type AdmissionRequest struct {
	TenantID       string
	OperationID    string
	IdempotencyKey string
	Payload        map[string]any
	OutboxPayload  map[string]any
	AuditEvent     AuditEvent
}

type AdmissionResult struct {
	Status  string         `json:"status"`
	Outcome map[string]any `json:"outcome"`
}

type IdempotencyRecord struct {
	TenantID       string         `json:"tenant_id"`
	OperationID    string         `json:"operation_id"`
	IdempotencyKey string         `json:"idempotency_key"`
	RequestHash    string         `json:"request_hash"`
	JobID          string         `json:"job_id"`
	Outcome        map[string]any `json:"outcome"`
}

type Job struct {
	JobID       string         `json:"job_id"`
	TenantID    string         `json:"tenant_id"`
	OperationID string         `json:"operation_id"`
	Payload     map[string]any `json:"payload"`
	State       string         `json:"state"`
	CreatedAt   int64          `json:"created_at"`
}

type OutboxEvent struct {
	EventID     string         `json:"event_id"`
	TenantID    string         `json:"tenant_id"`
	OperationID string         `json:"operation_id"`
	JobID       string         `json:"job_id"`
	Payload     map[string]any `json:"payload"`
	CreatedAt   int64          `json:"created_at"`
	LeaseOwner  string         `json:"lease_owner,omitempty"`
	LeaseToken  int64          `json:"lease_token"`
	LeaseUntil  *int64         `json:"lease_until,omitempty"`
	DeliveredAt *int64         `json:"delivered_at,omitempty"`
}

type RecoveryCounts struct {
	Jobs            int64 `json:"jobs"`
	Outbox          int64 `json:"outbox"`
	Idempotency     int64 `json:"idempotency"`
	Audit           int64 `json:"audit"`
	ConsumedEvents  int64 `json:"consumed_events"`
	ConsumerEffects int64 `json:"consumer_effects"`
}

type Metadata struct {
	Engine                 string `json:"engine"`
	EngineVersion          string `json:"engine_version"`
	Fsync                  string `json:"fsync"`
	SynchronousCommit      string `json:"synchronous_commit"`
	WALLevel               string `json:"wal_level"`
	Canonicalization       string `json:"canonicalization_version"`
	DurabilityProfile      string `json:"durability_profile"`
	TransactionIsolation   string `json:"transaction_isolation"`
}

type Adapter interface {
	AppendAudit(context.Context, AuditEvent) (int64, error)
	AdmitJob(context.Context, AdmissionRequest) (AdmissionResult, error)
	LookupIdempotency(context.Context, string, string, string) (*IdempotencyRecord, error)
	ReadJob(context.Context, string) (*Job, error)
	ReadOutboxForJob(context.Context, string) (*OutboxEvent, error)
	ClaimOutbox(context.Context, string, int, int64, int64) ([]OutboxEvent, error)
	AckOutbox(context.Context, string, string, int64, int64) (bool, error)
	ApplyConsumerEffect(context.Context, string, string, map[string]any, int64) (bool, error)
	Recover(context.Context) (RecoveryCounts, error)
	Metadata(context.Context) (Metadata, error)
	Close() error
}

type config struct {
	schema    string
	faultHook func(string) error
}

type Option func(*config)

func WithSchema(schema string) Option {
	return func(cfg *config) { cfg.schema = schema }
}

// WithFaultHook is intended for deterministic conformance tests. Production
// callers should not install fault injection hooks.
func WithFaultHook(hook func(string) error) Option {
	return func(cfg *config) { cfg.faultHook = hook }
}

var identifierPattern = regexp.MustCompile(`^[a-z][a-z0-9_]{0,62}$`)

func validateIdentifier(value string) error {
	if !identifierPattern.MatchString(value) {
		return fmt.Errorf("%w: invalid_schema", ErrInvalid)
	}
	return nil
}

func validateText(value, name string) error {
	if strings.TrimSpace(value) == "" || len(value) > 512 {
		return fmt.Errorf("%w: invalid_%s", ErrInvalid, name)
	}
	return nil
}

func canonicalJSON(value any) ([]byte, error) {
	var buffer bytes.Buffer
	encoder := json.NewEncoder(&buffer)
	encoder.SetEscapeHTML(false)
	if err := encoder.Encode(value); err != nil {
		return nil, err
	}
	encoded := bytes.TrimSuffix(buffer.Bytes(), []byte("\n"))
	// Python's reference canonicalizer emits these Unicode separators as UTF-8.
	encoded = bytes.ReplaceAll(encoded, []byte(`\u2028`), []byte("\u2028"))
	encoded = bytes.ReplaceAll(encoded, []byte(`\u2029`), []byte("\u2029"))
	return append([]byte(nil), encoded...), nil
}

func canonicalHash(value any) (string, error) {
	encoded, err := canonicalJSON(value)
	if err != nil {
		return "", err
	}
	hash := sha256.New()
	_, _ = hash.Write([]byte(CanonicalizationVersion))
	_, _ = hash.Write([]byte{0})
	_, _ = hash.Write(encoded)
	return hex.EncodeToString(hash.Sum(nil)), nil
}

func encodeObject(value map[string]any, name string) (string, error) {
	if value == nil {
		return "", fmt.Errorf("%w: %s_must_be_object", ErrInvalid, name)
	}
	encoded, err := canonicalJSON(value)
	if err != nil {
		return "", fmt.Errorf("%w: invalid_%s: %v", ErrInvalid, name, err)
	}
	return string(encoded), nil
}

func decodeObject(encoded string) (map[string]any, error) {
	var value map[string]any
	if err := json.Unmarshal([]byte(encoded), &value); err != nil {
		return nil, err
	}
	if value == nil {
		return nil, fmt.Errorf("%w: stored_json_must_be_object", ErrInvalid)
	}
	return value, nil
}

func newID() (string, error) {
	var raw [16]byte
	if _, err := rand.Read(raw[:]); err != nil {
		return "", err
	}
	raw[6] = (raw[6] & 0x0f) | 0x40
	raw[8] = (raw[8] & 0x3f) | 0x80
	encoded := hex.EncodeToString(raw[:])
	return encoded[:8] + "-" + encoded[8:12] + "-" + encoded[12:16] + "-" + encoded[16:20] + "-" + encoded[20:], nil
}
