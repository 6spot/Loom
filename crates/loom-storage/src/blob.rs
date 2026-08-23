//! Immutable `BlobStore` adapters.
//!
//! The adapters calculate BLAKE3 content identities and use immutable object
//! paths. The object-store adapter accepts an already-composed
//! `Arc<dyn object_store::ObjectStore>` so S3-compatible endpoint, credential
//! and secret configuration remains in the Application composition root.

use std::{
    collections::BTreeMap,
    fmt,
    path::Path as FsPath,
    sync::{Arc, RwLock},
};

use loom_runtime::{
    BlobError, BlobHash, BlobId, BlobMetadata, BlobObject, BlobRef, BlobStore, PersistenceFuture,
};
use object_store::{
    Attribute, AttributeValue, ObjectStore, ObjectStoreExt, PutMode, PutOptions,
    local::LocalFileSystem, path::Path,
};

fn content_hash(bytes: &[u8]) -> BlobHash {
    BlobHash::new(*blake3::hash(bytes).as_bytes())
}

fn make_reference(bytes: &[u8], content_type: Option<&str>) -> BlobRef {
    let hash = content_hash(bytes);
    BlobRef::new(
        BlobId::new(hash),
        BlobMetadata::new(
            hash,
            bytes.len() as u64,
            content_type.map(ToOwned::to_owned),
        ),
    )
}

fn verify_bytes(reference: &BlobRef, bytes: &[u8]) -> Result<(), BlobError> {
    if !reference.is_consistent() {
        return Err(BlobError::InvalidReference {
            id: reference.id,
            metadata_hash: reference.metadata.content_hash,
        });
    }
    let actual_size = bytes.len() as u64;
    if actual_size != reference.metadata.size {
        return Err(BlobError::SizeMismatch {
            expected: reference.metadata.size,
            actual: actual_size,
        });
    }
    let actual_hash = content_hash(bytes);
    if actual_hash != reference.metadata.content_hash {
        return Err(BlobError::HashMismatch {
            expected: reference.metadata.content_hash,
            actual: actual_hash,
        });
    }
    Ok(())
}

#[derive(Clone, Debug)]
struct StoredBlob {
    reference: BlobRef,
    bytes: Vec<u8>,
}

/// Deterministic in-memory immutable `BlobStore` used by tests and local
/// composition fixtures.
#[derive(Debug, Default, Clone)]
pub struct InMemoryBlobStore {
    blobs: Arc<RwLock<BTreeMap<BlobId, StoredBlob>>>,
}

impl InMemoryBlobStore {
    /// Creates an empty deterministic `BlobStore`.
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    /// Removes a blob from this adapter to simulate operational unavailability.
    ///
    /// The operation is intentionally concrete-adapter functionality; the
    /// Runtime port does not make deletion part of World history.
    ///
    /// # Errors
    ///
    /// Returns [`BlobError::NotFound`] when the reference is absent or
    /// [`BlobError::InvalidReference`] when its identity and metadata disagree.
    pub fn delete(&self, reference: &BlobRef) -> Result<(), BlobError> {
        Self::ensure_reference(reference)?;
        let mut blobs = self
            .blobs
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if blobs.remove(&reference.id).is_some() {
            Ok(())
        } else {
            Err(BlobError::NotFound { id: reference.id })
        }
    }

    /// Replaces the adapter's test body without changing its immutable
    /// reference, allowing a contract test to prove hash mismatch detection.
    ///
    /// # Errors
    ///
    /// Returns [`BlobError::NotFound`] when the reference is absent or
    /// [`BlobError::InvalidReference`] when its identity and metadata disagree.
    pub fn corrupt(&self, reference: &BlobRef, bytes: Vec<u8>) -> Result<(), BlobError> {
        Self::ensure_reference(reference)?;
        let mut blobs = self
            .blobs
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let blob = blobs
            .get_mut(&reference.id)
            .ok_or(BlobError::NotFound { id: reference.id })?;
        blob.bytes = bytes;
        Ok(())
    }

    fn ensure_reference(reference: &BlobRef) -> Result<(), BlobError> {
        if reference.is_consistent() {
            Ok(())
        } else {
            Err(BlobError::InvalidReference {
                id: reference.id,
                metadata_hash: reference.metadata.content_hash,
            })
        }
    }

