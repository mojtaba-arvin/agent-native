use std::{
    collections::HashSet,
    env,
    io::{BufRead, BufReader, Write},
    process::{Child, ChildStdin, ChildStdout, Command, Stdio},
    sync::{
        mpsc::{sync_channel, Receiver, SyncSender},
        Arc, Mutex,
    },
};

use bytes::{Bytes, BytesMut};
use futures_util::stream;
use http_body_util::{BodyExt, Full, StreamBody};
use hyper::{body::{Body as HttpBody, Frame, Incoming}, header, Request, Response, StatusCode};
use tokio::time::{timeout_at, Duration, Instant};

use crate::{ResponseBody, t16_auth::{authorize, verify_bearer}};

const MAX_BODY: usize = 16 * 1024;
const BODY_READ_TIMEOUT: Duration = Duration::from_secs(5);
const DONE: &str = "__T16_DONE__";

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum BodyReadError {
    TooLarge,
    Timeout,
    ReadFailed,
}

// Consume body frames incrementally. Never call collect() on the untrusted
// Incoming body: enforce the byte limit before copying each frame.
async fn collect_bounded_body<B>(
    mut body: B,
    timeout: Duration,
) -> Result<Bytes, BodyReadError>
where
    B: HttpBody<Data = Bytes> + Unpin,
{
    let deadline = Instant::now() + timeout;
    let mut output = BytesMut::with_capacity(4096);
    loop {
        let frame = match timeout_at(deadline, body.frame()).await {
            Err(_) => return Err(BodyReadError::Timeout),
            Ok(None) => return Ok(output.freeze()),
            Ok(Some(Err(_))) => return Err(BodyReadError::ReadFailed),
            Ok(Some(Ok(frame))) => frame,
        };
        if let Ok(data) = frame.into_data() {
            if output.len().saturating_add(data.len()) > MAX_BODY {
                return Err(BodyReadError::TooLarge);
            }
            output.extend_from_slice(&data);
        }
    }
}

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

// Reject duplicate JSON object keys before PostgreSQL JSONB can collapse them.
// Keys are compared after escape decoding ("name" equals "\u006eame").
struct UniqueJsonScanner<'a> {
    bytes: &'a [u8],
    offset: usize,
}

impl<'a> UniqueJsonScanner<'a> {
    fn new(value: &'a str) -> Self {
        Self { bytes: value.as_bytes(), offset: 0 }
    }

    fn skip_whitespace(&mut self) {
        while self.offset < self.bytes.len()
            && matches!(self.bytes[self.offset], b' ' | b'\n' | b'\r' | b'\t')
        {
            self.offset += 1;
        }
    }

    fn parse_value(&mut self, depth: usize) -> Result<(), ()> {
        if depth > 64 { return Err(()); }
        self.skip_whitespace();
        match self.bytes.get(self.offset).copied() {
            Some(b'{') => self.parse_object(depth + 1),
            Some(b'[') => self.parse_array(depth + 1),
            Some(b'"') => self.parse_string().map(|_| ()),
            Some(_) => {
                let start = self.offset;
                while let Some(byte) = self.bytes.get(self.offset).copied() {
                    if matches!(byte, b',' | b']' | b'}' | b' ' | b'\n' | b'\r' | b'\t') {
                        break;
                    }
                    self.offset += 1;
                }
                if self.offset == start { Err(()) } else { Ok(()) }
            }
            None => Err(()),
        }
    }

    fn parse_object(&mut self, depth: usize) -> Result<(), ()> {
        self.offset += 1;
        self.skip_whitespace();
        if self.bytes.get(self.offset) == Some(&b'}') {
            self.offset += 1;
            return Ok(());
        }
        let mut keys = HashSet::new();
        loop {
            self.skip_whitespace();
            let key = self.parse_string()?;
            if !keys.insert(key) { return Err(()); }
            self.skip_whitespace();
            if self.bytes.get(self.offset) != Some(&b':') { return Err(()); }
            self.offset += 1;
            self.parse_value(depth)?;
            self.skip_whitespace();
            match self.bytes.get(self.offset) {
                Some(b',') => self.offset += 1,
                Some(b'}') => { self.offset += 1; return Ok(()); }
                _ => return Err(()),
            }
        }
    }

