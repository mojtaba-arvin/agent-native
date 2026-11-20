//! Testable Rust implementation of the shared E-002 HTTP workload contract.
//!
//! This is a runtime spike, not a selected Agent Native production runtime.
//! The executable listener is provided by the crate binary.

pub mod product;

use std::{convert::Infallible, sync::Arc, time::Duration};

use bytes::Bytes;
use futures_util::stream;
use http_body_util::{BodyExt, Full, StreamBody, combinators::BoxBody};
use hyper::{
    body::{Frame, Incoming},
    Request, Response, StatusCode,
};
use tokio::{sync::{OwnedSemaphorePermit, Semaphore}, time};

pub const WORK_DEADLINE: Duration = Duration::from_millis(750);
pub const MAX_WORK_MS: u64 = 5_000;
pub const MAX_ACTIVE_WORK: usize = 64;

pub type ResponseBody = BoxBody<Bytes, Infallible>;

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum WorkFailure {
    InvalidDuration,
    Overloaded,
    DeadlineExceeded,
}

/// Parse only the registered raw query form: ms= plus ASCII decimal digits.
///
/// Additional parameters, reordered parameters, percent-encoded names, signs,
/// empty values, overflow, and values above the workload maximum are rejected.
pub fn parse_work_ms(query: Option<&str>) -> Option<u64> {
    let value = query?.strip_prefix("ms=")?;
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }

    value
        .parse::<u64>()
        .ok()
        .filter(|duration| *duration <= MAX_WORK_MS)
}

/// Perform one bounded work operation, distinguishing invalid input from timeout.
pub async fn execute_work(ms: u64) -> Result<String, WorkFailure> {
    if ms > MAX_WORK_MS {
        return Err(WorkFailure::InvalidDuration);
    }

    time::timeout(WORK_DEADLINE, time::sleep(Duration::from_millis(ms)))
        .await
        .map(|()| format!("completed:{ms}"))
        .map_err(|_| WorkFailure::DeadlineExceeded)
}

fn try_acquire_work_slot(slots: &Arc<Semaphore>) -> Option<OwnedSemaphorePermit> {
    Arc::clone(slots).try_acquire_owned().ok()
}

async fn execute_admitted_work(
    slots: &Arc<Semaphore>,
    ms: u64,
) -> Result<String, WorkFailure> {
    let _permit = try_acquire_work_slot(slots).ok_or(WorkFailure::Overloaded)?;
    execute_work(ms).await
}

fn response(status: StatusCode, body: impl Into<Bytes>) -> Response<ResponseBody> {
    Response::builder()
        .status(status)
        .body(Full::new(body.into()).map_err(|never| match never {}).boxed())
        .expect("static response is valid")
}

fn work_failure_response(failure: WorkFailure) -> Response<ResponseBody> {
    match failure {
        WorkFailure::InvalidDuration => response(StatusCode::BAD_REQUEST, "invalid ms"),
        WorkFailure::Overloaded => response(StatusCode::SERVICE_UNAVAILABLE, "overloaded"),
        WorkFailure::DeadlineExceeded => {
            response(StatusCode::GATEWAY_TIMEOUT, "deadline exceeded")
        }
    }
}

fn stream_response() -> Response<ResponseBody> {
    let frames = vec![
        Ok::<_, Infallible>(Frame::data(Bytes::from_static(b"chunk-1\n"))),
        Ok::<_, Infallible>(Frame::data(Bytes::from_static(b"chunk-2\n"))),
        Ok::<_, Infallible>(Frame::data(Bytes::from_static(b"chunk-3\n"))),
    ];

    Response::builder()
        .header("content-type", "application/octet-stream")
        .body(StreamBody::new(stream::iter(frames)).boxed())
        .expect("static response is valid")
}