    fn put_sync(&self, bytes: &[u8], content_type: Option<&str>) -> Result<BlobRef, BlobError> {
        let reference = make_reference(bytes, content_type);
        let mut blobs = self
            .blobs
            .write()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        if let Some(existing) = blobs.get(&reference.id) {
            verify_bytes(&existing.reference, &existing.bytes)?;
            if existing.reference.metadata.content_type != reference.metadata.content_type {
                return Err(BlobError::MetadataMismatch {
                    expected: existing.reference.metadata.content_type.clone(),
                    actual: reference.metadata.content_type,
                });
            }
            return Ok(existing.reference.clone());
        }
        blobs.insert(
            reference.id,
            StoredBlob {
                reference: reference.clone(),
                bytes: bytes.to_vec(),
            },
        );
        Ok(reference)
    }

    fn read_sync(&self, reference: &BlobRef) -> Result<BlobObject, BlobError> {
        Self::ensure_reference(reference)?;
        let blobs = self
            .blobs
            .read()
            .unwrap_or_else(std::sync::PoisonError::into_inner);
        let blob = blobs
            .get(&reference.id)
            .ok_or(BlobError::NotFound { id: reference.id })?;
        verify_bytes(reference, &blob.bytes)?;
        Ok(BlobObject {
            reference: reference.clone(),
            bytes: blob.bytes.clone(),
        })
    }
}

impl BlobStore for InMemoryBlobStore {
    fn put<'a>(
        &'a self,
        bytes: &'a [u8],
        content_type: Option<&'a str>,
    ) -> PersistenceFuture<'a, Result<BlobRef, BlobError>> {
        let result = self.put_sync(bytes, content_type);
        Box::pin(async move { result })
    }

    fn read<'a>(
        &'a self,
        reference: &'a BlobRef,
    ) -> PersistenceFuture<'a, Result<BlobObject, BlobError>> {
        let result = self.read_sync(reference);
        Box::pin(async move { result })
    }
}

/// Initialization failure for a concrete local/object-store adapter.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BlobStoreInitError {
    message: String,
}

impl BlobStoreInitError {
    fn new(message: impl Into<String>) -> Self {
        Self {
            message: message.into(),
        }
    }
}

impl fmt::Display for BlobStoreInitError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.message)
    }
}

impl std::error::Error for BlobStoreInitError {}

/// Provider-neutral adapter over the `object_store` contract.
///
/// Application composition chooses the concrete backend (S3-compatible,
/// local filesystem or another supported object store) and passes it here.
/// This type never accepts or stores endpoint, credential or secret config.
#[derive(Clone)]
pub struct ObjectStoreBlobStore {
    object_store: Arc<dyn ObjectStore>,
    prefix: Option<Path>,
}

impl fmt::Debug for ObjectStoreBlobStore {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ObjectStoreBlobStore")
            .field("prefix", &self.prefix)
            .finish_non_exhaustive()
    }
}

impl ObjectStoreBlobStore {
    /// Wraps an already configured object-store backend.
    #[must_use]
    pub fn new(object_store: Arc<dyn ObjectStore>) -> Self {
        Self {
            object_store,
            prefix: None,
        }
    }

    /// Wraps an object-store backend below a validated object path prefix.
    ///
    /// # Errors
    ///
    /// Returns [`BlobStoreInitError`] if the prefix is not a valid object path.
    pub fn with_prefix(
        object_store: Arc<dyn ObjectStore>,
        prefix: impl AsRef<str>,
    ) -> Result<Self, BlobStoreInitError> {
        let prefix = Path::parse(prefix.as_ref())
            .map_err(|error| BlobStoreInitError::new(error.to_string()))?;
        Ok(Self {
            object_store,
            prefix: (!prefix.is_root()).then_some(prefix),
        })
    }

    fn location(&self, id: BlobId) -> Path {
        let name = id.to_string();
        match &self.prefix {
            Some(prefix) => Path::from(format!("{prefix}/{name}")),
            None => Path::from(name),
        }
    }

    async fn put_inner(
        &self,
        bytes: Vec<u8>,
        content_type: Option<String>,
    ) -> Result<BlobRef, BlobError> {
        let reference = make_reference(&bytes, content_type.as_deref());
        let mut attributes = object_store::Attributes::new();
        if let Some(content_type) = &content_type {
            attributes.insert(
                Attribute::ContentType,
                AttributeValue::from(content_type.clone()),
            );
        }
        let options = PutOptions {
            mode: PutMode::Create,
            attributes,
            ..PutOptions::default()
        };
        let location = self.location(reference.id);
        match self
            .object_store
            .put_opts(&location, bytes.into(), options)
            .await
        {
            Ok(_) => Ok(reference),
            Err(object_store::Error::AlreadyExists { .. }) => {
                let (existing, existing_content_type) =
                    self.read_inner_with_metadata(&reference).await?;
                if existing_content_type != content_type {
                    return Err(BlobError::MetadataMismatch {
                        expected: existing_content_type,
                        actual: content_type,
                    });
                }
                let mut existing_reference = existing.reference;
                existing_reference.metadata.content_type = existing_content_type;
                Ok(existing_reference)
            }
            Err(error) => Err(map_object_store_error(reference.id, error)),
        }
    }

