package storage

import (
	"context"
	"fmt"
	"strings"
	"sync"
	"testing"
)


func TestCanonicalJSONMatchesPythonReference(t *testing.T) {
	value := map[string]any{
		"z": []any{true, 2},
		"a": "<café\u2028\u2029",
	}
	encoded, err := canonicalJSON(value)
	if err != nil {
		t.Fatal(err)
	}
	expected := "{\"a\":\"<café\u2028\u2029\",\"z\":[true,2]}"
	if string(encoded) != expected {
		t.Fatalf("canonical JSON mismatch: got %q want %q", string(encoded), expected)
	}
	first, err := canonicalHash(map[string]any{"b": 2, "a": 1})
	if err != nil {
		t.Fatal(err)
	}
	second, err := canonicalHash(map[string]any{"a": 1, "b": 2})
	if err != nil {
		t.Fatal(err)
	}
	if first != second {
		t.Fatalf("map key order changed canonical hash: %s != %s", first, second)
	}
}

func TestSameKeyReplayAndDifferentHashConflict(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	first, err := adapter.AdmitJob(ctx,
		testAdmission("request-1", "tenant-a", "jobs.create", "same-key", "lamp"))
	if err != nil || first.Status != "created" {
		t.Fatalf("first admission: result=%+v err=%v", first, err)
	}
	replayRequest := testAdmission("request-2", "tenant-a", "jobs.create", "same-key", "lamp")
	replay, err := adapter.AdmitJob(ctx, replayRequest)
	if err != nil || replay.Status != "replayed" {
		t.Fatalf("same request was not replayed: result=%+v err=%v", replay, err)
	}
	if replay.Outcome["job_id"] != first.Outcome["job_id"] {
		t.Fatalf("replay returned a different job: first=%+v replay=%+v", first, replay)
	}
	conflict, err := adapter.AdmitJob(ctx,
		testAdmission("request-3", "tenant-a", "jobs.create", "same-key", "desk"))
	if err != nil || conflict.Status != "conflict" {
		t.Fatalf("different payload did not conflict: result=%+v err=%v", conflict, err)
	}
	otherTenant, err := adapter.AdmitJob(ctx,
		testAdmission("request-4", "tenant-b", "jobs.create", "same-key", "lamp"))
	if err != nil || otherTenant.Status != "created" {
		t.Fatalf("tenant scope was not isolated: result=%+v err=%v", otherTenant, err)
	}
	otherOperation, err := adapter.AdmitJob(ctx,
		testAdmission("request-5", "tenant-a", "jobs.rebuild", "same-key", "lamp"))
	if err != nil || otherOperation.Status != "created" {
		t.Fatalf("operation scope was not isolated: result=%+v err=%v", otherOperation, err)
	}
	counts, err := adapter.Recover(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if counts.Jobs != 3 || counts.Outbox != 3 || counts.Idempotency != 3 || counts.Audit != 5 {
		t.Fatalf("unexpected replay/conflict state: %+v", counts)
	}
}

func TestConcurrentSameKeyAdmissionIsLinearizable(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	const workers = 32
	type result struct {
		status string
		jobID  string
		err    error
	}
	results := make(chan result, workers)
	var group sync.WaitGroup
	for index := 0; index < workers; index++ {
		group.Add(1)
		go func(index int) {
			defer group.Done()
			request := testAdmission(
				fmt.Sprintf("concurrent-%02d", index), "tenant-a", "jobs.create", "one-key", "lamp")
			value, err := adapter.AdmitJob(ctx, request)
			jobID, _ := value.Outcome["job_id"].(string)
			results <- result{status: value.Status, jobID: jobID, err: err}
		}(index)
	}
	group.Wait()
	close(results)

	created, replayed := 0, 0
	jobID := ""
	for value := range results {
		if value.err != nil {
			t.Fatalf("concurrent admission failed: %v", value.err)
		}
		if value.jobID == "" {
			t.Fatalf("concurrent result has no job id: %+v", value)
		}
		if jobID == "" {
			jobID = value.jobID
		}
		if value.jobID != jobID {
			t.Fatalf("same idempotency key created multiple jobs: %s != %s", value.jobID, jobID)
		}
		switch value.status {
		case "created":
			created++
		case "replayed":
			replayed++
		default:
			t.Fatalf("unexpected same-payload result: %+v", value)
		}
	}
	if created != 1 || replayed != workers-1 {
		t.Fatalf("same-key admission is not linearizable: created=%d replayed=%d", created, replayed)
	}
	counts, err := adapter.Recover(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if counts.Jobs != 1 || counts.Outbox != 1 || counts.Idempotency != 1 || counts.Audit != workers {
		t.Fatalf("concurrent admission persisted duplicate logical records: %+v", counts)
	}
}

func TestAuditUnavailableFailsClosed(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	function := adapter.table("e002_reject_audit_insert")
	if _, err := adapter.db.ExecContext(ctx, fmt.Sprintf(`CREATE OR REPLACE FUNCTION %s()
		RETURNS trigger LANGUAGE plpgsql AS $$
		BEGIN RAISE EXCEPTION 'injected_audit_unavailable'; END;
		$$`, function)); err != nil {
		t.Fatal(err)
	}
	if _, err := adapter.db.ExecContext(ctx, fmt.Sprintf(`CREATE TRIGGER e002_reject_audit_insert
		BEFORE INSERT ON %s FOR EACH ROW EXECUTE FUNCTION %s()`,
		adapter.table("e002_audit"), function)); err != nil {
		t.Fatal(err)
	}
	defer func() {
		_, _ = adapter.db.ExecContext(ctx, fmt.Sprintf("DROP TRIGGER IF EXISTS e002_reject_audit_insert ON %s", adapter.table("e002_audit")))
		_, _ = adapter.db.ExecContext(ctx, fmt.Sprintf("DROP FUNCTION IF EXISTS %s()", function))
	}()

	_, err := adapter.AdmitJob(ctx,
		testAdmission("audit-outage", "tenant-a", "jobs.create", "audit-key", "lamp"))
	if err == nil || !strings.Contains(err.Error(), "injected_audit_unavailable") {
		t.Fatalf("audit outage did not fail closed: %v", err)
	}
	counts, err := adapter.Recover(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if counts.Jobs != 0 || counts.Outbox != 0 || counts.Idempotency != 0 || counts.Audit != 0 {
		t.Fatalf("admission records survived audit outage: %+v", counts)
	}
}

func TestAuditRemainsAppendOnly(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	_, err := adapter.AppendAudit(ctx, AuditEvent{
		RequestID: "append-only", TenantID: "tenant-a", OperationID: "catalog.read",
		Decision: "allow", ReasonCode: "AUTHORIZED", Outcome: map[string]any{"id": "x"},
		CreatedAt: 100,
	})
	if err != nil {
		t.Fatal(err)
	}
	statements := []string{
		fmt.Sprintf("UPDATE %s SET reason_code='tampered'", adapter.table("e002_audit")),
		fmt.Sprintf("DELETE FROM %s", adapter.table("e002_audit")),
		fmt.Sprintf("TRUNCATE %s", adapter.table("e002_audit")),
	}
	for _, statement := range statements {
		if _, err := adapter.db.ExecContext(ctx, statement); err == nil {
			t.Fatalf("append-only audit accepted mutation: %s", statement)
		}
	}
}

func TestOutboxLeaseExpiryAndOwnerFencing(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	result, err := adapter.AdmitJob(ctx,
		testAdmission("outbox-lease", "tenant-a", "jobs.create", "lease-key", "lamp"))
	if err != nil {
		t.Fatal(err)
	}
	jobID := result.Outcome["job_id"].(string)
	event, err := adapter.ReadOutboxForJob(ctx, jobID)
	if err != nil || event == nil {
		t.Fatalf("read outbox event: event=%+v err=%v", event, err)
	}
	first, err := adapter.ClaimOutbox(ctx, "relay-a", 1, 5, 100)
	if err != nil || len(first) != 1 {
		t.Fatalf("first lease: events=%+v err=%v", first, err)
	}
	secondEarly, err := adapter.ClaimOutbox(ctx, "relay-b", 1, 5, 104)
	if err != nil || len(secondEarly) != 0 {
		t.Fatalf("lease was reclaimed before expiry: events=%+v err=%v", secondEarly, err)
	}
	second, err := adapter.ClaimOutbox(ctx, "relay-b", 1, 5, 106)
	if err != nil || len(second) != 1 {
		t.Fatalf("expired lease was not reclaimed: events=%+v err=%v", second, err)
	}
	if second[0].LeaseToken <= first[0].LeaseToken {
		t.Fatalf("lease fencing token did not advance: first=%d second=%d", first[0].LeaseToken, second[0].LeaseToken)
	}
	staleAck, err := adapter.AckOutbox(ctx, event.EventID, "relay-a", first[0].LeaseToken, 107)
	if err != nil || staleAck {
		t.Fatalf("stale lease owner acknowledged event: ack=%v err=%v", staleAck, err)
	}
	currentAck, err := adapter.AckOutbox(ctx, event.EventID, "relay-b", second[0].LeaseToken, 107)
	if err != nil || !currentAck {
		t.Fatalf("current lease owner could not acknowledge event: ack=%v err=%v", currentAck, err)
	}
	afterAck, err := adapter.ClaimOutbox(ctx, "relay-c", 1, 5, 108)
	if err != nil || len(afterAck) != 0 {
		t.Fatalf("delivered event was reclaimed: events=%+v err=%v", afterAck, err)
	}
}

func TestConsumerDeduplicatesLocalEffect(t *testing.T) {
	adapter := openTestAdapter(t, true)
	ctx := context.Background()
	result, err := adapter.AdmitJob(ctx,
		testAdmission("consumer-effect", "tenant-a", "jobs.create", "consumer-key", "lamp"))
	if err != nil {
		t.Fatal(err)
	}
	event, err := adapter.ReadOutboxForJob(ctx, result.Outcome["job_id"].(string))
	if err != nil || event == nil {
		t.Fatalf("read outbox event: event=%+v err=%v", event, err)
	}
	effect := map[string]any{"inventory_delta": -1, "sku": "lamp"}
	first, err := adapter.ApplyConsumerEffect(ctx, "inventory", event.EventID, effect, 200)
	if err != nil || !first {
		t.Fatalf("first consumer effect was not applied: applied=%v err=%v", first, err)
	}
	second, err := adapter.ApplyConsumerEffect(ctx, "inventory", event.EventID, effect, 201)
	if err != nil || second {
		t.Fatalf("duplicate consumer effect was applied twice: applied=%v err=%v", second, err)
	}
	counts, err := adapter.Recover(ctx)
	if err != nil {
		t.Fatal(err)
	}
	if counts.ConsumedEvents != 1 || counts.ConsumerEffects != 1 {
		t.Fatalf("consumer effect and dedupe marker were not atomic: %+v", counts)
	}
}
