use std::{convert::Infallible, net::SocketAddr, sync::Arc, time::Duration};

use bytes::Bytes;
use futures_util::stream;
use http_body_util::{BodyExt, Full, StreamBody, combinators::BoxBody};
use hyper::{body::Frame, service::service_fn, Request, Response, StatusCode};
use hyper_util::rt::TokioIo;
use tokio::{net::TcpListener, sync::Semaphore, time};

type ResponseBody = BoxBody<Bytes, Infallible>;

fn parse_ms(query: Option<&str>) -> Option<u64> {
    let value = query?.strip_prefix("ms=")?;
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    value.parse::<u64>().ok().filter(|value| *value <= 5000)
}

fn response(status: StatusCode, body: impl Into<Bytes>) -> Response<ResponseBody> {
    Response::builder()
        .status(status)
        .body(Full::new(body.into()).map_err(|never| match never {}).boxed())
        .expect("static response is valid")
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

async fn handle(
    request: Request<hyper::body::Incoming>,
    slots: Arc<Semaphore>,
) -> Result<Response<ResponseBody>, Infallible> {
    match request.uri().path() {
        "/health" => Ok(response(StatusCode::OK, "ok")),
        "/stream" => Ok(stream_response()),
        "/work" => {
            let Some(ms) = parse_ms(request.uri().query()) else {
                return Ok(response(StatusCode::BAD_REQUEST, "invalid ms"));
            };

            let Ok(_permit) = slots.try_acquire_owned() else {
                return Ok(response(StatusCode::SERVICE_UNAVAILABLE, "overloaded"));
            };

            match time::timeout(Duration::from_millis(750), time::sleep(Duration::from_millis(ms))).await {
                Ok(()) => Ok(response(StatusCode::OK, format!("completed:{ms}"))),
                Err(_) => Ok(response(StatusCode::GATEWAY_TIMEOUT, "deadline exceeded")),
            }
        }
        _ => Ok(response(StatusCode::NOT_FOUND, "not found")),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let address: SocketAddr = "127.0.0.1:8080".parse()?;
    let listener = TcpListener::bind(address).await?;
    let slots = Arc::new(Semaphore::new(64));

    loop {
        let (stream, _) = listener.accept().await?;
        let io = TokioIo::new(stream);
        let slots = Arc::clone(&slots);
        tokio::spawn(async move {
            let service = service_fn(move |request| handle(request, Arc::clone(&slots)));
            if let Err(error) = hyper::server::conn::http1::Builder::new()
                .serve_connection(io, service)
                .await
            {
                eprintln!("connection error: {error}");
            }
        });
    }
}