    async fn read_inner(&self, reference: &BlobRef) -> Result<BlobObject, BlobError> {
        self.read_inner_with_metadata(reference)
            .await
            .map(|(object, _)| object)
    }

    async fn read_inner_with_metadata(
        &self,
        reference: &BlobRef,
    ) -> Result<(BlobObject, Option<String>), BlobError> {
        if !reference.is_consistent() {
            return Err(BlobError::InvalidReference {
                id: reference.id,
                metadata_hash: reference.metadata.content_hash,
            });
        }
        let location = self.location(reference.id);
        let result = self
            .object_store
            .get(&location)
            .await
            .map_err(|error| map_object_store_error(reference.id, error))?;
        let reported_size = result.meta.size;
        let content_type = result
            .attributes
            .get(&Attribute::ContentType)
            .map(|value| value.as_ref().to_owned());
        let bytes = result
            .bytes()
            .await
            .map_err(|error| map_object_store_error(reference.id, error))?;
        if reported_size != bytes.len() as u64 {
            return Err(BlobError::SizeMismatch {
                expected: reported_size,
                actual: bytes.len() as u64,
            });
        }
        verify_bytes(reference, &bytes)?;
        Ok((
            BlobObject {
                reference: reference.clone(),
                bytes: bytes.to_vec(),
            },
            content_type,
        ))
    }

    /// Deletes one concrete object-store entry.
    ///
    /// This does not alter any Event/Facet reference or replay input. A later
    /// read reports [`BlobError::NotFound`].
    ///
    /// # Errors
    ///
    /// Returns a typed object-store access failure when deletion cannot be
    /// completed.
    pub async fn delete(&self, reference: &BlobRef) -> Result<(), BlobError> {
        if !reference.is_consistent() {
            return Err(BlobError::InvalidReference {
                id: reference.id,
                metadata_hash: reference.metadata.content_hash,
            });
        }
        self.object_store
            .delete(&self.location(reference.id))
            .await
            .map_err(|error| map_object_store_error(reference.id, error))
    }
}

impl BlobStore for ObjectStoreBlobStore {
    fn put<'a>(
        &'a self,
        bytes: &'a [u8],
        content_type: Option<&'a str>,
    ) -> PersistenceFuture<'a, Result<BlobRef, BlobError>> {
        Box::pin(self.put_inner(bytes.to_vec(), content_type.map(ToOwned::to_owned)))
    }

    fn read<'a>(
        &'a self,
        reference: &'a BlobRef,
    ) -> PersistenceFuture<'a, Result<BlobObject, BlobError>> {
        Box::pin(self.read_inner(reference))
    }
}

/// Local filesystem `BlobStore` adapter.
///
/// The filesystem root is application-owned configuration; the adapter only
/// receives a constructed path and stores content-addressed files below it.
#[derive(Clone, Debug)]
pub struct LocalBlobStore(ObjectStoreBlobStore);

impl LocalBlobStore {
    /// Opens a local object store rooted at an existing directory.
    ///
    /// # Errors
    ///
    /// Returns [`BlobStoreInitError`] when the root cannot be opened by the
    /// local object-store backend.
    pub fn new(root: impl AsRef<FsPath>) -> Result<Self, BlobStoreInitError> {
        let local = LocalFileSystem::new_with_prefix(root)
            .map_err(|error| BlobStoreInitError::new(error.to_string()))?;
        Ok(Self(ObjectStoreBlobStore::new(Arc::new(local))))
    }

    /// Wraps an already-created local/test object-store implementation.
    #[must_use]
    pub fn from_object_store(object_store: Arc<dyn ObjectStore>) -> Self {
        Self(ObjectStoreBlobStore::new(object_store))
    }

    /// Deletes one local object without changing its historical reference.
    ///
    /// # Errors
    ///
    /// Returns a typed object-store access failure when deletion cannot be
    /// completed.
    pub async fn delete(&self, reference: &BlobRef) -> Result<(), BlobError> {
        self.0.delete(reference).await
    }
}

impl BlobStore for LocalBlobStore {
    fn put<'a>(
        &'a self,
        bytes: &'a [u8],
        content_type: Option<&'a str>,
    ) -> PersistenceFuture<'a, Result<BlobRef, BlobError>> {
        self.0.put(bytes, content_type)
    }

    fn read<'a>(
        &'a self,
        reference: &'a BlobRef,
    ) -> PersistenceFuture<'a, Result<BlobObject, BlobError>> {
        self.0.read(reference)
    }
}

