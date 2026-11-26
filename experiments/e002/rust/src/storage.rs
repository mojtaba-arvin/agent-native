//! Rust-native PostgreSQL adapter for the shared E-002 durable storage contract.
//! Direct parameterized SQL only; no shelling out to psql or T16-specific routines.

use serde_json::{json, Value};
use sha2::{Digest, Sha256};
use std::{error::Error, io, sync::Arc};
use tokio::sync::Mutex;
use tokio_postgres::{Client, NoTls, Row, Transaction};
use uuid::Uuid;

pub const CANONICALIZATION_VERSION: &str = "json-sort-keys-compact-utf8-v1";
pub type StorageResult<T> = Result<T, Box<dyn Error + Send + Sync>>;
type FaultHook = Arc<dyn Fn(&str) -> bool + Send + Sync>;

#[derive(Debug, Clone)]
pub struct AuditEvent {
    pub request_id: String,
    pub tenant_id: String,
    pub operation_id: String,
    pub decision: String,
    pub reason_code: String,
    pub outcome: Value,
    pub created_at: i64,
}
#[derive(Debug, Clone)]
pub struct AdmissionRequest {
    pub tenant_id: String,
    pub operation_id: String,
    pub idempotency_key: String,
    pub payload: Value,
    pub outbox_payload: Value,
    pub audit: AuditEvent,
}
#[derive(Debug, Clone, PartialEq)]
pub struct AdmissionResult {
    pub status: String,
    pub outcome: Value,
}
#[derive(Debug, Clone)]
pub struct IdempotencyRecord {
    pub tenant_id: String,
    pub operation_id: String,
    pub idempotency_key: String,
    pub request_hash: String,
    pub job_id: String,
    pub outcome: Value,
}
#[derive(Debug, Clone)]
pub struct Job {
    pub job_id: String,
    pub tenant_id: String,
    pub operation_id: String,
    pub payload: Value,
    pub state: String,
    pub created_at: i64,
}
#[derive(Debug, Clone)]
pub struct OutboxEvent {
    pub event_id: String,
    pub tenant_id: String,
    pub operation_id: String,
    pub job_id: String,
    pub payload: Value,
    pub created_at: i64,
    pub lease_owner: Option<String>,
    pub lease_token: i64,
    pub lease_until: Option<i64>,
    pub delivered_at: Option<i64>,
}
#[derive(Debug, Clone, Default, PartialEq, Eq)]
pub struct RecoveryCounts {
    pub jobs: i64,
    pub outbox: i64,
    pub idempotency: i64,
    pub audit: i64,
    pub consumed_events: i64,
    pub consumer_effects: i64,
}
#[derive(Debug, Clone)]
pub struct Metadata {
    pub engine: String,
    pub engine_version: String,
    pub fsync: String,
    pub synchronous_commit: String,
    pub wal_level: String,
    pub transaction_isolation: String,
    pub canonicalization_version: String,
    pub durability_profile: String,
}

/// A single-connection adapter. PostgreSQL advisory locks provide cross-process
/// idempotency linearizability; the mutex only serializes this client's transactions.
pub struct PostgresAdapter {
    client: Mutex<Client>,
    schema: String,
    fault_hook: Option<FaultHook>,
}

