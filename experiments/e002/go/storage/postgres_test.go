package storage

import (
	"context"
	"os"
	"testing"
	"time"
)

const testSchema = "e002_go_test"

func openTestAdapter(t *testing.T, reset bool, options ...Option) *PostgresAdapter {
	t.Helper()
	dsn := os.Getenv("AGENT_NATIVE_E002_POSTGRES_DSN")
	if dsn == "" {
		t.Skip("requires AGENT_NATIVE_E002_POSTGRES_DSN and PostgreSQL 16.4")
	}
	options = append(options, WithSchema(testSchema))
	ctx, cancel := context.WithTimeout(context.Background(), 15*time.Second)
	defer cancel()
	adapter, err := NewPostgresAdapter(ctx, dsn, options...)
	if err != nil {
		t.Fatalf("open Go PostgreSQL adapter: %v", err)
	}
	if reset {
		if err := adapter.resetForTesting(ctx); err != nil {
			_ = adapter.Close()
			t.Fatalf("reset Go PostgreSQL adapter: %v", err)
		}
	}
	t.Cleanup(func() { _ = adapter.Close() })
	return adapter
}

func testAdmission(requestID, tenant, operation, key, name string) AdmissionRequest {
	return AdmissionRequest{
		TenantID:       tenant,
		OperationID:    operation,
		IdempotencyKey: key,
		Payload:        map[string]any{"name": name},
		OutboxPayload:  map[string]any{"topic": "job.created", "name": name},
		AuditEvent: AuditEvent{
			RequestID: requestID, TenantID: tenant, OperationID: operation,
			CreatedAt: 100,
		},
	}
}

func TestAppendAuditDurable(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	sequence, err := adapter.AppendAudit(ctx, AuditEvent{
		RequestID: "append-audit-1", TenantID: "tenant-a",
		OperationID: "catalog.read", Decision: "allow",
		ReasonCode: "AUTHORIZED", Outcome: map[string]any{"record_id": "fixture-1"},
		CreatedAt: 100,
	})
	if err != nil {
		t.Fatalf("append audit: %v", err)
	}
	if sequence < 1 {
		t.Fatalf("invalid audit sequence: %d", sequence)
	}
	if err := adapter.Close(); err != nil {
		t.Fatalf("close adapter: %v", err)
	}
	reopened := openTestAdapter(t, false)
	counts, err := reopened.Recover(ctx)
	if err != nil {
		t.Fatalf("recover after reopen: %v", err)
	}
	if counts.Audit != 1 {
		t.Fatalf("audit record did not survive reopen: %+v", counts)
	}
}

func TestAtomicJobOutboxIdempotencyAuditCommit(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	request := testAdmission("admission-1", "tenant-a", "jobs.create", "key-1", "lamp")
	result, err := adapter.AdmitJob(ctx, request)
	if err != nil {
		t.Fatalf("admit job: %v", err)
	}
	if result.Status != "created" {
		t.Fatalf("unexpected admission status: %+v", result)
	}
	jobID, _ := result.Outcome["job_id"].(string)
	if jobID == "" {
		t.Fatalf("missing job id: %+v", result)
	}
	job, err := adapter.ReadJob(ctx, jobID)
	if err != nil || job == nil || job.State != "queued" {
		t.Fatalf("job not durable: job=%+v err=%v", job, err)
	}
	event, err := adapter.ReadOutboxForJob(ctx, jobID)
	if err != nil || event == nil || event.JobID != jobID {
		t.Fatalf("outbox event not durable: event=%+v err=%v", event, err)
	}
	record, err := adapter.LookupIdempotency(ctx, "tenant-a", "jobs.create", "key-1")
	if err != nil || record == nil || record.JobID != jobID {
		t.Fatalf("idempotency result not durable: record=%+v err=%v", record, err)
	}
	counts, err := adapter.Recover(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if counts.Jobs != 1 || counts.Outbox != 1 || counts.Idempotency != 1 || counts.Audit != 1 {
		t.Fatalf("admission records did not commit atomically: %+v", counts)
	}
	metadata, err := adapter.Metadata(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if metadata.Engine != "postgresql" || metadata.EngineVersion == "" ||
		metadata.Fsync != "on" || metadata.SynchronousCommit != "on" ||
		metadata.WALLevel == "" || metadata.TransactionIsolation != "read committed" {
		t.Fatalf("durability profile or engine metadata is not the required local durable commit: %+v", metadata)
	}
	if metadata.Canonicalization != CanonicalizationVersion {
		t.Fatalf("canonicalization version mismatch: %+v", metadata)
	}
}

func TestRecoverCommittedState(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	result, err := adapter.AdmitJob(ctx, testAdmission("recover-1", "tenant-a", "jobs.create", "recover-key", "desk"))
	if err != nil {
		t.Fatal(err)
	}
	jobID := result.Outcome["job_id"].(string)
	if err := adapter.Close(); err != nil {
		t.Fatal(err)
	}
	reopened := openTestAdapter(t, false)
	counts, err := reopened.Recover(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if counts.Jobs != 1 || counts.Outbox != 1 || counts.Idempotency != 1 || counts.Audit != 1 {
		t.Fatalf("committed state did not recover: %+v", counts)
	}
	job, err := reopened.ReadJob(ctx, jobID)
	if err != nil || job == nil || job.Payload["name"] != "desk" {
		t.Fatalf("recovered job mismatch: job=%+v err=%v", job, err)
	}
}
