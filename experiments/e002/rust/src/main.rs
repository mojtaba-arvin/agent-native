use std::{net::SocketAddr, sync::Arc, time::Duration};

use agent_native_e002_rust::{handle_with_product, product::ProductConfig, MAX_ACTIVE_WORK};
use hyper::{server::conn::http1, service::service_fn};
use hyper_util::rt::{TokioIo, TokioTimer};
use tokio::{
    net::{TcpListener, TcpStream},
    sync::{OwnedSemaphorePermit, Semaphore},
    task::JoinSet,
    time::{sleep, timeout},
};

const MAX_CONNECTIONS: usize = 64;
const HEADER_READ_TIMEOUT: Duration = Duration::from_secs(2);
const MAX_CONNECTION_LIFETIME: Duration = Duration::from_secs(60);

fn try_acquire_connection_slot(slots: &Arc<Semaphore>) -> Option<OwnedSemaphorePermit> {
    Arc::clone(slots).try_acquire_owned().ok()
}

async fn serve_connection(
    stream: TcpStream,
    work_slots: Arc<Semaphore>,
    product: Option<Arc<ProductConfig>>,
) {
    let io = TokioIo::new(stream);
    let service = service_fn(move |request| {
        handle_with_product(request, Arc::clone(&work_slots), product.clone())
    });
    let mut builder = http1::Builder::new();
    builder
        .timer(TokioTimer::new())
        .header_read_timeout(HEADER_READ_TIMEOUT);

    match timeout(
        MAX_CONNECTION_LIFETIME,
        builder.serve_connection(io, service),
    )
    .await
    {
        Ok(Ok(())) => {}
        Ok(Err(error)) => eprintln!("connection error: {error}"),
        Err(_) => eprintln!("connection lifetime exceeded"),
    }
}

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let product = ProductConfig::from_env()
        .map_err(|error| std::io::Error::new(std::io::ErrorKind::Other, error))?;
    let address: SocketAddr = "127.0.0.1:8080".parse()?;
    let listener = TcpListener::bind(address).await?;
    let connection_slots = Arc::new(Semaphore::new(MAX_CONNECTIONS));
    let work_slots = Arc::new(Semaphore::new(MAX_ACTIVE_WORK));
    let mut connections = JoinSet::new();

    loop {
        tokio::select! {
            accepted = listener.accept() => {
                let (stream, _) = accepted?;
                let Some(permit) = try_acquire_connection_slot(&connection_slots) else {
                    // Deterministic overload policy: close newly accepted sockets
                    // instead of spawning an unbounded task queue.
                    drop(stream);
                    continue;
                };
                let work_slots = Arc::clone(&work_slots);
                let product = product.clone();
                connections.spawn(async move {
                    let _permit = permit;
                    serve_connection(stream, work_slots, product).await;
                });
            }
            Some(result) = connections.join_next(), if !connections.is_empty() => {
                if let Err(error) = result {
                    eprintln!("connection task failed: {error}");
                }
            }
        }
    }
}

#[cfg(test)]
mod t17_connection_tests {
    use super::*;
    use tokio::io::{AsyncReadExt, AsyncWriteExt};

    #[test]
    fn t17_connection_admission_is_bounded_and_releases_capacity() {
        let slots = Arc::new(Semaphore::new(1));
        let held = try_acquire_connection_slot(&slots).expect("first connection is admitted");
        assert!(try_acquire_connection_slot(&slots).is_none());
        drop(held);
        assert_eq!(slots.available_permits(), 1);
        assert!(try_acquire_connection_slot(&slots).is_some());
    }

    #[tokio::test]
    async fn t17_stalled_headers_time_out_and_next_request_succeeds() {
        let listener = TcpListener::bind("127.0.0.1:0").await.unwrap();
        let address = listener.local_addr().unwrap();
        let connection_slots = Arc::new(Semaphore::new(1));
        let work_slots = Arc::new(Semaphore::new(MAX_ACTIVE_WORK));
        let server_slots = Arc::clone(&connection_slots);
        let server_work_slots = Arc::clone(&work_slots);

        let server = tokio::spawn(async move {
            for _ in 0..2 {
                let (stream, _) = listener.accept().await.unwrap();
                let permit = try_acquire_connection_slot(&server_slots)
                    .expect("capacity is released after the previous connection closes");
                serve_connection(stream, Arc::clone(&server_work_slots), None).await;
                drop(permit);
            }
        });

        let mut stalled = TcpStream::connect(address).await.unwrap();
        stalled
            .write_all(b"GET /health HTTP/1.1\r\nHost:")
            .await
            .unwrap();

        timeout(HEADER_READ_TIMEOUT + Duration::from_secs(2), async {
            while connection_slots.available_permits() == 0 {
                sleep(Duration::from_millis(10)).await;
            }
        })
        .await
        .expect("stalled header must release its connection slot");

        assert_eq!(connection_slots.available_permits(), 1);

        let mut valid = TcpStream::connect(address).await.unwrap();
        valid
            .write_all(
                b"GET /health HTTP/1.1\r\nHost: localhost\r\nConnection: close\r\n\r\n",
            )
            .await
            .unwrap();
        let mut response = Vec::new();
        timeout(Duration::from_secs(2), async {
            let mut chunk = [0_u8; 512];
            while !response.windows(2).any(|window| window == b"ok") {
                let count = valid.read(&mut chunk).await?;
                if count == 0 {
                    break;
                }
                response.extend_from_slice(&chunk[..count]);
            }
            Ok::<(), std::io::Error>(())
        })
        .await
        .expect("valid request must not hang")
        .unwrap();
        let response = String::from_utf8_lossy(&response);
        assert!(response.contains("200 OK"), "{response}");
        assert!(response.contains("ok"), "{response}");

        timeout(Duration::from_secs(2), server)
            .await
            .expect("server test task must finish")
            .unwrap();
    }
}