/// S3-compatible object-store adapter.
///
/// The S3 builder and all credentials/endpoints are intentionally composed by
/// the Application and injected as `Arc<dyn ObjectStore>`.
#[derive(Clone, Debug)]
pub struct S3CompatibleBlobStore(ObjectStoreBlobStore);

impl S3CompatibleBlobStore {
    /// Wraps an already configured S3-compatible backend.
    #[must_use]
    pub fn new(object_store: Arc<dyn ObjectStore>) -> Self {
        Self(ObjectStoreBlobStore::new(object_store))
    }

    /// Wraps an S3 backend below a validated object path prefix.
    ///
    /// # Errors
    ///
    /// Returns [`BlobStoreInitError`] when the prefix is not a valid object
    /// path.
    pub fn with_prefix(
        object_store: Arc<dyn ObjectStore>,
        prefix: impl AsRef<str>,
    ) -> Result<Self, BlobStoreInitError> {
        Ok(Self(ObjectStoreBlobStore::with_prefix(
            object_store,
            prefix,
        )?))
    }

    /// Deletes one object without changing its historical reference.
    ///
    /// # Errors
    ///
    /// Returns a typed object-store access failure when deletion cannot be
    /// completed.
    pub async fn delete(&self, reference: &BlobRef) -> Result<(), BlobError> {
        self.0.delete(reference).await
    }
}

impl BlobStore for S3CompatibleBlobStore {
    fn put<'a>(
        &'a self,
        bytes: &'a [u8],
        content_type: Option<&'a str>,
    ) -> PersistenceFuture<'a, Result<BlobRef, BlobError>> {
        self.0.put(bytes, content_type)
    }

    fn read<'a>(
        &'a self,
        reference: &'a BlobRef,
    ) -> PersistenceFuture<'a, Result<BlobObject, BlobError>> {
        self.0.read(reference)
    }
}

/// Compatibility name for the provider-neutral object-store adapter.
pub type ObjectStorageBlobStore = ObjectStoreBlobStore;
/// Short compatibility name for the S3-compatible adapter.
pub type S3BlobStore = S3CompatibleBlobStore;

fn map_object_store_error(id: BlobId, error: object_store::Error) -> BlobError {
    match error {
        object_store::Error::NotFound { .. } => BlobError::NotFound { id },
        error => BlobError::Unavailable {
            id,
            message: error.to_string(),
        },
    }
}

#[cfg(test)]
mod tests {
    use std::{fs, path::PathBuf, str::FromStr, sync::Arc};

    use super::{
        InMemoryBlobStore, LocalBlobStore, S3CompatibleBlobStore, content_hash, make_reference,
    };
    use loom_core::{
        EventId, EventSeq, EventTypeId, SchemaRevision, StateRevision, TimelineId, TimelineVersion,
        WorldId, WorldInstant,
    };
    use loom_protocol::ProposedEvent;
    use loom_runtime::{BaseWorldSnapshot, BlobError, BlobStore, CommittedEvent, ReplayEngine};
    use object_store::{ObjectStore, PutMode, PutOptions, memory::InMemory};
    use serde_json::json;

    async fn put(
        store: &impl BlobStore,
        bytes: &[u8],
        content_type: Option<&str>,
    ) -> loom_runtime::BlobRef {
        store
            .put(bytes, content_type)
            .await
            .expect("blob put should succeed")
    }

    async fn exercise_contract(store: &impl BlobStore) {
        let reference = put(store, b"immutable bytes", Some("text/plain")).await;
        assert_eq!(reference.id.hash(), content_hash(b"immutable bytes"));
        assert_eq!(reference.metadata.size, 15);
        assert_eq!(
            reference.metadata.content_type.as_deref(),
            Some("text/plain")
        );
        assert_eq!(
            store.read(&reference).await.unwrap().bytes(),
            b"immutable bytes"
        );
        assert_eq!(
            put(store, b"immutable bytes", Some("text/plain")).await,
            reference
        );
    }

    #[tokio::test]
    async fn in_memory_adapter_is_deterministic_and_detects_read_failures() {
        let store = InMemoryBlobStore::new();
        exercise_contract(&store).await;
        let reference = put(&store, b"corrupt me", None).await;
        store
            .corrupt(&reference, b"different bytes".to_vec())
            .unwrap();
        assert!(matches!(
            store.read(&reference).await,
            Err(BlobError::SizeMismatch { .. } | BlobError::HashMismatch { .. })
        ));
        store.delete(&reference).unwrap();
        assert!(matches!(
            store.read(&reference).await,
            Err(BlobError::NotFound { .. })
        ));
    }

