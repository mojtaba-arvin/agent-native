package storage

import (
	"context"
	"database/sql"
	"encoding/json"
	"errors"
	"fmt"
	"strings"
	"time"

	"github.com/jackc/pgx/v5/stdlib"
)

type PostgresAdapter struct {
	db        *sql.DB
	schema    string
	faultHook func(string) error
}

func NewPostgresAdapter(ctx context.Context, dsn string, options ...Option) (*PostgresAdapter, error) {
	if err := validateText(dsn, "postgres_dsn"); err != nil {
		return nil, err
	}
	cfg := config{schema: "e002_go"}
	for _, option := range options {
		if option != nil {
			option(&cfg)
		}
	}
	if err := validateIdentifier(cfg.schema); err != nil {
		return nil, err
	}

	pgxConfig, err := pgx.ParseConfig(dsn)
	if err != nil {
		return nil, fmt.Errorf("parse_postgres_dsn: %w", err)
	}
	db := stdlib.OpenDB(*pgxConfig)
	db.SetMaxOpenConns(64)
	db.SetMaxIdleConns(32)
	db.SetConnMaxIdleTime(2 * time.Minute)
	db.SetConnMaxLifetime(15 * time.Minute)

	adapter := &PostgresAdapter{db: db, schema: cfg.schema, faultHook: cfg.faultHook}
	if err := db.PingContext(ctx); err != nil {
		_ = db.Close()
		return nil, fmt.Errorf("ping_postgres: %w", err)
	}
	if err := adapter.initialize(ctx); err != nil {
		_ = db.Close()
		return nil, err
	}
	metadata, err := adapter.Metadata(ctx)
	if err != nil {
		_ = db.Close()
		return nil, err
	}
	if metadata.Fsync != "on" || metadata.SynchronousCommit != "on" {
		_ = db.Close()
		return nil, fmt.Errorf(
			"postgres_durability_profile_required: fsync=%s synchronous_commit=%s",
			metadata.Fsync, metadata.SynchronousCommit,
		)
	}
	return adapter, nil
}

func (adapter *PostgresAdapter) table(name string) string {
	return quoteIdentifier(adapter.schema) + "." + quoteIdentifier(name)
}

func quoteIdentifier(value string) string {
	return "\"" + strings.ReplaceAll(value, "\"", "\"\"") + "\""
}

