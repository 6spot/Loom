//! Public backend context supplied to validator scenarios.

use loom_client::LoomClient;

/// Client-only context available to a validator scenario.
///
/// Keeping the client as the only backend authority makes the supported
/// consumer boundary explicit: a scenario can call Loom's public transport
/// client, but cannot receive a Runtime handle or a Storage implementation.
#[derive(Clone, Debug)]
pub struct BackendContext {
    client: LoomClient,
}

impl BackendContext {
    /// Creates a context from the supported public Loom client.
    #[must_use]
    pub const fn new(client: LoomClient) -> Self {
        Self { client }
    }

    /// Borrows the public Loom client used by this context.
    #[must_use]
    pub const fn client(&self) -> &LoomClient {
        &self.client
    }
}