    fn parse_array(&mut self, depth: usize) -> Result<(), ()> {
        self.offset += 1;
        self.skip_whitespace();
        if self.bytes.get(self.offset) == Some(&b']') {
            self.offset += 1;
            return Ok(());
        }
        loop {
            self.parse_value(depth)?;
            self.skip_whitespace();
            match self.bytes.get(self.offset) {
                Some(b',') => self.offset += 1,
                Some(b']') => { self.offset += 1; return Ok(()); }
                _ => return Err(()),
            }
        }
    }

    fn read_hex4(&mut self) -> Result<u16, ()> {
        if self.offset + 4 > self.bytes.len() { return Err(()); }
        let digits = std::str::from_utf8(&self.bytes[self.offset..self.offset + 4]).map_err(|_| ())?;
        let value = u16::from_str_radix(digits, 16).map_err(|_| ())?;
        self.offset += 4;
        Ok(value)
    }

    fn parse_string(&mut self) -> Result<String, ()> {
        if self.bytes.get(self.offset) != Some(&b'"') { return Err(()); }
        self.offset += 1;
        let mut output = String::new();
        while self.offset < self.bytes.len() {
            let byte = self.bytes[self.offset];
            self.offset += 1;
            match byte {
                b'"' => return Ok(output),
                b'\\' => {
                    let escaped = *self.bytes.get(self.offset).ok_or(())?;
                    self.offset += 1;
                    match escaped {
                        b'"' => output.push('"'),
                        b'\\' => output.push('\\'),
                        b'/' => output.push('/'),
                        b'b' => output.push('\u{0008}'),
                        b'f' => output.push('\u{000c}'),
                        b'n' => output.push('\n'),
                        b'r' => output.push('\r'),
                        b't' => output.push('\t'),
                        b'u' => {
                            let first = self.read_hex4()? as u32;
                            let codepoint = if (0xD800..=0xDBFF).contains(&first) {
                                if self.bytes.get(self.offset..self.offset + 2) != Some(b"\\u") { return Err(()); }
                                self.offset += 2;
                                let second = self.read_hex4()? as u32;
                                if !(0xDC00..=0xDFFF).contains(&second) { return Err(()); }
                                0x10000 + ((first - 0xD800) << 10) + (second - 0xDC00)
                            } else if (0xDC00..=0xDFFF).contains(&first) {
                                return Err(());
                            } else { first };
                            output.push(char::from_u32(codepoint).ok_or(())?);
                        }
                        _ => return Err(()),
                    }
                }
                value if value < 0x20 => return Err(()),
                value if value < 0x80 => output.push(value as char),
                _ => {
                    let remaining = std::str::from_utf8(&self.bytes[self.offset - 1..]).map_err(|_| ())?;
                    let character = remaining.chars().next().ok_or(())?;
                    output.push(character);
                    self.offset += character.len_utf8() - 1;
                }
            }
        }
        Err(())
    }
}

