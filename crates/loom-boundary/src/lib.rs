//! External runtime boundaries.
//!
//! Ingress submits external input into Loom; feedback exposes committed World
//! changes without giving Core authority to perform real-world side effects.

#![forbid(unsafe_code)]
