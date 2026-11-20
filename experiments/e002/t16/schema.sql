-- T16's shared PostgreSQL control-plane storage contract.
CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS t16_records (
    tenant_id TEXT NOT NULL,
    record_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    PRIMARY KEY (tenant_id, record_id)
);

CREATE TABLE IF NOT EXISTS t16_jobs (
    job_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    payload JSONB NOT NULL,
    state TEXT NOT NULL CHECK (state IN ('queued', 'completed', 'failed')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS t16_outbox (
    event_id UUID PRIMARY KEY,
    tenant_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    job_id UUID NOT NULL UNIQUE REFERENCES t16_jobs(job_id),
    payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp(),
    delivered_at TIMESTAMPTZ
);

CREATE TABLE IF NOT EXISTS t16_idempotency_records (
    tenant_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    idempotency_key TEXT NOT NULL,
    request_hash TEXT NOT NULL,
    job_id UUID NOT NULL REFERENCES t16_jobs(job_id),
    outcome JSONB NOT NULL,
    PRIMARY KEY (tenant_id, operation_id, idempotency_key)
);

CREATE TABLE IF NOT EXISTS t16_audit (
    sequence BIGSERIAL PRIMARY KEY,
    event_id UUID NOT NULL UNIQUE,
    request_id TEXT NOT NULL,
    principal_id TEXT NOT NULL,
    tenant_id TEXT NOT NULL,
    operation_id TEXT NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('allow', 'deny')),
    reason_code TEXT NOT NULL,
    outcome JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE TABLE IF NOT EXISTS t16_integrity_violations (
    sequence BIGSERIAL PRIMARY KEY,
    request_id TEXT NOT NULL,
    reason_code TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()
);

CREATE OR REPLACE FUNCTION t16_reject_audit_mutation()
RETURNS trigger LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 't16_audit_append_only';
END;
$$;

DROP TRIGGER IF EXISTS t16_audit_no_update ON t16_audit;
DROP TRIGGER IF EXISTS t16_audit_no_delete ON t16_audit;
CREATE TRIGGER t16_audit_no_update BEFORE UPDATE ON t16_audit
FOR EACH ROW EXECUTE FUNCTION t16_reject_audit_mutation();
CREATE TRIGGER t16_audit_no_delete BEFORE DELETE ON t16_audit
FOR EACH ROW EXECUTE FUNCTION t16_reject_audit_mutation();

INSERT INTO t16_records (tenant_id, record_id, payload)
VALUES ('tenant-a', 'fixture-0001', '{"id":"fixture-0001","kind":"catalog-record","value":"seeded"}'::jsonb)
ON CONFLICT (tenant_id, record_id) DO UPDATE SET payload = EXCLUDED.payload;

CREATE OR REPLACE FUNCTION t16_handle(input JSONB)
RETURNS JSONB LANGUAGE plpgsql AS $$
DECLARE
    request_id TEXT := input->>'request_id';
    principal_id TEXT := input->>'principal_id';
    v_tenant_id TEXT := input->>'tenant_id';
    v_operation_id TEXT := input->>'operation';
    v_idempotency_key TEXT := input->>'idempotency_key';
    reason_code TEXT := COALESCE(input->>'reason_code', 'CAPABILITY_DENIED');
    body JSONB := COALESCE(input->'body', '{}'::jsonb);
    record_payload JSONB;
    request_hash TEXT;
    existing_hash TEXT;
    existing_outcome JSONB;
    job_id UUID;
    event_id UUID;
    outcome JSONB;
BEGIN
    IF request_id IS NULL OR request_id = '' OR principal_id IS NULL OR principal_id = ''
       OR v_tenant_id IS NULL OR v_tenant_id = '' OR v_operation_id IS NULL OR v_operation_id = '' THEN
        RAISE EXCEPTION 't16_request_context_invalid';
    END IF;

    IF v_operation_id = 'expected_denial' THEN
        outcome := jsonb_build_object('request_id', request_id,
            'error', jsonb_build_object('code', reason_code));
        INSERT INTO t16_audit(event_id, request_id, principal_id, v_tenant_id,
            operation_id, decision, reason_code, outcome)
        VALUES (gen_random_uuid(), request_id, principal_id, v_tenant_id,
            'jobs.create', 'deny', reason_code, outcome);
        RETURN outcome;
    ELSIF v_operation_id = 'authorized_read' THEN
        SELECT payload INTO record_payload FROM t16_records
        WHERE t16_records.tenant_id = v_tenant_id AND record_id = COALESCE(input->>'resource_id', 'fixture-0001');
        IF record_payload IS NULL THEN
            RAISE EXCEPTION 't16_record_not_found';
        END IF;
        outcome := jsonb_build_object('request_id', request_id, 'data', record_payload);
        INSERT INTO t16_audit(event_id, request_id, principal_id, tenant_id,
            operation_id, decision, reason_code, outcome)
        VALUES (gen_random_uuid(), request_id, principal_id, tenant_id,
            'catalog.read', 'allow', 'AUTHORIZED_READ', outcome);
        RETURN outcome;
    ELSIF v_operation_id = 'validate_plan' THEN
        IF body->>'contract_version' IS DISTINCT FROM 'v1'
           OR body->>'operation' IS DISTINCT FROM 'catalog.read'
           OR COALESCE(body->>'resource_id', '') = '' THEN
            RAISE EXCEPTION 't16_contract_invalid';
        END IF;
        outcome := jsonb_build_object('request_id', request_id, 'decision', 'allow');
        INSERT INTO t16_audit(event_id, request_id, principal_id, tenant_id,
            operation_id, decision, reason_code, outcome)
        VALUES (gen_random_uuid(), request_id, principal_id, tenant_id,
            'operations.validate', 'allow', 'PLAN_VALIDATED', outcome);
        RETURN outcome;
    ELSIF v_operation_id = 'job_admission' THEN
        IF body->>'contract_version' IS DISTINCT FROM 'v1' OR body->>'operation' IS DISTINCT FROM 'jobs.create'
           OR jsonb_typeof(body->'payload') IS DISTINCT FROM 'object'
           OR v_idempotency_key IS NULL OR v_idempotency_key = '' THEN
            RAISE EXCEPTION 't16_job_contract_invalid';
        END IF;
        request_hash := encode(digest(convert_to((body->'payload')::text, 'UTF8'), 'sha256'), 'hex');
        PERFORM pg_advisory_xact_lock(hashtextextended(v_tenant_id || ':' || v_operation_id || ':' || v_idempotency_key, 0));
        SELECT request_hash, outcome INTO existing_hash, existing_outcome
        FROM t16_idempotency_records
        WHERE t16_idempotency_records.tenant_id = v_tenant_id
          AND operation_id = 'jobs.create'
          AND t16_idempotency_records.idempotency_key = v_idempotency_key;
        IF FOUND THEN
            IF existing_hash <> request_hash THEN
                outcome := jsonb_build_object('request_id', request_id,
                    'error', jsonb_build_object('code', 'IDEMPOTENCY_CONFLICT'));
                INSERT INTO t16_audit(event_id, request_id, principal_id, tenant_id,
                    operation_id, decision, reason_code, outcome)
                VALUES (gen_random_uuid(), request_id, principal_id, tenant_id,
                    'jobs.create', 'deny', 'IDEMPOTENCY_PAYLOAD_CONFLICT', outcome);
                RETURN outcome;
            END IF;
            outcome := existing_outcome || jsonb_build_object('request_id', request_id);
            INSERT INTO t16_audit(event_id, request_id, principal_id, tenant_id,
                operation_id, decision, reason_code, outcome)
            VALUES (gen_random_uuid(), request_id, principal_id, tenant_id,
                'jobs.create', 'allow', 'IDEMPOTENCY_REPLAY', outcome);
            RETURN outcome;
        END IF;

        job_id := gen_random_uuid();
        event_id := gen_random_uuid();
        outcome := jsonb_build_object('request_id', request_id,
            'job_id', job_id::text, 'status', 'queued');
        INSERT INTO t16_jobs(job_id, tenant_id, operation_id, payload, state)
        VALUES (job_id, v_tenant_id, 'jobs.create', body->'payload', 'queued');
        INSERT INTO t16_outbox(event_id, tenant_id, operation_id, job_id, payload)
        VALUES (event_id, v_tenant_id, 'jobs.create', job_id,
            jsonb_build_object('event_id', event_id::text, 'topic', 'job.created', 'job_id', job_id::text));
        INSERT INTO t16_idempotency_records(tenant_id, operation_id, idempotency_key,
            request_hash, job_id, outcome)
        VALUES (v_tenant_id, 'jobs.create', v_idempotency_key, request_hash, job_id, outcome - 'request_id');
        INSERT INTO t16_audit(event_id, request_id, principal_id, tenant_id,
            operation_id, decision, reason_code, outcome)
        VALUES (gen_random_uuid(), request_id, principal_id, tenant_id,
            'jobs.create', 'allow', 'JOB_ADMITTED', outcome);
        RETURN outcome;
    ELSE
        RAISE EXCEPTION 't16_operation_unknown';
    END IF;
END;
$$;

CREATE OR REPLACE FUNCTION t16_reset()
RETURNS VOID LANGUAGE plpgsql AS $$
BEGIN
    TRUNCATE t16_audit, t16_idempotency_records, t16_outbox, t16_jobs, t16_integrity_violations RESTART IDENTITY;
END;
$$;