/// Handle one HTTP request using the shared E-002 workload semantics.
pub async fn handle(
    request: Request<Incoming>,
    slots: Arc<Semaphore>,
) -> Result<Response<ResponseBody>, Infallible> {
    match request.uri().path() {
        "/health" => Ok(response(StatusCode::OK, "ok")),
        "/stream" => Ok(stream_response()),
        "/work" => {
            let Some(ms) = parse_work_ms(request.uri().query()) else {
                return Ok(response(StatusCode::BAD_REQUEST, "invalid ms"));
            };

            match execute_admitted_work(&slots, ms).await {
                Ok(body) => Ok(response(StatusCode::OK, body)),
                Err(failure) => Ok(work_failure_response(failure)),
            }
        }
        _ => Ok(response(StatusCode::NOT_FOUND, "not found")),
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use http_body_util::BodyExt;

    #[test]
    fn parser_accepts_canonical_decimal_values() {
        assert_eq!(parse_work_ms(Some("ms=0")), Some(0));
        assert_eq!(parse_work_ms(Some("ms=20")), Some(20));
        assert_eq!(parse_work_ms(Some("ms=5000")), Some(MAX_WORK_MS));
    }

    #[test]
    fn parser_rejects_noncanonical_query_values() {
        for query in [
            None,
            Some(""),
            Some("ms="),
            Some("other=20"),
            Some("x=1&ms=20"),
            Some("ms=20&x=1"),
            Some("ms=20&ms=21"),
            Some("%6ds=20"),
            Some("ms=+1"),
            Some("ms=-1"),
            Some("ms= 1"),
            Some("ms=5001"),
            Some("ms=18446744073709551616"),
        ] {
            assert_eq!(parse_work_ms(query), None, "query should be rejected: {query:?}");
        }
    }

    #[tokio::test]
    async fn work_completes_before_deadline() {
        assert_eq!(execute_work(20).await, Ok("completed:20".to_owned()));
    }

    #[tokio::test]
    async fn work_times_out_at_registered_deadline() {
        assert_eq!(
            execute_work(900).await,
            Err(WorkFailure::DeadlineExceeded)
        );
        assert_eq!(WORK_DEADLINE, Duration::from_millis(750));
    }

    #[tokio::test]
    async fn work_rejects_duration_above_registered_maximum() {
        assert_eq!(
            execute_work(MAX_WORK_MS + 1).await,
            Err(WorkFailure::InvalidDuration)
        );
    }

    #[tokio::test]
    async fn work_admission_is_bounded_and_releases_capacity() {
        let slots = Arc::new(Semaphore::new(1));
        let held = try_acquire_work_slot(&slots).expect("first request owns the only slot");

        assert_eq!(
            execute_admitted_work(&slots, 20).await,
            Err(WorkFailure::Overloaded)
        );

        drop(held);
        assert_eq!(
            execute_admitted_work(&slots, 900).await,
            Err(WorkFailure::DeadlineExceeded)
        );
        assert_eq!(slots.available_permits(), 1);

        assert_eq!(
            execute_admitted_work(&slots, 20).await,
            Ok("completed:20".to_owned())
        );
        assert_eq!(slots.available_permits(), 1);
        assert_eq!(MAX_ACTIVE_WORK, 64);
    }

    #[test]
    fn work_failure_responses_match_http_contract() {
        assert_eq!(
            work_failure_response(WorkFailure::InvalidDuration).status(),
            StatusCode::BAD_REQUEST
        );
        assert_eq!(
            work_failure_response(WorkFailure::Overloaded).status(),
            StatusCode::SERVICE_UNAVAILABLE
        );
        assert_eq!(
            work_failure_response(WorkFailure::DeadlineExceeded).status(),
            StatusCode::GATEWAY_TIMEOUT
        );
    }

    #[tokio::test]
    async fn stream_preserves_ordered_chunks() {
        let mut body = stream_response().into_body();
        let mut chunks = Vec::new();

        while let Some(frame) = body.frame().await {
            let data = frame
                .expect("stream frame must be valid")
                .into_data()
                .expect("stream frame must contain data");
            chunks.push(data.to_vec());
        }

        assert_eq!(
            chunks,
            vec![
                b"chunk-1\n".to_vec(),
                b"chunk-2\n".to_vec(),
                b"chunk-3\n".to_vec(),
            ]
        );
    }
}

/// Dispatch the T16 product routes when the product database/auth fixtures are configured.
pub async fn handle_with_product(
    request: Request<Incoming>,
    slots: Arc<Semaphore>,
    product: Option<Arc<product::ProductConfig>>,
) -> Result<Response<ResponseBody>, Infallible> {
    if request.uri().path().starts_with("/v1/") {
        return Ok(match product {
            Some(config) => config.handle(request).await,
            None => response(StatusCode::SERVICE_UNAVAILABLE, "product workload not configured"),
        });
    }
    handle(request, slots).await
}
