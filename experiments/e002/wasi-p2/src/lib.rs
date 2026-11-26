use std::convert::Infallible;

use futures_lite::stream::unfold;
use wstd::http::body::Bytes;
use wstd::http::{Body, Error, Request, Response, StatusCode};
use wstd::time::Duration;

fn parse_ms(query: Option<&str>) -> Option<u64> {
    let value = query?.strip_prefix("ms=")?;
    if value.is_empty() || !value.bytes().all(|byte| byte.is_ascii_digit()) {
        return None;
    }
    value.parse::<u64>().ok().filter(|value| *value <= 5000)
}

#[wstd::http_server]
async fn main(request: Request<Body>) -> Result<Response<Body>, Error> {
    match request.uri().path() {
        "/health" => Ok(Response::new(Body::from("ok"))),
        "/work" => {
            let Some(ms) = parse_ms(request.uri().query()) else {
                return Ok(Response::builder()
                    .status(StatusCode::BAD_REQUEST)
                    .body(Body::from("invalid ms"))?);
            };

            if ms > 750 {
                wstd::task::sleep(Duration::from_millis(750)).await;
                return Ok(Response::builder()
                    .status(StatusCode::GATEWAY_TIMEOUT)
                    .body(Body::from("deadline exceeded"))?);
            }

            wstd::task::sleep(Duration::from_millis(ms)).await;
            Ok(Response::new(Body::from(format!("completed:{ms}"))))
        }
        "/stream" => {
            let chunks = unfold(1_u8, |index| async move {
                if index > 3 {
                    return None;
                }
                wstd::task::sleep(Duration::from_millis(10)).await;
                let bytes = Bytes::from(format!("chunk-{index}\n"));
                Some((Ok::<_, Infallible>(bytes), index + 1))
            });
            Ok(Response::new(Body::from_try_stream(chunks)))
        }
        _ => Ok(Response::builder()
            .status(StatusCode::NOT_FOUND)
            .body(Body::from("not found"))?),
    }
}
