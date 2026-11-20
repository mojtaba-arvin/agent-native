use std::{
    env,
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{
        mpsc::{sync_channel, Receiver, SyncSender},
        Arc, Mutex,
    },
};

use bytes::Bytes;
use http_body_util::{BodyExt, Full};
use hyper::{body::Incoming, header, Request, Response, StatusCode};

use crate::{ResponseBody, t16_auth::{authorize, verify_bearer}};

const MAX_BODY: usize = 16 * 1024;
const DONE: &str = "__T16_DONE__";

struct PsqlWorker {
    child: Child,
    stdin: ChildStdin,
    stdout: BufReader<ChildStdout>,
}

impl PsqlWorker {
    fn start(dsn: &str) -> Result<Self, String> {
        let mut child = Command::new("psql")
            .args(["-X", "-q", "-A", "-t", dsn])
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null())
            .spawn()
            .map_err(|error| format!("psql_start_failed:{error}"))?;
        let stdin = child.stdin.take().ok_or("psql_stdin_unavailable")?;
        let stdout = child.stdout.take().ok_or("psql_stdout_unavailable")?;
        Ok(Self { child, stdin, stdout: BufReader::new(stdout) })
    }

    fn query(&mut self, payload: &str) -> Result<String, String> {
        let quoted = payload.replace('\'', "''");
        let statement = format!("SELECT t16_handle('{quoted}'::jsonb)::text;\n\\echo {DONE}\n");
        self.stdin.write_all(statement.as_bytes()).map_err(|error| format!("psql_write_failed:{error}"))?;
        self.stdin.flush().map_err(|error| format!("psql_flush_failed:{error}"))?;

        let mut result = String::new();
        loop {
            let mut line = String::new();
            let count = self.stdout.read_line(&mut line).map_err(|error| format!("psql_read_failed:{error}"))?;
            if count == 0 {
                return Err("psql_worker_exited".to_owned());
            }
            let line = line.trim_end_matches(&['\r', '\n'][..]);
            if line == DONE {
                break;
            }
            if !line.is_empty() {
                if !result.is_empty() {
                    return Err("postgres_returned_multiple_rows".to_owned());
                }
                result.push_str(line);
            }
        }
        if result.is_empty() || !result.starts_with('{') || !result.ends_with('}') {
            return Err("postgres_product_operation_failed".to_owned());
        }
        Ok(result)
    }
}

impl Drop for PsqlWorker {
    fn drop(&mut self) {
        let _ = self.child.kill();
        let _ = self.child.wait();
    }
}

pub struct PgPool {
    sender: SyncSender<Arc<Mutex<PsqlWorker>>>,
    receiver: Mutex<Receiver<Arc<Mutex<PsqlWorker>>>>,
}

impl PgPool {
    pub fn new(dsn: &str, size: usize) -> Result<Self, String> {
        if size == 0 {
            return Err("invalid_psql_pool_size".to_owned());
        }
        let (sender, receiver) = sync_channel(size);
        for index in 0..size {
            let worker = PsqlWorker::start(dsn)
                .map_err(|error| format!("start_postgres_worker_{index}:{error}"))?;
            sender.send(Arc::new(Mutex::new(worker)))
                .map_err(|error| format!("initialize_psql_pool:{error}"))?;
        }
        Ok(Self { sender, receiver: Mutex::new(receiver) })
    }

    pub fn query(&self, payload: &str) -> Result<String, String> {
        let worker = {
            let receiver = self.receiver.lock().map_err(|_| "psql_pool_poisoned".to_owned())?;
            receiver.recv().map_err(|error| format!("psql_pool_receive:{error}"))?
        };
        let result = worker.lock()
            .map_err(|_| "psql_worker_poisoned".to_owned())?
            .query(payload);
        self.sender.send(worker).map_err(|error| format!("psql_pool_return:{error}"))?;
        result
    }
}

pub struct ProductConfig {
    pub pool: Arc<PgPool>,
    signing_key: Vec<u8>,
}