func (adapter *PostgresAdapter) initialize(ctx context.Context) error {
	if _, err := adapter.db.ExecContext(ctx, "CREATE SCHEMA IF NOT EXISTS "+quoteIdentifier(adapter.schema)); err != nil {
		return fmt.Errorf("create_e002_schema: %w", err)
	}
	statements := []string{
		fmt.Sprintf(`CREATE TABLE IF NOT EXISTS %s (
			job_id UUID PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			operation_id TEXT NOT NULL,
			payload_json TEXT NOT NULL,
			state TEXT NOT NULL CHECK (state IN ('queued','completed','failed')),
			created_at BIGINT NOT NULL
		)`, adapter.table("e002_jobs")),
		fmt.Sprintf(`CREATE TABLE IF NOT EXISTS %s (
			tenant_id TEXT NOT NULL,
			operation_id TEXT NOT NULL,
			idempotency_key TEXT NOT NULL,
			request_hash TEXT NOT NULL,
			job_id UUID NOT NULL REFERENCES %s(job_id),
			outcome_json TEXT NOT NULL,
			PRIMARY KEY (tenant_id, operation_id, idempotency_key)
		)`, adapter.table("e002_idempotency_records"), adapter.table("e002_jobs")),
		fmt.Sprintf(`CREATE TABLE IF NOT EXISTS %s (
			event_id UUID PRIMARY KEY,
			tenant_id TEXT NOT NULL,
			operation_id TEXT NOT NULL,
			job_id UUID NOT NULL UNIQUE REFERENCES %s(job_id),
			payload_json TEXT NOT NULL,
			created_at BIGINT NOT NULL,
			lease_owner TEXT,
			lease_token BIGINT NOT NULL DEFAULT 0,
			lease_until BIGINT,
			delivered_at BIGINT
		)`, adapter.table("e002_outbox"), adapter.table("e002_jobs")),
		fmt.Sprintf(`CREATE TABLE IF NOT EXISTS %s (
			sequence BIGSERIAL PRIMARY KEY,
			event_id UUID NOT NULL UNIQUE,
			request_id TEXT NOT NULL,
			tenant_id TEXT,
			operation_id TEXT NOT NULL,
			decision TEXT NOT NULL CHECK (decision IN ('allow','deny')),
			reason_code TEXT NOT NULL,
			outcome_json TEXT NOT NULL,
			created_at BIGINT NOT NULL
		)`, adapter.table("e002_audit")),
		fmt.Sprintf(`CREATE TABLE IF NOT EXISTS %s (
			consumer TEXT NOT NULL,
			event_id UUID NOT NULL REFERENCES %s(event_id),
			consumed_at BIGINT NOT NULL,
			PRIMARY KEY (consumer, event_id)
		)`, adapter.table("e002_consumed_events"), adapter.table("e002_outbox")),
		fmt.Sprintf(`CREATE TABLE IF NOT EXISTS %s (
			consumer TEXT NOT NULL,
			event_id UUID NOT NULL,
			effect_json TEXT NOT NULL,
			PRIMARY KEY (consumer, event_id),
			FOREIGN KEY (consumer, event_id)
				REFERENCES %s(consumer, event_id)
		)`, adapter.table("e002_consumer_effects"), adapter.table("e002_consumed_events")),
		fmt.Sprintf(`CREATE OR REPLACE FUNCTION %s()
			RETURNS trigger LANGUAGE plpgsql AS $$
			BEGIN
				RAISE EXCEPTION 'audit_append_only';
			END;
			$$`, adapter.table("e002_reject_audit_mutation")),
		fmt.Sprintf("DROP TRIGGER IF EXISTS e002_audit_no_update ON %s", adapter.table("e002_audit")),
		fmt.Sprintf("DROP TRIGGER IF EXISTS e002_audit_no_delete ON %s", adapter.table("e002_audit")),
		fmt.Sprintf("DROP TRIGGER IF EXISTS e002_audit_no_truncate ON %s", adapter.table("e002_audit")),
		fmt.Sprintf(`CREATE TRIGGER e002_audit_no_update BEFORE UPDATE ON %s
			FOR EACH ROW EXECUTE FUNCTION %s()`,
			adapter.table("e002_audit"), adapter.table("e002_reject_audit_mutation")),
		fmt.Sprintf(`CREATE TRIGGER e002_audit_no_delete BEFORE DELETE ON %s
			FOR EACH ROW EXECUTE FUNCTION %s()`,
			adapter.table("e002_audit"), adapter.table("e002_reject_audit_mutation")),
		fmt.Sprintf(`CREATE TRIGGER e002_audit_no_truncate BEFORE TRUNCATE ON %s
			FOR EACH STATEMENT EXECUTE FUNCTION %s()`,
			adapter.table("e002_audit"), adapter.table("e002_reject_audit_mutation")),
	}
	for _, statement := range statements {
		if _, err := adapter.db.ExecContext(ctx, statement); err != nil {
			return fmt.Errorf("initialize_e002_storage: %w", err)
		}
	}
	return nil
}

func (adapter *PostgresAdapter) ResetForTesting(ctx context.Context) error {
	if _, err := adapter.db.ExecContext(ctx, "DROP SCHEMA IF EXISTS "+quoteIdentifier(adapter.schema)+" CASCADE"); err != nil {
		return err
	}
	return adapter.initialize(ctx)
}

func (adapter *PostgresAdapter) fault(stage string) error {
	if adapter.faultHook == nil {
		return nil
	}
	return adapter.faultHook(stage)
}

func setDurableCommit(ctx context.Context, tx *sql.Tx) error {
	_, err := tx.ExecContext(ctx, "SET LOCAL synchronous_commit = on")
	return err
}

