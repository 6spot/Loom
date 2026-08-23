//! Runtime-owned immutable Blob/Object Storage contract.
//!
//! Blob values are references and metadata, not World State and not a second
//! authority. The `BlobStore` port is owned by Runtime because consumers of
//! blob content decide the narrow operation they need; concrete storage and
//! provider configuration stay in adapters/application composition.

use std::{fmt, str::FromStr, sync::Arc};

use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};

use crate::PersistenceFuture;

/// Number of bytes in a BLAKE3 content hash.
pub const BLOB_HASH_SIZE: usize = 32;

/// A fixed-size content hash used by immutable blob identity and integrity
/// checks.
///
/// Adapters calculate this value using the v0 BLAKE3 technical baseline. The
/// Runtime contract carries the stable digest value without depending on a
/// hashing or provider implementation.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct BlobHash([u8; BLOB_HASH_SIZE]);

impl BlobHash {
    /// Creates a hash from its already computed digest bytes.
    #[must_use]
    pub const fn new(bytes: [u8; BLOB_HASH_SIZE]) -> Self {
        Self(bytes)
    }

    /// Returns the digest bytes.
    #[must_use]
    pub const fn as_bytes(&self) -> &[u8; BLOB_HASH_SIZE] {
        &self.0
    }

    /// Parses a lower- or upper-case hexadecimal digest.
    ///
    /// # Errors
    ///
    /// Returns [`BlobHashParseError`] when the input is not exactly
    /// `BLOB_HASH_SIZE * 2` hexadecimal characters.
    pub fn from_hex(value: &str) -> Result<Self, BlobHashParseError> {
        if value.len() != BLOB_HASH_SIZE * 2 {
            return Err(BlobHashParseError::InvalidLength {
                expected: BLOB_HASH_SIZE * 2,
                actual: value.len(),
            });
        }

        let mut bytes = [0; BLOB_HASH_SIZE];
        for (index, pair) in value.as_bytes().chunks_exact(2).enumerate() {
            let high = hex_digit(pair[0]).ok_or(BlobHashParseError::InvalidCharacter {
                index: index * 2,
                character: pair[0] as char,
            })?;
            let low = hex_digit(pair[1]).ok_or(BlobHashParseError::InvalidCharacter {
                index: index * 2 + 1,
                character: pair[1] as char,
            })?;
            bytes[index] = (high << 4) | low;
        }
        Ok(Self::new(bytes))
    }

    /// Returns the canonical lower-case hexadecimal representation.
    #[must_use]
    pub fn to_hex(self) -> String {
        let mut value = String::with_capacity(BLOB_HASH_SIZE * 2);
        for byte in self.0 {
            value.push(hex_digit_to_char(byte >> 4));
            value.push(hex_digit_to_char(byte & 0x0f));
        }
        value
    }
}

impl Serialize for BlobHash {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_str(&self.to_hex())
    }
}

impl<'de> Deserialize<'de> for BlobHash {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::from_hex(&value).map_err(D::Error::custom)
    }
}

impl From<[u8; BLOB_HASH_SIZE]> for BlobHash {
    fn from(value: [u8; BLOB_HASH_SIZE]) -> Self {
        Self::new(value)
    }
}

impl FromStr for BlobHash {
    type Err = BlobHashParseError;

    fn from_str(value: &str) -> Result<Self, Self::Err> {
        Self::from_hex(value)
    }
}

impl fmt::Display for BlobHash {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str(&self.to_hex())
    }
}

/// A malformed serialized content hash.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BlobHashParseError {
    /// The digest does not contain exactly 64 hexadecimal characters.
    InvalidLength {
        /// Required character count.
        expected: usize,
        /// Supplied character count.
        actual: usize,
    },
    /// One character is not hexadecimal.
    InvalidCharacter {
        /// Zero-based character index.
        index: usize,
        /// Supplied invalid character.
        character: char,
    },
}

impl fmt::Display for BlobHashParseError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::InvalidLength { expected, actual } => write!(
                formatter,
                "blob hash must contain {expected} hexadecimal characters, received {actual}"
            ),
            Self::InvalidCharacter { index, character } => {
                write!(
                    formatter,
                    "blob hash character {character:?} at index {index} is invalid"
                )
            }
        }
    }
}

