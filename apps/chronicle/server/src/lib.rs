//! Chronicle C1-T2 application server library.
//!
//! The server owns the Chronicle HTTP boundary for C1: distinct public and
//! Studio API namespaces, single-administrator Studio authentication from
//! environment configuration, health/error behavior, and the same-origin web
//! front. Historical reads stay on the proven C0 Python read model behind
//! `CHRONICLE_UPSTREAM_URL`, so this crate introduces no second historical
//! read authority and takes no Loom Runtime/Storage authority.
//!
//! Governance: no `loom-*` dependency, no SQLx/PostgreSQL driver dependency,
//! no inline SQL. Persistence lives in the registered Chronicle product
//! persistence root (`apps/chronicle/persistence/`) behind
//! `CHRONICLE_DATABASE_URL` (Architecture Amendment 0006).

#![forbid(unsafe_code)]

pub mod app;
pub mod auth;
pub mod config;
pub mod error;
pub mod static_assets;
pub mod upstream;

pub use app::{build_router, AppState};
pub use auth::{credentials_match, parse_basic_credentials};
pub use config::{AdminCredentials, ChronicleConfig};
pub use error::{error_body, TypedError};
pub use upstream::{fetch_upstream, forward_upstream, UpstreamTarget, MAX_PROXY_BODY_BYTES};