func (adapter *PostgresAdapter) insertAuditTx(ctx context.Context, tx *sql.Tx, event AuditEvent) (int64, error) {
	if err := validateText(event.RequestID, "request_id"); err != nil {
		return 0, err
	}
	if err := validateText(event.OperationID, "operation_id"); err != nil {
		return 0, err
	}
	if event.Decision != "allow" && event.Decision != "deny" {
		return 0, fmt.Errorf("%w: invalid_audit_decision", ErrInvalid)
	}
	if err := validateText(event.ReasonCode, "reason_code"); err != nil {
		return 0, err
	}
	if event.CreatedAt < 0 {
		return 0, fmt.Errorf("%w: invalid_audit_timestamp", ErrInvalid)
	}
	if event.EventID == "" {
		id, err := newID()
		if err != nil {
			return 0, err
		}
		event.EventID = id
	}
	outcome := event.Outcome
	if outcome == nil {
		outcome = map[string]any{}
	}
	outcomeJSON, err := encodeObject(outcome, "audit_outcome")
	if err != nil {
		return 0, err
	}
	var sequence int64
	err = tx.QueryRowContext(ctx, fmt.Sprintf(`INSERT INTO %s
		(event_id, request_id, tenant_id, operation_id, decision, reason_code, outcome_json, created_at)
		VALUES ($1,$2,NULLIF($3,''),$4,$5,$6,$7,$8)
		RETURNING sequence`, adapter.table("e002_audit")),
		event.EventID, event.RequestID, event.TenantID, event.OperationID,
		event.Decision, event.ReasonCode, outcomeJSON, event.CreatedAt,
	).Scan(&sequence)
	return sequence, err
}

func (adapter *PostgresAdapter) AppendAudit(ctx context.Context, event AuditEvent) (int64, error) {
	if err := adapter.fault("before_audit_begin"); err != nil {
		return 0, err
	}
	tx, err := adapter.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return 0, err
	}
	defer func() { _ = tx.Rollback() }()
	if err := setDurableCommit(ctx, tx); err != nil {
		return 0, err
	}
	if err := adapter.fault("before_audit_insert"); err != nil {
		return 0, err
	}
	sequence, err := adapter.insertAuditTx(ctx, tx, event)
	if err != nil {
		return 0, err
	}
	if err := tx.Commit(); err != nil {
		return 0, err
	}
	if err := adapter.fault("after_audit_commit"); err != nil {
		return 0, err
	}
	return sequence, nil
}