impl std::error::Error for BlobHashParseError {}

/// Stable content-addressed identity for one immutable blob.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct BlobId(BlobHash);

impl BlobId {
    /// Creates a content identity from its already computed hash.
    #[must_use]
    pub const fn new(hash: BlobHash) -> Self {
        Self(hash)
    }

    /// Returns the content hash that defines this identity.
    #[must_use]
    pub const fn hash(self) -> BlobHash {
        self.0
    }
}

impl From<BlobHash> for BlobId {
    fn from(value: BlobHash) -> Self {
        Self::new(value)
    }
}

impl fmt::Display for BlobId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

/// Immutable metadata recorded alongside a blob reference.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct BlobMetadata {
    /// BLAKE3 hash of the complete blob body.
    pub content_hash: BlobHash,
    /// Number of bytes in the complete blob body.
    pub size: u64,
    /// Optional media type supplied by the consumer/application.
    pub content_type: Option<String>,
}

impl BlobMetadata {
    /// Creates metadata for one content-addressed body.
    #[must_use]
    pub fn new(content_hash: BlobHash, size: u64, content_type: Option<String>) -> Self {
        Self {
            content_hash,
            size,
            content_type,
        }
    }

    /// Returns the content hash.
    #[must_use]
    pub const fn hash(&self) -> BlobHash {
        self.content_hash
    }
}

/// Stable reference stored in Event/Facet payloads instead of large bytes.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
pub struct BlobRef {
    /// Content-addressed identity of the referenced object.
    pub id: BlobId,
    /// Immutable metadata needed to verify an object read.
    pub metadata: BlobMetadata,
}

impl BlobRef {
    /// Creates a reference from its identity and immutable metadata.
    #[must_use]
    pub const fn new(id: BlobId, metadata: BlobMetadata) -> Self {
        Self { id, metadata }
    }

    /// Returns whether the identity and metadata carry the same content hash.
    #[must_use]
    pub fn is_consistent(&self) -> bool {
        self.id.hash().as_bytes() == self.metadata.content_hash.as_bytes()
    }

    /// Returns the referenced content identity.
    #[must_use]
    pub const fn id(&self) -> BlobId {
        self.id
    }

    /// Returns immutable verification metadata.
    #[must_use]
    pub const fn metadata(&self) -> &BlobMetadata {
        &self.metadata
    }
}

/// Blob bytes returned by a successful read.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BlobObject {
    /// The verified reference for the returned bytes.
    pub reference: BlobRef,
    /// Complete immutable object body.
    pub bytes: Vec<u8>,
}

impl BlobObject {
    /// Returns the verified reference.
    #[must_use]
    pub const fn reference(&self) -> &BlobRef {
        &self.reference
    }

    /// Returns the object bytes.
    #[must_use]
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    /// Consumes the result and returns the object bytes.
    #[must_use]
    pub fn into_bytes(self) -> Vec<u8> {
        self.bytes
    }
}

/// Typed failures at the immutable `BlobStore` read/write boundary.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum BlobError {
    /// The requested immutable identity is not available.
    NotFound { id: BlobId },
    /// The stored body does not match the reference hash.
    HashMismatch {
        /// Hash recorded in the immutable reference.
        expected: BlobHash,
        /// Hash calculated from the retrieved body.
        actual: BlobHash,
    },
    /// The stored body length does not match immutable metadata.
    SizeMismatch {
        /// Size recorded in the immutable reference.
        expected: u64,
        /// Size observed in the retrieved body.
        actual: u64,
    },
    /// A reference has inconsistent identity and metadata.
    InvalidReference { id: BlobId, metadata_hash: BlobHash },
    /// The same immutable identity was requested with different metadata.
    MetadataMismatch {
        /// Metadata already associated with the identity.
        expected: Option<String>,
        /// New metadata supplied by the caller.
        actual: Option<String>,
    },
    /// The adapter or remote object store could not complete the operation.
    Unavailable { id: BlobId, message: String },
}