fn validate_unique_json_keys(value: &str) -> Result<(), ()> {
    let mut scanner = UniqueJsonScanner::new(value);
    scanner.parse_value(0)?;
    scanner.skip_whitespace();
    if scanner.offset != scanner.bytes.len() { return Err(()); }
    Ok(())
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
        if request.headers().get(header::CONTENT_LENGTH)
            .and_then(|value| value.to_str().ok())
            .and_then(|value| value.parse::<usize>().ok())
            .is_some_and(|length| length > MAX_BODY)
        {
            return json_response(StatusCode::PAYLOAD_TOO_LARGE, r#"{"error":{"code":"BODY_TOO_LARGE"}}"#);
        }
        let (_, body) = request.into_parts();
        let collected = match collect_bounded_body(body, BODY_READ_TIMEOUT).await {
            Ok(value) => value,
            Err(BodyReadError::TooLarge) => {
                return json_response(StatusCode::PAYLOAD_TOO_LARGE, r#"{"error":{"code":"BODY_TOO_LARGE"}}"#)
            }
            Err(BodyReadError::Timeout) => {
                return json_response(StatusCode::REQUEST_TIMEOUT, r#"{"error":{"code":"BODY_READ_TIMEOUT"}}"#)
            }
            Err(BodyReadError::ReadFailed) => {
                return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"BODY_READ_FAILED"}}"#)
            }
        };
        let body_text = if collected.is_empty() {
            "{}"
        } else {
            match std::str::from_utf8(&collected) {
                Ok(value) if value.trim_start().starts_with('{') && value.trim_end().ends_with('}') => value,
                _ => return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"INVALID_JSON_BODY"}}"#),
            }
        };

        if validate_unique_json_keys(body_text).is_err() {
            return json_response(StatusCode::BAD_REQUEST, r#"{"error":{"code":"INVALID_JSON_BODY"}}"#);
        }

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
    fn t16_json_parser_rejects_duplicate_keys_including_escaped_equivalents() {
        assert!(validate_unique_json_keys(r#"{"operation":"catalog.read","operation":"jobs.create"}"#).is_err());
        assert!(validate_unique_json_keys(r#"{"payload":{"fixture":"safe","fixture":"overridden"}}"#).is_err());
        assert!(validate_unique_json_keys(r#"{"name":1,"\u006eame":2}"#).is_err());
        assert!(validate_unique_json_keys(r#"{"items":[{"id":1,"id":2}]}"#).is_err());
    }

    #[test]
    fn t16_json_parser_accepts_unique_nested_keys_and_unicode() {
        assert!(validate_unique_json_keys(r#"{"name":"lamp \uD83D\uDCA1","payload":{"count":2}}"#).is_ok());
    }

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
#[cfg(test)]
mod t17_body_tests {
    use super::*;
    use hyper::body::Frame;
    use std::convert::Infallible;

    #[tokio::test]
    async fn t17_exact_body_limit_is_accepted() {
        let body = Full::new(Bytes::from(vec![b'x'; MAX_BODY]));
        let result = collect_bounded_body(body, Duration::from_secs(1)).await.unwrap();
        assert_eq!(result.len(), MAX_BODY);
    }

    #[tokio::test]
    async fn t17_fixed_body_over_limit_is_rejected() {
        let body = Full::new(Bytes::from(vec![b'x'; MAX_BODY + 1]));
        assert_eq!(
            collect_bounded_body(body, Duration::from_secs(1)).await,
            Err(BodyReadError::TooLarge)
        );
    }

    #[tokio::test]
    async fn t17_chunked_body_over_limit_is_rejected() {
        let frames = stream::iter(vec![
            Ok::<_, Infallible>(Frame::data(Bytes::from(vec![b'a'; MAX_BODY / 2]))),
            Ok::<_, Infallible>(Frame::data(Bytes::from(vec![b'b'; MAX_BODY / 2]))),
            Ok::<_, Infallible>(Frame::data(Bytes::from_static(b"x"))),
        ]);
        let body = StreamBody::new(frames);
        assert_eq!(
            collect_bounded_body(body, Duration::from_secs(1)).await,
            Err(BodyReadError::TooLarge)
        );
    }

    #[tokio::test]
    async fn t17_slow_body_hits_total_read_deadline() {
        let frames = stream::once(async {
            tokio::time::sleep(Duration::from_millis(50)).await;
            Ok::<_, Infallible>(Frame::data(Bytes::from_static(b"{}")))
        });
        let body = StreamBody::new(frames);
        assert_eq!(
            collect_bounded_body(body, Duration::from_millis(1)).await,
            Err(BodyReadError::Timeout)
        );
    }
}