func (adapter *PostgresAdapter) AdmitJob(ctx context.Context, request AdmissionRequest) (AdmissionResult, error) {
	if err := validateText(request.TenantID, "tenant_id"); err != nil {
		return AdmissionResult{}, err
	}
	if err := validateText(request.OperationID, "operation_id"); err != nil {
		return AdmissionResult{}, err
	}
	if err := validateText(request.IdempotencyKey, "idempotency_key"); err != nil {
		return AdmissionResult{}, err
	}
	if request.AuditEvent.OperationID != request.OperationID {
		return AdmissionResult{}, fmt.Errorf("%w: audit_operation_mismatch", ErrInvalid)
	}
	if err := validateText(request.AuditEvent.RequestID, "request_id"); err != nil {
		return AdmissionResult{}, err
	}
	if request.AuditEvent.CreatedAt < 0 {
		return AdmissionResult{}, fmt.Errorf("%w: invalid_created_at", ErrInvalid)
	}
	payloadJSON, err := encodeObject(request.Payload, "payload")
	if err != nil {
		return AdmissionResult{}, err
	}
	outboxJSON, err := encodeObject(request.OutboxPayload, "outbox_payload")
	if err != nil {
		return AdmissionResult{}, err
	}
	requestHash, err := canonicalHash(map[string]any{
		"operation_id": request.OperationID,
		"payload":      request.Payload,
	})
	if err != nil {
		return AdmissionResult{}, err
	}
	scope, err := canonicalJSON([]string{request.TenantID, request.OperationID, request.IdempotencyKey})
	if err != nil {
		return AdmissionResult{}, err
	}
	if err := adapter.fault("before_begin"); err != nil {
		return AdmissionResult{}, err
	}
	tx, err := adapter.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return AdmissionResult{}, err
	}
	defer func() { _ = tx.Rollback() }()
	if err := setDurableCommit(ctx, tx); err != nil {
		return AdmissionResult{}, err
	}
	// A transaction-scoped advisory lock makes the tenant/operation/key tuple
	// linearizable without serializing unrelated idempotency scopes.
	if _, err := tx.ExecContext(ctx,
		"SELECT pg_advisory_xact_lock(hashtextextended($1, 0))", string(scope),
	); err != nil {
		return AdmissionResult{}, err
	}

	var previousHash, previousOutcome string
	err = tx.QueryRowContext(ctx, fmt.Sprintf(`SELECT request_hash, outcome_json FROM %s
		WHERE tenant_id=$1 AND operation_id=$2 AND idempotency_key=$3`, adapter.table("e002_idempotency_records")),
		request.TenantID, request.OperationID, request.IdempotencyKey,
	).Scan(&previousHash, &previousOutcome)
	if err != nil && !errors.Is(err, sql.ErrNoRows) {
		return AdmissionResult{}, err
	}
	if err == nil {
		result := AdmissionResult{}
		audit := AuditEvent{
			RequestID: request.AuditEvent.RequestID, TenantID: request.TenantID,
			OperationID: request.OperationID, CreatedAt: request.AuditEvent.CreatedAt,
		}
		if previousHash == requestHash {
			result.Status = "replayed"
			if err := json.Unmarshal([]byte(previousOutcome), &result.Outcome); err != nil {
				return AdmissionResult{}, err
			}
			audit.Decision, audit.ReasonCode = "allow", "IDEMPOTENCY_REPLAY"
			audit.Outcome = result.Outcome
		} else {
			result.Status = "conflict"
			result.Outcome = map[string]any{"code": "IDEMPOTENCY_PAYLOAD_CONFLICT"}
			audit.Decision, audit.ReasonCode = "deny", "IDEMPOTENCY_PAYLOAD_CONFLICT"
			audit.Outcome = result.Outcome
		}
		if _, err := adapter.insertAuditTx(ctx, tx, audit); err != nil {
			return AdmissionResult{}, err
		}
		if err := tx.Commit(); err != nil {
			return AdmissionResult{}, err
		}
		return result, nil
	}

	jobID, err := newID()
	if err != nil {
		return AdmissionResult{}, err
	}
	eventID, err := newID()
	if err != nil {
		return AdmissionResult{}, err
	}
	outcome := map[string]any{"job_id": jobID, "state": "queued"}
	outcomeJSON, err := encodeObject(outcome, "admission_outcome")
	if err != nil {
		return AdmissionResult{}, err
	}
	now := request.AuditEvent.CreatedAt

	if _, err := tx.ExecContext(ctx, fmt.Sprintf(`INSERT INTO %s
		(job_id, tenant_id, operation_id, payload_json, state, created_at)
		VALUES ($1,$2,$3,$4,'queued',$5)`, adapter.table("e002_jobs")),
		jobID, request.TenantID, request.OperationID, payloadJSON, now,
	); err != nil {
		return AdmissionResult{}, err
	}
	if err := adapter.fault("after_job"); err != nil {
		return AdmissionResult{}, err
	}
	if _, err := tx.ExecContext(ctx, fmt.Sprintf(`INSERT INTO %s
		(event_id, tenant_id, operation_id, job_id, payload_json, created_at)
		VALUES ($1,$2,$3,$4,$5,$6)`, adapter.table("e002_outbox")),
		eventID, request.TenantID, request.OperationID, jobID, outboxJSON, now,
	); err != nil {
		return AdmissionResult{}, err
	}
	if err := adapter.fault("after_outbox"); err != nil {
		return AdmissionResult{}, err
	}
	if _, err := tx.ExecContext(ctx, fmt.Sprintf(`INSERT INTO %s
		(tenant_id, operation_id, idempotency_key, request_hash, job_id, outcome_json)
		VALUES ($1,$2,$3,$4,$5,$6)`, adapter.table("e002_idempotency_records")),
		request.TenantID, request.OperationID, request.IdempotencyKey, requestHash, jobID, outcomeJSON,
	); err != nil {
		return AdmissionResult{}, err
	}
	if err := adapter.fault("after_idempotency"); err != nil {
		return AdmissionResult{}, err
	}
	admissionAudit := AuditEvent{
		RequestID: request.AuditEvent.RequestID, TenantID: request.TenantID,
		OperationID: request.OperationID, Decision: "allow", ReasonCode: "JOB_ADMITTED",
		Outcome: outcome, CreatedAt: now,
	}
	if _, err := adapter.insertAuditTx(ctx, tx, admissionAudit); err != nil {
		return AdmissionResult{}, err
	}
	if err := adapter.fault("after_audit"); err != nil {
		return AdmissionResult{}, err
	}
	if err := adapter.fault("before_commit"); err != nil {
		return AdmissionResult{}, err
	}
	if err := tx.Commit(); err != nil {
		return AdmissionResult{}, err
	}
	if err := adapter.fault("after_commit"); err != nil {
		// The caller has an ambiguous outcome. A retry with the same key must
		// reconcile through the durable idempotency record.
		return AdmissionResult{}, err
	}
	return AdmissionResult{Status: "created", Outcome: outcome}, nil
}