impl ProductConfig {
    pub fn from_env() -> Result<Option<Arc<Self>>, String> {
        let key_hex = env::var("T16_SIGNING_KEY").unwrap_or_default();
        if key_hex.is_empty() { return Ok(None); }
        let signing_key = crate::t16_auth::decode_hex(&key_hex)?;
        if signing_key.len() < 32 { return Err("t16_signing_key_must_be_32_bytes_of_hex".to_owned()); }
        let dsn = env::var("T16_PSQL_DSN").unwrap_or_else(|_| {
            "postgresql://postgres@127.0.0.1:5432/agent_native?sslmode=disable".to_owned()
        });
        let pool = Arc::new(PgPool::new(&dsn, 32)?);
        Ok(Some(Arc::new(Self { pool, signing_key })))
    }

    pub async fn handle(&self, request: Request<Incoming>) -> Response<ResponseBody> {
        if request.uri().query().is_some() {
            return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"QUERY_NOT_SUPPORTED"}}"#);
        }
        let request_id = header_text(&request, "x-request-id").to_owned();
        let asserted_tenant = header_text(&request, "x-tenant-id").to_owned();
        if !valid_header(&request_id) || !valid_header(&asserted_tenant) {
            return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"INVALID_REQUEST_CONTEXT"}}"#);
        }

        let identity = match verify_bearer(header_text(&request, "authorization"), &self.signing_key) {
            Ok(value) => value,
            Err(_) => return json_response(StatusCode::UNAUTHORIZED, r#"{"error":{"code":"UNAUTHORIZED"}}"#),
        };

        let method = request.method().as_str();
        let path = request.uri().path();
        let target_operation = match path {
            "/v1/records/fixture-0001" => "catalog.read",
            "/v1/operations/validate" => "operations.validate",
            "/v1/jobs" => "jobs.create",
            _ => "unknown",
        };
        let (mut operation, mut resource_id, mut status, required_capability, mut protected_resource) = match (method, path) {
            ("GET", "/v1/records/fixture-0001") => ("authorized_read", "fixture-0001".to_owned(), StatusCode::OK, "catalog.read", "/v1/records/fixture-0001".to_owned()),
            ("POST", "/v1/operations/validate") => ("validate_plan", String::new(), StatusCode::OK, "catalog.read", String::new()),
            ("POST", "/v1/jobs") => ("job_admission", String::new(), StatusCode::ACCEPTED, "jobs.create", "/v1/jobs".to_owned()),
            _ => return json_response(StatusCode::NOT_FOUND, r#"{"error":{"code":"NOT_FOUND"}}"#),
        };

        let idempotency_key = header_text(&request, "idempotency-key").to_owned();
        if operation == "job_admission" && !valid_header(&idempotency_key) {
            return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"IDEMPOTENCY_KEY_REQUIRED"}}"#);
        }
        let (_, body) = request.into_parts();
        let collected = match body.collect().await {
            Ok(value) => value.to_bytes(),
            Err(_) => return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"BODY_READ_FAILED"}}"#),
        };
        if collected.len() > MAX_BODY {
            return json_response(StatusCode::PAYLOAD_TOO_LARGE, r#"{"error":{"code":"BODY_TOO_LARGE"}}"#);
        }
        let body_text = if collected.is_empty() {
            "{}"
        } else {
            match std::str::from_utf8(&collected) {
                Ok(value) if value.trim_start().starts_with('{') && value.trim_end().ends_with('}') => value,
                _ => return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"INVALID_JSON_BODY"}}"#),
            }
        };

        if operation == "validate_plan" {
            match extract_resource_id(body_text) {
                Some(value) => {
                    resource_id = value.clone();
                    protected_resource = format!("/v1/records/{value}");
                }
                None => protected_resource = "/v1/records/invalid".to_owned(),
            }
        }
        let (mut authorized, mut reason) = authorize(&identity, required_capability, &protected_resource);
        if asserted_tenant != identity.tenant_id {
            authorized = false;
            reason = "TENANT_SCOPE_MISMATCH";
        }
        if !authorized {
            operation = "expected_denial";
            status = StatusCode::FORBIDDEN;
        }
        let mut payload = format!(
            r#"{{"request_id":"{request_id}","principal_id":"{}","tenant_id":"{}","operation":"{operation}","target_operation":"{target_operation}","resource_id":"{resource_id}","body":{body_text}"#,
            identity.principal_id, identity.tenant_id
        );
        if operation == "job_admission" || operation == "expected_denial" {
            payload.push_str(&format!(r#", "idempotency_key":"{idempotency_key}""#));
        }
        if operation == "expected_denial" {
            payload.push_str(&format!(r#", "reason_code":"{reason}""#));
        }
        payload.push('}');

        let pool = Arc::clone(&self.pool);
        let result = tokio::task::spawn_blocking(move || pool.query(&payload)).await;
        match result {
            Ok(Ok(body)) => {
                let actual_status = if body.contains(r#""code": "IDEMPOTENCY_CONFLICT""#) {
                    StatusCode::CONFLICT
                } else if body.contains(r#""code": "INVALID_CONTRACT""#) {
                    StatusCode::BAD_REQUEST
                } else {
                    status
                };
                json_response(actual_status, &body)
            }
            _ => json_response(StatusCode::SERVICE_UNAVAILABLE, r#"{"error":{"code":"DURABLE_OPERATION_FAILED"}}"#),
        }
    }
}

fn extract_resource_id(body: &str) -> Option<String> {
    let marker = r#""resource_id""#;
    if body.matches(marker).count() != 1 {
        return None;
    }
    let after_key = body.split_once(marker)?.1.trim_start();
    let after_colon = after_key.strip_prefix(':')?.trim_start();
    let quoted = after_colon.strip_prefix('"')?;
    let end = quoted.find('"')?;
    let value = &quoted[..end];
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_') {
        return None;
    }
    Some(value.to_owned())
}

fn header_text<'a>(request: &'a Request<Incoming>, name: &str) -> &'a str {
    request.headers().get(name).and_then(|value| value.to_str().ok()).unwrap_or("")
}

