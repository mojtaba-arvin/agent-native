use std::{net::SocketAddr, sync::Arc};

use agent_native_e002_rust::{handle, MAX_ACTIVE_WORK};
use hyper::service::service_fn;
use hyper_util::rt::TokioIo;
use tokio::{net::TcpListener, sync::Semaphore};

#[tokio::main]
async fn main() -> Result<(), Box<dyn std::error::Error + Send + Sync>> {
    let address: SocketAddr = "127.0.0.1:8080".parse()?;
    let listener = TcpListener::bind(address).await?;
    let slots = Arc::new(Semaphore::new(MAX_ACTIVE_WORK));

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