func (adapter *PostgresAdapter) LookupIdempotency(ctx context.Context, tenantID, operationID, key string) (*IdempotencyRecord, error) {
	var record IdempotencyRecord
	var outcomeJSON string
	err := adapter.db.QueryRowContext(ctx, fmt.Sprintf(`SELECT tenant_id, operation_id, idempotency_key,
		request_hash, job_id::text, outcome_json FROM %s
		WHERE tenant_id=$1 AND operation_id=$2 AND idempotency_key=$3`, adapter.table("e002_idempotency_records")),
		tenantID, operationID, key,
	).Scan(&record.TenantID, &record.OperationID, &record.IdempotencyKey,
		&record.RequestHash, &record.JobID, &outcomeJSON)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	record.Outcome, err = decodeObject(outcomeJSON)
	return &record, err
}

func (adapter *PostgresAdapter) ReadJob(ctx context.Context, jobID string) (*Job, error) {
	var job Job
	var payloadJSON string
	err := adapter.db.QueryRowContext(ctx, fmt.Sprintf(`SELECT job_id::text, tenant_id, operation_id,
		payload_json, state, created_at FROM %s WHERE job_id=$1`, adapter.table("e002_jobs")),
		jobID,
	).Scan(&job.JobID, &job.TenantID, &job.OperationID, &payloadJSON, &job.State, &job.CreatedAt)
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	if err != nil {
		return nil, err
	}
	job.Payload, err = decodeObject(payloadJSON)
	return &job, err
}

func scanOutbox(scanner interface{ Scan(...any) error }) (*OutboxEvent, error) {
	var event OutboxEvent
	var payloadJSON string
	var leaseOwner sql.NullString
	var leaseUntil, deliveredAt sql.NullInt64
	err := scanner.Scan(
		&event.EventID, &event.TenantID, &event.OperationID, &event.JobID,
		&payloadJSON, &event.CreatedAt, &leaseOwner, &event.LeaseToken,
		&leaseUntil, &deliveredAt,
	)
	if err != nil {
		return nil, err
	}
	event.Payload, err = decodeObject(payloadJSON)
	if err != nil {
		return nil, err
	}
	if leaseOwner.Valid {
		event.LeaseOwner = leaseOwner.String
	}
	if leaseUntil.Valid {
		value := leaseUntil.Int64
		event.LeaseUntil = &value
	}
	if deliveredAt.Valid {
		value := deliveredAt.Int64
		event.DeliveredAt = &value
	}
	return &event, nil
}