impl PostgresAdapter {
    pub async fn connect(dsn: &str) -> StorageResult<Self> {
        Self::connect_options(dsn, "e002_rust", None).await
    }
    pub async fn connect_with_schema(dsn: &str, schema: &str) -> StorageResult<Self> {
        Self::connect_options(dsn, schema, None).await
    }
    pub async fn connect_with_fault_hook<F>(dsn: &str, schema: &str, hook: F) -> StorageResult<Self>
    where
        F: Fn(&str) -> bool + Send + Sync + 'static,
    {
        Self::connect_options(dsn, schema, Some(Arc::new(hook))).await
    }
    async fn connect_options(
        dsn: &str,
        schema: &str,
        fault_hook: Option<FaultHook>,
    ) -> StorageResult<Self> {
        validate_text(dsn, "postgres_dsn")?;
        validate_identifier(schema)?;
        let (client, connection) = tokio_postgres::connect(dsn, NoTls).await?;
        tokio::spawn(async move {
            if let Err(error) = connection.await {
                eprintln!("E-002 Rust PostgreSQL connection task ended: {error}");
            }
        });
        let adapter = Self {
            client: Mutex::new(client),
            schema: schema.to_owned(),
            fault_hook,
        };
        adapter.initialize().await?;
        let meta = adapter.metadata().await?;
        if meta.fsync != "on" || meta.synchronous_commit != "on" {
            return Err(invalid(format!(
                "postgres_durability_profile_required: fsync={} synchronous_commit={}",
                meta.fsync, meta.synchronous_commit
            )));
        }
        Ok(adapter)
    }
    fn table(&self, name: &str) -> String {
        format!(
            "{}.{}",
            quote_identifier(&self.schema),
            quote_identifier(name)
        )
    }
    fn fault(&self, stage: &str) -> StorageResult<()> {
        if self.fault_hook.as_ref().is_some_and(|hook| hook(stage)) {
            return Err(invalid(format!("injected_failure:{stage}")));
        }
        Ok(())
    }
    async fn initialize(&self) -> StorageResult<()> {
        let mut client = self.client.lock().await;
        let tx = client.transaction().await?;
        let schema_lock = format!("e002-rust-schema:{}", self.schema);
        tx.query_one(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            &[&schema_lock],
        )
        .await?;
        tx.batch_execute("SET LOCAL synchronous_commit = on")
            .await?;
        tx.batch_execute(&format!(
            "CREATE SCHEMA IF NOT EXISTS {}",
            quote_identifier(&self.schema)
        ))
        .await?;
        let jobs = self.table("e002_jobs");
        let idem = self.table("e002_idempotency_records");
        let outbox = self.table("e002_outbox");
        let audit = self.table("e002_audit");
        let consumed = self.table("e002_consumed_events");
        let effects = self.table("e002_consumer_effects");
        let trigger_fn = format!(
            "{}.{}",
            quote_identifier(&self.schema),
            quote_identifier("reject_audit_mutation")
        );
        let statements = vec![
            format!("CREATE TABLE IF NOT EXISTS {jobs} (job_id UUID PRIMARY KEY, tenant_id TEXT NOT NULL, operation_id TEXT NOT NULL, payload_json TEXT NOT NULL, state TEXT NOT NULL CHECK(state IN ('queued','completed','failed')), created_at BIGINT NOT NULL)"),
            format!("CREATE TABLE IF NOT EXISTS {idem} (tenant_id TEXT NOT NULL, operation_id TEXT NOT NULL, idempotency_key TEXT NOT NULL, request_hash TEXT NOT NULL, job_id UUID NOT NULL REFERENCES {jobs}(job_id), outcome_json TEXT NOT NULL, PRIMARY KEY(tenant_id,operation_id,idempotency_key))"),
            format!("CREATE TABLE IF NOT EXISTS {outbox} (event_id UUID PRIMARY KEY, tenant_id TEXT NOT NULL, operation_id TEXT NOT NULL, job_id UUID NOT NULL UNIQUE REFERENCES {jobs}(job_id), payload_json TEXT NOT NULL, created_at BIGINT NOT NULL, lease_owner TEXT, lease_token BIGINT NOT NULL DEFAULT 0, lease_until BIGINT, delivered_at BIGINT)"),
            format!("CREATE TABLE IF NOT EXISTS {audit} (sequence BIGSERIAL PRIMARY KEY, event_id UUID NOT NULL UNIQUE, request_id TEXT NOT NULL, tenant_id TEXT NOT NULL, operation_id TEXT NOT NULL, decision TEXT NOT NULL CHECK(decision IN ('allow','deny')), reason_code TEXT NOT NULL, outcome_json TEXT NOT NULL, created_at BIGINT NOT NULL)"),
            format!("CREATE TABLE IF NOT EXISTS {consumed} (consumer TEXT NOT NULL, event_id UUID NOT NULL REFERENCES {outbox}(event_id), consumed_at BIGINT NOT NULL, PRIMARY KEY(consumer,event_id))"),
            format!("CREATE TABLE IF NOT EXISTS {effects} (consumer TEXT NOT NULL, event_id UUID NOT NULL, effect_json TEXT NOT NULL, PRIMARY KEY(consumer,event_id), FOREIGN KEY(consumer,event_id) REFERENCES {consumed}(consumer,event_id))"),
            format!("CREATE OR REPLACE FUNCTION {trigger_fn}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit_append_only'; END; $$"),
        ];
        for statement in statements {
            tx.batch_execute(&statement).await?;
        }
        let audit_relation = format!(
            "{}.{}",
            quote_identifier(&self.schema),
            quote_identifier("e002_audit")
        );
        for (name, ddl) in [
            ("e002_audit_no_update", format!("CREATE TRIGGER e002_audit_no_update BEFORE UPDATE ON {audit} FOR EACH ROW EXECUTE FUNCTION {trigger_fn}()")),
            ("e002_audit_no_delete", format!("CREATE TRIGGER e002_audit_no_delete BEFORE DELETE ON {audit} FOR EACH ROW EXECUTE FUNCTION {trigger_fn}()")),
            ("e002_audit_no_truncate", format!("CREATE TRIGGER e002_audit_no_truncate BEFORE TRUNCATE ON {audit} FOR EACH STATEMENT EXECUTE FUNCTION {trigger_fn}()")),
        ] {
            let exists: bool = tx.query_one(
                "SELECT EXISTS (SELECT 1 FROM pg_trigger WHERE tgname=$1 AND tgrelid=$2::text::regclass AND NOT tgisinternal)",
                &[&name, &audit_relation],
            ).await?.get(0);
            if !exists { tx.batch_execute(&ddl).await?; }
        }
        tx.commit().await?;
        Ok(())
    }
    #[cfg(test)]
    async fn reset_for_testing(&self) -> StorageResult<()> {
        {
            let client = self.client.lock().await;
            client
                .batch_execute(&format!(
                    "DROP SCHEMA IF EXISTS {} CASCADE",
                    quote_identifier(&self.schema)
                ))
                .await?;
        }
        self.initialize().await
    }
    async fn insert_audit_tx(
        &self,
        tx: &Transaction<'_>,
        event: &AuditEvent,
    ) -> StorageResult<i64> {
        validate_text(&event.request_id, "request_id")?;
        validate_text(&event.tenant_id, "tenant_id")?;
        validate_text(&event.operation_id, "operation_id")?;
        validate_text(&event.reason_code, "reason_code")?;
        if event.decision != "allow" && event.decision != "deny" {
            return Err(invalid("invalid_audit_decision"));
        }
        if event.created_at < 0 {
            return Err(invalid("invalid_audit_timestamp"));
        }
        let event_id = Uuid::new_v4().to_string();
        let outcome = encode_json(&event.outcome)?;
        let sql = format!("INSERT INTO {} (event_id,request_id,tenant_id,operation_id,decision,reason_code,outcome_json,created_at) VALUES ($1::text::uuid,$2,$3,$4,$5,$6,$7,$8) RETURNING sequence", self.table("e002_audit"));
        let row = tx
            .query_one(
                &sql,
                &[
                    &event_id,
                    &event.request_id,
                    &event.tenant_id,
                    &event.operation_id,
                    &event.decision,
                    &event.reason_code,
                    &outcome,
                    &event.created_at,
                ],
            )
            .await?;
        Ok(row.get(0))
    }
    pub async fn append_audit(&self, event: AuditEvent) -> StorageResult<i64> {
        self.fault("before_audit_begin")?;
        let mut client = self.client.lock().await;
        let tx = client.transaction().await?;
        tx.batch_execute("SET LOCAL synchronous_commit = on")
            .await?;
        self.fault("before_audit_insert")?;
        let sequence = self.insert_audit_tx(&tx, &event).await?;
        tx.commit().await?;
        self.fault("after_audit_commit")?;
        Ok(sequence)
    }
    pub async fn admit_job(&self, request: AdmissionRequest) -> StorageResult<AdmissionResult> {
        validate_text(&request.tenant_id, "tenant_id")?;
        validate_text(&request.operation_id, "operation_id")?;
        validate_text(&request.idempotency_key, "idempotency_key")?;
        if request.audit.operation_id != request.operation_id
            || request.audit.tenant_id != request.tenant_id
        {
            return Err(invalid("audit_scope_mismatch"));
        }
        if request.audit.created_at < 0 {
            return Err(invalid("invalid_created_at"));
        }
        let payload_json = encode_json(&request.payload)?;
        let outbox_json = encode_json(&request.outbox_payload)?;
        let request_hash = canonical_hash(
            &json!({"operation_id":request.operation_id,"payload":request.payload}),
        )?;
        let scope = serde_json::to_string(&json!([
            request.tenant_id,
            request.operation_id,
            request.idempotency_key
        ]))?;
        self.fault("before_begin")?;
        let mut client = self.client.lock().await;
        let tx = client.transaction().await?;
        tx.batch_execute("SET LOCAL synchronous_commit = on")
            .await?;
        tx.query_one(
            "SELECT pg_advisory_xact_lock(hashtextextended($1, 0))",
            &[&scope],
        )
        .await?;
        let lookup = format!("SELECT request_hash,outcome_json FROM {} WHERE tenant_id=$1 AND operation_id=$2 AND idempotency_key=$3", self.table("e002_idempotency_records"));
        if let Some(row) = tx
            .query_opt(
                &lookup,
                &[
                    &request.tenant_id,
                    &request.operation_id,
                    &request.idempotency_key,
                ],
            )
            .await?
        {
            let prior_hash: String = row.get(0);
            let prior_outcome: String = row.get(1);
            let (status, outcome, decision, reason) = if prior_hash == request_hash {
                (
                    "replayed",
                    serde_json::from_str::<Value>(&prior_outcome)?,
                    "allow",
                    "IDEMPOTENCY_REPLAY",
                )
            } else {
                (
                    "conflict",
                    json!({"code":"IDEMPOTENCY_PAYLOAD_CONFLICT"}),
                    "deny",
                    "IDEMPOTENCY_PAYLOAD_CONFLICT",
                )
            };
            let event = AuditEvent {
                request_id: request.audit.request_id,
                tenant_id: request.tenant_id,
                operation_id: request.operation_id,
                decision: decision.into(),
                reason_code: reason.into(),
                outcome: outcome.clone(),
                created_at: request.audit.created_at,
            };
            self.insert_audit_tx(&tx, &event).await?;
            tx.commit().await?;
            return Ok(AdmissionResult {
                status: status.into(),
                outcome,
            });
        }
        let job_id = Uuid::new_v4().to_string();
        let event_id = Uuid::new_v4().to_string();
        let outcome = json!({"job_id":job_id,"state":"queued"});
        let outcome_json = encode_json(&outcome)?;
        let now = request.audit.created_at;
        let insert_job = format!("INSERT INTO {} (job_id,tenant_id,operation_id,payload_json,state,created_at) VALUES ($1::text::uuid,$2,$3,$4,'queued',$5)",self.table("e002_jobs"));
        tx.execute(
            &insert_job,
            &[
                &job_id,
                &request.tenant_id,
                &request.operation_id,
                &payload_json,
                &now,
            ],
        )
        .await?;
        self.fault("after_job")?;
        let insert_outbox = format!("INSERT INTO {} (event_id,tenant_id,operation_id,job_id,payload_json,created_at) VALUES ($1::text::uuid,$2,$3,$4::text::uuid,$5,$6)",self.table("e002_outbox"));
        tx.execute(
            &insert_outbox,
            &[
                &event_id,
                &request.tenant_id,
                &request.operation_id,
                &job_id,
                &outbox_json,
                &now,
            ],
        )
        .await?;
        self.fault("after_outbox")?;
        let insert_idem = format!("INSERT INTO {} (tenant_id,operation_id,idempotency_key,request_hash,job_id,outcome_json) VALUES ($1,$2,$3,$4,$5::text::uuid,$6)",self.table("e002_idempotency_records"));
        tx.execute(
            &insert_idem,
            &[
                &request.tenant_id,
                &request.operation_id,
                &request.idempotency_key,
                &request_hash,
                &job_id,
                &outcome_json,
            ],
        )
        .await?;
        self.fault("after_idempotency")?;
        let event = AuditEvent {
            request_id: request.audit.request_id,
            tenant_id: request.tenant_id,
            operation_id: request.operation_id,
            decision: "allow".into(),
            reason_code: "JOB_ADMITTED".into(),
            outcome: outcome.clone(),
            created_at: now,
        };
        self.insert_audit_tx(&tx, &event).await?;
        self.fault("after_audit")?;
        self.fault("before_commit")?;
        tx.commit().await?;
        self.fault("after_commit")?;
        Ok(AdmissionResult {
            status: "created".into(),
            outcome,
        })
    }
    pub async fn lookup_idempotency(
        &self,
        tenant: &str,
        operation: &str,
        key: &str,
    ) -> StorageResult<Option<IdempotencyRecord>> {
        let sql = format!("SELECT tenant_id,operation_id,idempotency_key,request_hash,job_id::text,outcome_json FROM {} WHERE tenant_id=$1 AND operation_id=$2 AND idempotency_key=$3",self.table("e002_idempotency_records"));
        let client = self.client.lock().await;
        let Some(row) = client.query_opt(&sql, &[&tenant, &operation, &key]).await? else {
            return Ok(None);
        };
        let outcome: String = row.get(5);
        Ok(Some(IdempotencyRecord {
            tenant_id: row.get(0),
            operation_id: row.get(1),
            idempotency_key: row.get(2),
            request_hash: row.get(3),
            job_id: row.get(4),
            outcome: serde_json::from_str(&outcome)?,
        }))
    }
    pub async fn read_job(&self, job_id: &str) -> StorageResult<Option<Job>> {
        let sql = format!("SELECT job_id::text,tenant_id,operation_id,payload_json,state,created_at FROM {} WHERE job_id=$1::text::uuid",self.table("e002_jobs"));
        let client = self.client.lock().await;
        let Some(row) = client.query_opt(&sql, &[&job_id]).await? else {
            return Ok(None);
        };
        let payload: String = row.get(3);
        Ok(Some(Job {
            job_id: row.get(0),
            tenant_id: row.get(1),
            operation_id: row.get(2),
            payload: serde_json::from_str(&payload)?,
            state: row.get(4),
            created_at: row.get(5),
        }))
    }
    fn outbox_from_row(row: &Row) -> StorageResult<OutboxEvent> {
        let payload: String = row.get(4);
        Ok(OutboxEvent {
            event_id: row.get(0),
            tenant_id: row.get(1),
            operation_id: row.get(2),
            job_id: row.get(3),
            payload: serde_json::from_str(&payload)?,
            created_at: row.get(5),
            lease_owner: row.get(6),
            lease_token: row.get(7),
            lease_until: row.get(8),
            delivered_at: row.get(9),
        })
    }
    pub async fn read_outbox_for_job(&self, job_id: &str) -> StorageResult<Option<OutboxEvent>> {
        let sql = format!("SELECT event_id::text,tenant_id,operation_id,job_id::text,payload_json,created_at,lease_owner,lease_token,lease_until,delivered_at FROM {} WHERE job_id=$1::text::uuid",self.table("e002_outbox"));
        let client = self.client.lock().await;
        let Some(row) = client.query_opt(&sql, &[&job_id]).await? else {
            return Ok(None);
        };
        Ok(Some(Self::outbox_from_row(&row)?))
    }
    pub async fn read_outbox(&self, event_id: &str) -> StorageResult<Option<OutboxEvent>> {
        let sql = format!("SELECT event_id::text,tenant_id,operation_id,job_id::text,payload_json,created_at,lease_owner,lease_token,lease_until,delivered_at FROM {} WHERE event_id=$1::text::uuid",self.table("e002_outbox"));
        let client = self.client.lock().await;
        let Some(row) = client.query_opt(&sql, &[&event_id]).await? else {
            return Ok(None);
        };
        Ok(Some(Self::outbox_from_row(&row)?))
    }
    pub async fn claim_outbox(
        &self,
        consumer: &str,
        limit: i64,
        lease_seconds: i64,
        now: i64,
    ) -> StorageResult<Vec<OutboxEvent>> {
        validate_text(consumer, "consumer")?;
        if !(1..=1000).contains(&limit) || lease_seconds < 1 || now < 0 {
            return Err(invalid("invalid_outbox_claim"));
        }
        let lease_until = now
            .checked_add(lease_seconds)
            .ok_or_else(|| invalid("outbox_lease_overflow"))?;
        let mut client = self.client.lock().await;
        let tx = client.transaction().await?;
        tx.batch_execute("SET LOCAL synchronous_commit = on")
            .await?;
        let select = format!("SELECT event_id::text FROM {} WHERE delivered_at IS NULL AND (lease_until IS NULL OR lease_until <= $1) ORDER BY created_at,event_id LIMIT $2 FOR UPDATE SKIP LOCKED",self.table("e002_outbox"));
        let ids: Vec<String> = tx
            .query(&select, &[&now, &limit])
            .await?
            .iter()
            .map(|r| r.get(0))
            .collect();
        let update = format!("UPDATE {} SET lease_owner=$1,lease_token=lease_token+1,lease_until=$2 WHERE event_id=$3::text::uuid AND delivered_at IS NULL",self.table("e002_outbox"));
        let read = format!("SELECT event_id::text,tenant_id,operation_id,job_id::text,payload_json,created_at,lease_owner,lease_token,lease_until,delivered_at FROM {} WHERE event_id=$1::text::uuid",self.table("e002_outbox"));
        let mut result = Vec::with_capacity(ids.len());
        for id in ids {
            tx.execute(&update, &[&consumer, &lease_until, &id]).await?;
            result.push(Self::outbox_from_row(&tx.query_one(&read, &[&id]).await?)?);
        }
        tx.commit().await?;
        Ok(result)
    }
    pub async fn ack_outbox(
        &self,
        event_id: &str,
        consumer: &str,
        lease_token: i64,
        now: i64,
    ) -> StorageResult<bool> {
        validate_text(event_id, "event_id")?;
        validate_text(consumer, "consumer")?;
        if lease_token < 1 || now < 0 {
            return Err(invalid("invalid_outbox_ack"));
        }
        let sql=format!("UPDATE {} SET delivered_at=$1,lease_owner=NULL,lease_until=NULL WHERE event_id=$2::text::uuid AND lease_owner=$3 AND lease_token=$4 AND lease_until>$1 AND delivered_at IS NULL",self.table("e002_outbox"));
        let mut client = self.client.lock().await;
        let tx = client.transaction().await?;
        tx.batch_execute("SET LOCAL synchronous_commit = on")
            .await?;
        let changed = tx
            .execute(&sql, &[&now, &event_id, &consumer, &lease_token])
            .await?;
        tx.commit().await?;
        Ok(changed == 1)
    }
    pub async fn apply_consumer_effect(
        &self,
        consumer: &str,
        event_id: &str,
        effect: &Value,
        now: i64,
    ) -> StorageResult<bool> {
        validate_text(consumer, "consumer")?;
        validate_text(event_id, "event_id")?;
        if now < 0 {
            return Err(invalid("invalid_consumer_timestamp"));
        }
        let effect_json = encode_json(effect)?;
        let mut client = self.client.lock().await;
        let tx = client.transaction().await?;
        tx.batch_execute("SET LOCAL synchronous_commit = on")
            .await?;
        let insert=format!("INSERT INTO {} (consumer,event_id,consumed_at) VALUES ($1,$2::text::uuid,$3) ON CONFLICT (consumer,event_id) DO NOTHING",self.table("e002_consumed_events"));
        let changed = tx.execute(&insert, &[&consumer, &event_id, &now]).await?;
        if changed == 0 {
            let read = format!(
                "SELECT effect_json FROM {} WHERE consumer=$1 AND event_id=$2::text::uuid",
                self.table("e002_consumer_effects")
            );
            let row = tx.query_one(&read, &[&consumer, &event_id]).await?;
            let previous: String = row.get(0);
            if previous != effect_json {
                return Err(invalid("consumer_effect_payload_conflict"));
            }
            tx.commit().await?;
            return Ok(false);
        }
        let effect_sql = format!(
            "INSERT INTO {} (consumer,event_id,effect_json) VALUES ($1,$2::text::uuid,$3)",
            self.table("e002_consumer_effects")
        );
        tx.execute(&effect_sql, &[&consumer, &event_id, &effect_json])
            .await?;
        tx.commit().await?;
        Ok(true)
    }
    pub async fn recover(&self) -> StorageResult<RecoveryCounts> {
        let client = self.client.lock().await;
        let count = |name: &str| format!("SELECT COUNT(*) FROM {}", self.table(name));
        Ok(RecoveryCounts {
            jobs: client.query_one(&count("e002_jobs"), &[]).await?.get(0),
            outbox: client.query_one(&count("e002_outbox"), &[]).await?.get(0),
            idempotency: client
                .query_one(&count("e002_idempotency_records"), &[])
                .await?
                .get(0),
            audit: client.query_one(&count("e002_audit"), &[]).await?.get(0),
            consumed_events: client
                .query_one(&count("e002_consumed_events"), &[])
                .await?
                .get(0),
            consumer_effects: client
                .query_one(&count("e002_consumer_effects"), &[])
                .await?
                .get(0),
        })
    }
    pub async fn metadata(&self) -> StorageResult<Metadata> {
        let client = self.client.lock().await;
        let engine_version: String = client.query_one("SHOW server_version", &[]).await?.get(0);
        let fsync: String = client.query_one("SHOW fsync", &[]).await?.get(0);
        let synchronous_commit: String = client
            .query_one("SHOW synchronous_commit", &[])
            .await?
            .get(0);
        let wal_level: String = client.query_one("SHOW wal_level", &[]).await?.get(0);
        let transaction_isolation: String = client
            .query_one("SHOW transaction_isolation", &[])
            .await?
            .get(0);
        Ok(Metadata {
            engine: "postgresql".into(),
            engine_version,
            fsync,
            synchronous_commit,
            wal_level,
            transaction_isolation,
            canonicalization_version: CANONICALIZATION_VERSION.into(),
            durability_profile: "fsync=on + synchronous_commit=on".into(),
        })
    }
}

