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

use crate::ResponseBody;

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
    read_token: String,
    deny_token: String,
    tenant: String,
}

impl ProductConfig {
    pub fn from_env() -> Result<Option<Arc<Self>>, String> {
        let read_token = env::var("T16_READ_TOKEN").unwrap_or_default();
        let deny_token = env::var("T16_DENY_TOKEN").unwrap_or_default();
        if read_token.is_empty() && deny_token.is_empty() {
            return Ok(None);
        }
        if read_token.is_empty() || deny_token.is_empty() {
            return Err("both_t16_bearer_fixtures_required".to_owned());
        }
        let dsn = env::var("T16_PSQL_DSN").unwrap_or_else(|_| {
            "postgresql://postgres@127.0.0.1:5432/agent_native?sslmode=disable".to_owned()
        });
        let tenant = env::var("T16_TENANT_ID").unwrap_or_else(|_| "tenant-a".to_owned());
        let pool = Arc::new(PgPool::new(&dsn, 32)?);
        Ok(Some(Arc::new(Self { pool, read_token, deny_token, tenant })))
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

        let authorization = header_text(&request, "authorization");
        let (principal, allowed) = if authorization == format!("Bearer {}", self.read_token) {
            ("benchmark-reader", true)
        } else if authorization == format!("Bearer {}", self.deny_token) {
            ("benchmark-limited", false)
        } else {
            return json_response(StatusCode::UNAUTHORIZED, r#"{"error":{"code":"UNAUTHORIZED"}}"#);
        };

        let method = request.method().as_str();
        let path = request.uri().path();
        let (mut operation, resource_id, mut status) = match (method, path) {
            ("GET", "/v1/records/fixture-0001") => ("authorized_read", "fixture-0001", StatusCode::OK),
            ("POST", "/v1/operations/validate") => ("validate_plan", "", StatusCode::OK),
            ("POST", "/v1/jobs") => ("job_admission", "", StatusCode::ACCEPTED),
            _ => return json_response(StatusCode::NOT_FOUND, r#"{"error":{"code":"NOT_FOUND"}}"#),
        };

        let idempotency_key = header_text(&request, "idempotency-key").to_owned();
        if operation == "job_admission" && !valid_header(&idempotency_key) {
            return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"IDEMPOTENCY_KEY_REQUIRED"}}"#);
        }
        if operation == "job_admission" && (!allowed || asserted_tenant != self.tenant) {
            operation = "expected_denial";
            status = StatusCode::FORBIDDEN;
        }
        if operation == "validate_plan" && (!allowed || asserted_tenant != self.tenant) {
            operation = "expected_denial";
            status = StatusCode::FORBIDDEN;
        }
        if operation == "authorized_read" && asserted_tenant != self.tenant {
            operation = "expected_denial";
            status = StatusCode::FORBIDDEN;
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
        let reason = if asserted_tenant != self.tenant {
            "TENANT_SCOPE_MISMATCH"
        } else {
            "CAPABILITY_DENIED"
        };
        let mut payload = format!(
            r#"{{"request_id":"{request_id}","principal_id":"{principal}","tenant_id":"{}","operation":"{operation}","resource_id":"{resource_id}","body":{body_text}"#,
            self.tenant
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
                } else {
                    status
                };
                json_response(actual_status, &body)
            }
            _ => json_response(StatusCode::SERVICE_UNAVAILABLE, r#"{"error":{"code":"DURABLE_OPERATION_FAILED"}}"#),
        }
    }
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