    #[tokio::test]
    async fn object_store_adapter_proves_s3_compatible_contract_without_provider_config() {
        let backend: Arc<dyn ObjectStore> = Arc::new(InMemory::new());
        let store = S3CompatibleBlobStore::new(backend.clone());
        exercise_contract(&store).await;

        let no_metadata_reference = put(&store, b"x", None).await;
        assert!(matches!(
            store.put(b"x", Some("text/plain")).await,
            Err(BlobError::MetadataMismatch {
                expected: None,
                actual: Some(actual),
            }) if actual == "text/plain"
        ));
        assert_eq!(store.put(b"x", None).await.unwrap(), no_metadata_reference);
        assert_eq!(
            store.read(&no_metadata_reference).await.unwrap().bytes(),
            b"x"
        );

        let reference = put(&store, b"object body", Some("application/octet-stream")).await;
        let location = object_store::path::Path::from(reference.id.to_string());
        backend
            .put_opts(
                &location,
                b"tampered".to_vec().into(),
                PutOptions::from(PutMode::Overwrite),
            )
            .await
            .unwrap();
        assert!(matches!(
            store.read(&reference).await,
            Err(BlobError::SizeMismatch { .. } | BlobError::HashMismatch { .. })
        ));
        store.delete(&reference).await.unwrap();
        assert!(matches!(
            store.read(&reference).await,
            Err(BlobError::NotFound { .. })
        ));
    }

    #[tokio::test]
    async fn local_adapter_uses_content_addressed_paths_and_survives_reopen() {
        let root = unique_test_path("loom-blob-local");
        fs::create_dir_all(&root).unwrap();
        let reference;
        {
            let store = LocalBlobStore::new(&root).unwrap();
            reference = put(&store, b"local bytes", None).await;
        }
        let reopened = LocalBlobStore::new(&root).unwrap();
        assert_eq!(
            reopened.read(&reference).await.unwrap().bytes(),
            b"local bytes"
        );
        assert_eq!(reopened.put(b"local bytes", None).await.unwrap(), reference);
        assert_eq!(
            reopened.read(&reference).await.unwrap().bytes(),
            b"local bytes"
        );
        reopened.delete(&reference).await.unwrap();
        assert!(matches!(
            reopened.read(&reference).await,
            Err(BlobError::NotFound { .. })
        ));
        fs::remove_dir_all(root).unwrap();
    }

    #[tokio::test]
    async fn blob_unavailability_changes_only_blob_read_not_replay() {
        let store = InMemoryBlobStore::new();
        let reference = put(&store, b"history reference", Some("text/plain")).await;
        let world: WorldId = "00000000-0000-0000-0000-000000000001".parse().unwrap();
        let timeline: TimelineId = "00000000-0000-0000-0000-000000000002".parse().unwrap();
        let proposal = ProposedEvent::new(
            EventId::from_str("00000000-0000-0000-0000-000000000003").unwrap(),
            EventTypeId::from("blob.reference.recorded"),
            SchemaRevision::new(1),
            json!({"blob": reference}),
        );
        let event = CommittedEvent::from_proposed(
            timeline,
            EventSeq::new(1),
            &proposal,
            WorldInstant::new(1),
        );
        let initial = BaseWorldSnapshot::new(
            world,
            timeline,
            TimelineVersion::new(EventSeq::new(0), StateRevision::new(0)),
            WorldInstant::new(1),
        );
        let before = ReplayEngine::replay(initial.clone(), std::slice::from_ref(&event)).unwrap();
        store.delete(&reference).unwrap();
        assert!(matches!(
            store.read(&reference).await,
            Err(BlobError::NotFound { .. })
        ));
        let after = ReplayEngine::replay(initial, std::slice::from_ref(&event)).unwrap();
        assert_eq!(before.materialization(), after.materialization());
        assert_eq!(before.head_event_seq(), after.head_event_seq());
    }

    #[test]
    fn blob_reference_serialization_is_payload_safe() {
        let reference = make_reference(b"history reference", Some("text/plain"));
        let payload = json!({"blob": reference});
        assert_eq!(payload["blob"]["metadata"]["size"], 17);
    }

    fn unique_test_path(name: &str) -> PathBuf {
        let suffix = format!("{}-{}", std::process::id(), content_hash(name.as_bytes()));
        std::env::temp_dir().join(suffix)
    }
}