impl fmt::Display for BlobError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::NotFound { id } => write!(formatter, "blob {id} was not found"),
            Self::HashMismatch { expected, actual } => write!(
                formatter,
                "blob hash mismatch: expected {expected}, calculated {actual}"
            ),
            Self::SizeMismatch { expected, actual } => {
                write!(
                    formatter,
                    "blob size mismatch: expected {expected}, received {actual}"
                )
            }
            Self::InvalidReference { id, metadata_hash } => write!(
                formatter,
                "blob reference {id} metadata hash {metadata_hash} does not match its identity"
            ),
            Self::MetadataMismatch { expected, actual } => write!(
                formatter,
                "blob metadata content type mismatch: expected {expected:?}, received {actual:?}"
            ),
            Self::Unavailable { id, message } => {
                write!(formatter, "blob {id} is unavailable: {message}")
            }
        }
    }
}

impl std::error::Error for BlobError {}

/// Consumer-owned port for immutable blob content.
///
/// `put` calculates the content-addressed identity and must never overwrite a
/// different body at an existing identity. `read` verifies size and hash
/// before returning bytes. Blob reads are deliberately separate from World
/// replay; a read failure must not mutate Events, Facets, State or forks.
pub trait BlobStore: Send + Sync {
    /// Stores complete bytes and returns their immutable reference.
    fn put<'a>(
        &'a self,
        bytes: &'a [u8],
        content_type: Option<&'a str>,
    ) -> PersistenceFuture<'a, Result<BlobRef, BlobError>>;

    /// Reads and integrity-checks one immutable reference.
    fn read<'a>(
        &'a self,
        reference: &'a BlobRef,
    ) -> PersistenceFuture<'a, Result<BlobObject, BlobError>>;

    /// Compatibility spelling for consumers that call the operation `get`.
    fn get<'a>(
        &'a self,
        reference: &'a BlobRef,
    ) -> PersistenceFuture<'a, Result<BlobObject, BlobError>> {
        self.read(reference)
    }
}

impl<T> BlobStore for Arc<T>
where
    T: BlobStore + ?Sized,
{
    fn put<'a>(
        &'a self,
        bytes: &'a [u8],
        content_type: Option<&'a str>,
    ) -> PersistenceFuture<'a, Result<BlobRef, BlobError>> {
        (**self).put(bytes, content_type)
    }

    fn read<'a>(
        &'a self,
        reference: &'a BlobRef,
    ) -> PersistenceFuture<'a, Result<BlobObject, BlobError>> {
        (**self).read(reference)
    }
}

fn hex_digit(value: u8) -> Option<u8> {
    match value {
        b'0'..=b'9' => Some(value - b'0'),
        b'a'..=b'f' => Some(value - b'a' + 10),
        b'A'..=b'F' => Some(value - b'A' + 10),
        _ => None,
    }
}

fn hex_digit_to_char(value: u8) -> char {
    match value {
        0..=9 => (b'0' + value) as char,
        10..=15 => (b'a' + value - 10) as char,
        _ => unreachable!("a hexadecimal digit is always below 16"),
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::*;

    #[test]
    fn hash_serialization_is_canonical_and_round_trips() {
        let hash = BlobHash::new([0xab; BLOB_HASH_SIZE]);
        assert_eq!(hash.to_string(), "ab".repeat(BLOB_HASH_SIZE));
        assert_eq!(BlobHash::from_hex(&hash.to_string()), Ok(hash));
        assert_eq!(serde_json::to_value(hash).unwrap(), json!(hash.to_string()));
        assert_eq!(
            serde_json::from_value::<BlobHash>(json!(hash.to_string())).unwrap(),
            hash
        );
    }

    #[test]
    fn blob_reference_rejects_no_reads_when_identity_metadata_disagree() {
        let reference = BlobRef::new(
            BlobId::new(BlobHash::new([1; BLOB_HASH_SIZE])),
            BlobMetadata::new(BlobHash::new([2; BLOB_HASH_SIZE]), 3, None),
        );
        assert!(!reference.is_consistent());
    }
}