fn invalid(message: impl Into<String>) -> Box<dyn Error + Send + Sync> {
    Box::new(io::Error::new(io::ErrorKind::InvalidInput, message.into()))
}
fn validate_text(value: &str, name: &str) -> StorageResult<()> {
    if value.trim().is_empty() || value.len() > 512 {
        Err(invalid(format!("invalid_{name}")))
    } else {
        Ok(())
    }
}
fn validate_identifier(value: &str) -> StorageResult<()> {
    let mut chars = value.chars();
    let first = chars.next().is_some_and(|c| c.is_ascii_lowercase());
    if !first
        || !chars.all(|c| c.is_ascii_lowercase() || c.is_ascii_digit() || c == '_')
        || value.len() > 63
    {
        Err(invalid("invalid_schema"))
    } else {
        Ok(())
    }
}
fn quote_identifier(value: &str) -> String {
    format!("\"{}\"", value.replace('"', "\"\""))
}
fn encode_json(value: &Value) -> StorageResult<String> {
    if !value.is_object() {
        return Err(invalid("json_value_must_be_object"));
    }
    Ok(serde_json::to_string(value)?)
}
fn canonical_hash(value: &Value) -> StorageResult<String> {
    let encoded = serde_json::to_vec(value)?;
    let mut hash = Sha256::new();
    hash.update(CANONICALIZATION_VERSION.as_bytes());
    hash.update([0]);
    hash.update(encoded);
    Ok(format!("{:x}", hash.finalize()))
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        process::Command,
        sync::atomic::{AtomicBool, Ordering},
    };
    const SCHEMA: &str = "e002_rust_test";
    static TEST_LOCK: tokio::sync::Mutex<()> = tokio::sync::Mutex::const_new(());
    async fn open(reset: bool) -> StorageResult<PostgresAdapter> {
        let dsn = std::env::var("AGENT_NATIVE_E002_POSTGRES_DSN")
            .map_err(|_| invalid("AGENT_NATIVE_E002_POSTGRES_DSN is required"))?;
        let adapter = PostgresAdapter::connect_with_schema(&dsn, SCHEMA).await?;
        if reset {
            adapter.reset_for_testing().await?;
        }
        Ok(adapter)
    }
    fn request(id: &str, tenant: &str, operation: &str, key: &str, name: &str) -> AdmissionRequest {
        AdmissionRequest {
            tenant_id: tenant.into(),
            operation_id: operation.into(),
            idempotency_key: key.into(),
            payload: json!({"name":name}),
            outbox_payload: json!({"topic":"job.created","name":name}),
            audit: AuditEvent {
                request_id: id.into(),
                tenant_id: tenant.into(),
                operation_id: operation.into(),
                decision: "allow".into(),
                reason_code: "AUTHORIZED".into(),
                outcome: json!({"name":name}),
                created_at: 100,
            },
        }
    }
    #[tokio::test]
    async fn test_append_audit_durable() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let a = open(true).await?;
        let n = a
            .append_audit(AuditEvent {
                request_id: "audit-1".into(),
                tenant_id: "tenant-a".into(),
                operation_id: "catalog.read".into(),
                decision: "allow".into(),
                reason_code: "AUTHORIZED".into(),
                outcome: json!({"id":"1"}),
                created_at: 100,
            })
            .await?;
        assert!(n > 0);
        let audit = a.table("e002_audit");
        {
            let client = a.client.lock().await;
            assert!(client
                .execute(&format!("UPDATE {audit} SET reason_code='tampered'"), &[])
                .await
                .is_err());
            assert!(client
                .execute(&format!("DELETE FROM {audit}"), &[])
                .await
                .is_err());
            assert!(client
                .execute(&format!("TRUNCATE {audit}"), &[])
                .await
                .is_err());
        }
        drop(a);
        let reopened = open(false).await?;
        assert_eq!(reopened.recover().await?.audit, 1);
        Ok(())
    }
    #[tokio::test]
    async fn test_atomic_job_outbox_idempotency_audit_commit() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let a = open(true).await?;
        let r = a
            .admit_job(request("admit", "tenant-a", "jobs.create", "key", "lamp"))
            .await?;
        assert_eq!(r.status, "created");
        let id = r.outcome["job_id"].as_str().unwrap();
        assert_eq!(a.read_job(id).await?.unwrap().state, "queued");
        assert_eq!(a.read_outbox_for_job(id).await?.unwrap().job_id, id);
        assert_eq!(
            a.lookup_idempotency("tenant-a", "jobs.create", "key")
                .await?
                .unwrap()
                .job_id,
            id
        );
        let c = a.recover().await?;
        assert_eq!((c.jobs, c.outbox, c.idempotency, c.audit), (1, 1, 1, 1));
        let m = a.metadata().await?;
        assert_eq!(m.fsync, "on");
        assert_eq!(m.synchronous_commit, "on");
        assert_eq!(m.transaction_isolation, "read committed");
        assert!(!m.engine_version.is_empty());
        assert!(!m.wal_level.is_empty());
        Ok(())
    }
    #[tokio::test]
    async fn test_rollback_after_each_logical_write() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let dsn =
            std::env::var("AGENT_NATIVE_E002_POSTGRES_DSN").map_err(|_| invalid("missing DSN"))?;
        for (i, stage) in [
            "after_job",
            "after_outbox",
            "after_idempotency",
            "after_audit",
            "before_commit",
        ]
        .iter()
        .enumerate()
        {
            let schema = format!("e002_rust_fault_{i}");
            let target = (*stage).to_owned();
            let a = PostgresAdapter::connect_with_fault_hook(&dsn, &schema, move |s| {
                s == target.as_str()
            })
            .await?;
            a.reset_for_testing().await?;
            assert!(a
                .admit_job(request("fault", "tenant-a", "jobs.create", "key", "lamp"))
                .await
                .is_err());
            let c = a.recover().await?;
            assert_eq!(
                (c.jobs, c.outbox, c.idempotency, c.audit),
                (0, 0, 0, 0),
                "fault at {stage}"
            );
        }
        Ok(())
    }
    #[tokio::test]
    async fn test_same_key_replay_and_different_hash_conflict() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let a = open(true).await?;
        let x = a
            .admit_job(request("one", "tenant-a", "jobs.create", "same", "lamp"))
            .await?;
        let y = a
            .admit_job(request("retry", "tenant-a", "jobs.create", "same", "lamp"))
            .await?;
        let z = a
            .admit_job(request(
                "conflict",
                "tenant-a",
                "jobs.create",
                "same",
                "desk",
            ))
            .await?;
        assert_eq!(x.status, "created");
        assert_eq!(y.status, "replayed");
        assert_eq!(x.outcome, y.outcome);
        assert_eq!(z.status, "conflict");
        let tenant_scope = a
            .admit_job(request(
                "tenant-reuse",
                "tenant-b",
                "jobs.create",
                "same",
                "lamp",
            ))
            .await?;
        let operation_scope = a
            .admit_job(request(
                "operation-reuse",
                "tenant-a",
                "catalog.create",
                "same",
                "lamp",
            ))
            .await?;
        assert_eq!(tenant_scope.status, "created");
        assert_eq!(operation_scope.status, "created");
        let c = a.recover().await?;
        assert_eq!((c.jobs, c.outbox, c.idempotency, c.audit), (3, 3, 3, 5));
        assert_ne!(tenant_scope.outcome, operation_scope.outcome);
        Ok(())
    }
    #[tokio::test]
    async fn test_concurrent_different_hashes_have_one_stable_winner() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let dsn =
            std::env::var("AGENT_NATIVE_E002_POSTGRES_DSN").map_err(|_| invalid("missing DSN"))?;
        let setup = open(true).await?;
        drop(setup);
        let a = PostgresAdapter::connect_with_schema(&dsn, SCHEMA).await?;
        let b = PostgresAdapter::connect_with_schema(&dsn, SCHEMA).await?;
        let first = tokio::spawn(async move {
            a.admit_job(request(
                "race-a",
                "tenant-a",
                "jobs.create",
                "diff-key",
                "lamp",
            ))
            .await
        });
        let second = tokio::spawn(async move {
            b.admit_job(request(
                "race-b",
                "tenant-a",
                "jobs.create",
                "diff-key",
                "desk",
            ))
            .await
        });
        let x = first.await.map_err(|e| invalid(e.to_string()))??;
        let y = second.await.map_err(|e| invalid(e.to_string()))??;
        let created = if x.status == "created" {
            x.clone()
        } else {
            y.clone()
        };
        let conflict = if x.status == "conflict" { x } else { y };
        assert_eq!(created.status, "created");
        assert_eq!(conflict.status, "conflict");
        let a = open(false).await?;
        let record = a
            .lookup_idempotency("tenant-a", "jobs.create", "diff-key")
            .await?
            .unwrap();
        assert_eq!(record.outcome, created.outcome);
        let counts = a.recover().await?;
        assert_eq!(
            (counts.jobs, counts.outbox, counts.idempotency, counts.audit),
            (1, 1, 1, 2)
        );
        Ok(())
    }
    #[tokio::test]
    async fn test_concurrent_same_key_admission_is_linearizable() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let dsn =
            std::env::var("AGENT_NATIVE_E002_POSTGRES_DSN").map_err(|_| invalid("missing DSN"))?;
        let setup = open(true).await?;
        drop(setup);
        let mut adapters = Vec::with_capacity(32);
        for _ in 0..32 {
            adapters.push(PostgresAdapter::connect_with_schema(&dsn, SCHEMA).await?);
        }
        let mut tasks = Vec::new();
        for (i, a) in adapters.into_iter().enumerate() {
            tasks.push(tokio::spawn(async move {
                a.admit_job(request(
                    &format!("race-{i}"),
                    "tenant-a",
                    "jobs.create",
                    "race-key",
                    "lamp",
                ))
                .await
            }));
        }
        let (mut created, mut replayed) = (0, 0);
        for t in tasks {
            match t
                .await
                .map_err(|e| invalid(e.to_string()))??
                .status
                .as_str()
            {
                "created" => created += 1,
                "replayed" => replayed += 1,
                other => return Err(invalid(format!("unexpected {other}"))),
            }
        }
        assert_eq!((created, replayed), (1, 31));
        let a = open(false).await?;
        let c = a.recover().await?;
        assert_eq!((c.jobs, c.outbox, c.idempotency, c.audit), (1, 1, 1, 32));
        Ok(())
    }
    #[tokio::test]
    async fn test_audit_unavailable_fails_closed() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let a = open(true).await?;
        let audit = a.table("e002_audit");
        let f = format!(
            "{}.{}",
            quote_identifier(SCHEMA),
            quote_identifier("reject_audit_insert")
        );
        {
            let c = a.client.lock().await;
            c.batch_execute(&format!("CREATE OR REPLACE FUNCTION {f}() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'audit_unavailable'; END; $$; CREATE TRIGGER reject_audit_insert BEFORE INSERT ON {audit} FOR EACH ROW EXECUTE FUNCTION {f}();")).await?;
        }
        assert!(a
            .admit_job(request("down", "tenant-a", "jobs.create", "key", "lamp"))
            .await
            .is_err());
        let c = a.recover().await?;
        assert_eq!((c.jobs, c.outbox, c.idempotency), (0, 0, 0));
        Ok(())
    }
    #[tokio::test]
    async fn crash_after_commit_child() -> StorageResult<()> {
        if std::env::var_os("AGENT_NATIVE_E002_CRASH_CHILD").is_none() {
            return Ok(());
        }
        let dsn =
            std::env::var("AGENT_NATIVE_E002_POSTGRES_DSN").map_err(|_| invalid("missing DSN"))?;
        let once = Arc::new(AtomicBool::new(true));
        let gate = once.clone();
        let a = PostgresAdapter::connect_with_fault_hook(&dsn, SCHEMA, move |s| {
            s == "after_commit" && gate.swap(false, Ordering::SeqCst)
        })
        .await?;
        assert!(a
            .admit_job(request(
                "crash-child",
                "tenant-a",
                "jobs.create",
                "crash-key",
                "lamp"
            ))
            .await
            .is_err());
        std::process::exit(86);
    }
    #[tokio::test]
    async fn test_crash_after_commit_before_response_reconciles() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let setup = open(true).await?;
        drop(setup);
        let executable = std::env::current_exe()?;
        let status = Command::new(executable)
            .arg("--exact")
            .arg("storage::tests::crash_after_commit_child")
            .arg("--nocapture")
            .env("AGENT_NATIVE_E002_CRASH_CHILD", "1")
            .status()?;
        assert_eq!(
            status.code(),
            Some(86),
            "child must terminate after durable commit and before response"
        );
        let a = open(false).await?;
        assert_eq!(
            a.admit_job(request(
                "retry",
                "tenant-a",
                "jobs.create",
                "crash-key",
                "lamp"
            ))
            .await?
            .status,
            "replayed"
        );
        let c = a.recover().await?;
        assert_eq!((c.jobs, c.outbox, c.idempotency, c.audit), (1, 1, 1, 2));
        Ok(())
    }
    #[tokio::test]
    async fn test_outbox_lease_expiry_and_owner_fencing() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let a = open(true).await?;
        let r = a
            .admit_job(request("outbox", "tenant-a", "jobs.create", "key", "lamp"))
            .await?;
        let id = r.outcome["job_id"].as_str().unwrap();
        let event = a.read_outbox_for_job(id).await?.unwrap().event_id;
        let first = a.claim_outbox("worker-a", 1, 10, 100).await?.pop().unwrap();
        let second = a.claim_outbox("worker-b", 1, 10, 111).await?.pop().unwrap();
        assert!(second.lease_token > first.lease_token);
        assert!(
            !a.ack_outbox(&event, "worker-a", first.lease_token, 112)
                .await?
        );
        assert!(
            a.ack_outbox(&event, "worker-b", second.lease_token, 112)
                .await?
        );
        Ok(())
    }
    #[tokio::test]
    async fn test_consumer_deduplicates_local_effect() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let a = open(true).await?;
        let r = a
            .admit_job(request("effect", "tenant-a", "jobs.create", "key", "lamp"))
            .await?;
        let id = r.outcome["job_id"].as_str().unwrap();
        let event = a.read_outbox_for_job(id).await?.unwrap().event_id;
        assert!(
            a.apply_consumer_effect("indexer", &event, &json!({"indexed":id}), 100)
                .await?
        );
        assert!(
            !a.apply_consumer_effect("indexer", &event, &json!({"indexed":id}), 101)
                .await?
        );
        assert!(a
            .apply_consumer_effect("indexer", &event, &json!({"indexed":"different"}), 102)
            .await
            .is_err());
        let c = a.recover().await?;
        assert_eq!((c.consumed_events, c.consumer_effects), (1, 1));
        Ok(())
    }
    #[tokio::test]
    async fn test_recover_committed_state() -> StorageResult<()> {
        let _guard = TEST_LOCK.lock().await;
        let a = open(true).await?;
        let r = a
            .admit_job(request("recover", "tenant-a", "jobs.create", "key", "desk"))
            .await?;
        let id = r.outcome["job_id"].as_str().unwrap();
        let c = a.recover().await?;
        assert_eq!((c.jobs, c.outbox, c.idempotency, c.audit), (1, 1, 1, 1));
        assert_eq!(a.read_job(id).await?.unwrap().payload["name"], "desk");
        Ok(())
    }
}