const outboxColumns = "event_id::text, tenant_id, operation_id, job_id::text, payload_json, created_at, lease_owner, lease_token, lease_until, delivered_at"

func (adapter *PostgresAdapter) ReadOutboxForJob(ctx context.Context, jobID string) (*OutboxEvent, error) {
	event, err := scanOutbox(adapter.db.QueryRowContext(ctx,
		fmt.Sprintf("SELECT %s FROM %s WHERE job_id=$1", outboxColumns, adapter.table("e002_outbox")),
		jobID,
	))
	if errors.Is(err, sql.ErrNoRows) {
		return nil, nil
	}
	return event, err
}

func (adapter *PostgresAdapter) ClaimOutbox(ctx context.Context, consumer string, limit int, leaseSeconds, now int64) ([]OutboxEvent, error) {
	if err := validateText(consumer, "consumer"); err != nil {
		return nil, err
	}
	if limit < 1 || limit > 1000 || leaseSeconds < 1 || now < 0 {
		return nil, fmt.Errorf("%w: invalid_outbox_claim", ErrInvalid)
	}
	tx, err := adapter.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return nil, err
	}
	defer func() { _ = tx.Rollback() }()
	if err := setDurableCommit(ctx, tx); err != nil {
		return nil, err
	}
	rows, err := tx.QueryContext(ctx, fmt.Sprintf(`SELECT event_id::text FROM %s
		WHERE delivered_at IS NULL AND (lease_until IS NULL OR lease_until <= $1)
		ORDER BY created_at, event_id LIMIT $2 FOR UPDATE SKIP LOCKED`, adapter.table("e002_outbox")),
		now, limit,
	)
	if err != nil {
		return nil, err
	}
	var ids []string
	for rows.Next() {
		var eventID string
		if err := rows.Scan(&eventID); err != nil {
			_ = rows.Close()
			return nil, err
		}
		ids = append(ids, eventID)
	}
	if err := rows.Err(); err != nil {
		_ = rows.Close()
		return nil, err
	}
	_ = rows.Close()

	claimed := make([]OutboxEvent, 0, len(ids))
	for _, eventID := range ids {
		if _, err := tx.ExecContext(ctx, fmt.Sprintf(`UPDATE %s
			SET lease_owner=$1, lease_token=lease_token+1, lease_until=$2
			WHERE event_id=$3 AND delivered_at IS NULL`, adapter.table("e002_outbox")),
			consumer, now+leaseSeconds, eventID,
		); err != nil {
			return nil, err
		}
		event, err := scanOutbox(tx.QueryRowContext(ctx,
			fmt.Sprintf("SELECT %s FROM %s WHERE event_id=$1", outboxColumns, adapter.table("e002_outbox")),
			eventID,
		))
		if err != nil {
			return nil, err
		}
		claimed = append(claimed, *event)
	}
	if err := tx.Commit(); err != nil {
		return nil, err
	}
	return claimed, nil
}

