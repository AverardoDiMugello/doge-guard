use axum::{http::StatusCode, routing::get, Json, Router};
use serde::{Deserialize, Serialize};
use tracing_subscriber;

async fn root() -> &'static str {
    "Hello Doge Guard Server"
}

#[tokio::main]
async fn main() {
    tracing_subscriber::fmt::init();

    let app = Router::new().route("/", get(root));
    let listener = tokio::net::TcpListener::bind("localhost:3000")
        .await
        .unwrap();
    axum::serve(listener, app).await.unwrap();
}