fn valid_header(value: &str) -> bool {
    !value.is_empty() && value.len() <= 128 &&
        value.bytes().all(|byte| byte.is_ascii_alphanumeric() || byte == b'-' || byte == b'_')
}

fn json_response(status: StatusCode, body: &str) -> Response<ResponseBody> {
    Response::builder()
        .status(status)
        .header(header::CONTENT_TYPE, "application/json")
        .body(Full::new(Bytes::from(body.to_owned())).map_err(|never| match never {}).boxed())
        .expect("static product response is valid")
}


#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn t16_header_validation_rejects_injection_and_empty_values() {
        assert!(valid_header("tenant-a"));
        assert!(valid_header("request_001"));
        assert!(!valid_header(""));
        assert!(!valid_header("tenant-a\nX-Admin: true"));
        assert!(!valid_header("tenant a"));
        assert!(!valid_header(&"x".repeat(129)));
    }

    #[test]
    fn t16_postgres_pool_executes_durable_authorized_read_when_configured() {
        let Ok(dsn) = env::var("T16_PSQL_DSN") else {
            return;
        };
        let pool = PgPool::new(&dsn, 32).expect("32 persistent psql sessions should start");
        let payload = r#"{"request_id":"rust-pg-read-1","principal_id":"benchmark-reader","tenant_id":"tenant-a","operation":"authorized_read","resource_id":"fixture-0001","body":{}}"#;
        let result = pool.query(payload).expect("PostgreSQL product function should return JSON");
        assert!(result.contains(r#""request_id": "rust-pg-read-1""#));
        assert!(result.contains(r#""id": "fixture-0001""#));
    }

    #[test]
    fn t16_postgres_pool_records_expected_denial_when_configured() {
        let Ok(dsn) = env::var("T16_PSQL_DSN") else {
            return;
        };
        let pool = PgPool::new(&dsn, 32).expect("32 persistent psql sessions should start");
        let payload = r#"{"request_id":"rust-pg-deny-1","principal_id":"benchmark-limited","tenant_id":"tenant-a","operation":"expected_denial","reason_code":"CAPABILITY_DENIED","body":{}}"#;
        let result = pool.query(payload).expect("denial audit should commit and return JSON");
        assert!(result.contains(r#""code": "CAPABILITY_DENIED""#));
    }
}