func (adapter *PostgresAdapter) AckOutbox(ctx context.Context, eventID, consumer string, leaseToken, now int64) (bool, error) {
	if err := validateText(eventID, "event_id"); err != nil {
		return false, err
	}
	if err := validateText(consumer, "consumer"); err != nil {
		return false, err
	}
	if leaseToken < 1 || now < 0 {
		return false, fmt.Errorf("%w: invalid_outbox_ack", ErrInvalid)
	}
	tx, err := adapter.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	if err := setDurableCommit(ctx, tx); err != nil {
		return false, err
	}
	result, err := tx.ExecContext(ctx, fmt.Sprintf(`UPDATE %s
		SET delivered_at=$1, lease_owner=NULL, lease_until=NULL
		WHERE event_id=$2 AND lease_owner=$3 AND lease_token=$4
		  AND lease_until>$1 AND delivered_at IS NULL`, adapter.table("e002_outbox")),
		now, eventID, consumer, leaseToken,
	)
	if err != nil {
		return false, err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	if err := tx.Commit(); err != nil {
		return false, err
	}
	return affected == 1, nil
}

func (adapter *PostgresAdapter) ApplyConsumerEffect(ctx context.Context, consumer, eventID string, effect map[string]any, now int64) (bool, error) {
	if err := validateText(consumer, "consumer"); err != nil {
		return false, err
	}
	if err := validateText(eventID, "event_id"); err != nil {
		return false, err
	}
	if now < 0 {
		return false, fmt.Errorf("%w: invalid_consumer_timestamp", ErrInvalid)
	}
	effectJSON, err := encodeObject(effect, "consumer_effect")
	if err != nil {
		return false, err
	}
	tx, err := adapter.db.BeginTx(ctx, &sql.TxOptions{Isolation: sql.LevelReadCommitted})
	if err != nil {
		return false, err
	}
	defer func() { _ = tx.Rollback() }()
	if err := setDurableCommit(ctx, tx); err != nil {
		return false, err
	}
	result, err := tx.ExecContext(ctx, fmt.Sprintf(`INSERT INTO %s (consumer,event_id,consumed_at)
		VALUES ($1,$2,$3) ON CONFLICT (consumer,event_id) DO NOTHING`, adapter.table("e002_consumed_events")),
		consumer, eventID, now,
	)
	if err != nil {
		return false, err
	}
	affected, err := result.RowsAffected()
	if err != nil {
		return false, err
	}
	if affected == 0 {
		if err := tx.Commit(); err != nil {
			return false, err
		}
		return false, nil
	}
	if _, err := tx.ExecContext(ctx, fmt.Sprintf(`INSERT INTO %s (consumer,event_id,effect_json)
		VALUES ($1,$2,$3)`, adapter.table("e002_consumer_effects")),
		consumer, eventID, effectJSON,
	); err != nil {
		return false, err
	}
	if err := tx.Commit(); err != nil {
		return false, err
	}
	return true, nil
}

func (adapter *PostgresAdapter) Recover(ctx context.Context) (RecoveryCounts, error) {
	var counts RecoveryCounts
	tables := []struct {
		name string
		dest *int64
	}{
		{"e002_jobs", &counts.Jobs},
		{"e002_outbox", &counts.Outbox},
		{"e002_idempotency_records", &counts.Idempotency},
		{"e002_audit", &counts.Audit},
		{"e002_consumed_events", &counts.ConsumedEvents},
		{"e002_consumer_effects", &counts.ConsumerEffects},
	}
	for _, table := range tables {
		if err := adapter.db.QueryRowContext(ctx,
			"SELECT COUNT(*) FROM "+adapter.table(table.name),
		).Scan(table.dest); err != nil {
			return RecoveryCounts{}, err
		}
	}
	return counts, nil
}

func (adapter *PostgresAdapter) Metadata(ctx context.Context) (Metadata, error) {
	var metadata Metadata
	metadata.Engine = "postgresql"
	metadata.Canonicalization = CanonicalizationVersion
	metadata.DurabilityProfile = "fsync=on + synchronous_commit=on"
	err := adapter.db.QueryRowContext(ctx, "SHOW server_version").Scan(&metadata.EngineVersion)
	if err != nil {
		return Metadata{}, err
	}
	if err := adapter.db.QueryRowContext(ctx, "SHOW fsync").Scan(&metadata.Fsync); err != nil {
		return Metadata{}, err
	}
	if err := adapter.db.QueryRowContext(ctx, "SHOW synchronous_commit").Scan(&metadata.SynchronousCommit); err != nil {
		return Metadata{}, err
	}
	if err := adapter.db.QueryRowContext(ctx, "SHOW wal_level").Scan(&metadata.WALLevel); err != nil {
		return Metadata{}, err
	}
	if err := adapter.db.QueryRowContext(ctx, "SHOW transaction_isolation").Scan(&metadata.TransactionIsolation); err != nil {
		return Metadata{}, err
	}
	return metadata, nil
}

func (adapter *PostgresAdapter) Close() error {
	if adapter == nil || adapter.db == nil {
		return nil
	}
	return adapter.db.Close()
}

var _ Adapter = (*PostgresAdapter)(nil)

