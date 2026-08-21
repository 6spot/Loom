from pathlib import Path

path = Path("tests/loom-composition/subresolution.rs")
text = path.read_text()
old = '''impl CommitStore for CountingStore {
    fn commit(
        &self,
        resolution: &ValidatedResolution,
        current_work: Option<&WorkClaim>,
        now: PlatformTime,
    ) -> Result<CommitResult, CommitError> {
        self.commits.fetch_add(1, Ordering::SeqCst);
        *self
            .provenance
            .lock()
            .expect("provenance mutex should not be poisoned") =
            Some(resolution.call_provenance().clone());
        self.inner.commit(resolution, current_work, now)
    }
}
'''
new = '''impl CommitStore for CountingStore {
    fn commit<'a>(
        &'a self,
        resolution: &'a ValidatedResolution,
        current_work: Option<&'a WorkClaim>,
        now: PlatformTime,
    ) -> PersistenceFuture<'a, Result<CommitResult, CommitError>> {
        self.commits.fetch_add(1, Ordering::SeqCst);
        *self
            .provenance
            .lock()
            .expect("provenance mutex should not be poisoned") =
            Some(resolution.call_provenance().clone());
        Box::pin(async move { self.inner.commit(resolution, current_work, now) })
    }
}
'''
if old not in text:
    raise SystemExit("CountingStore CommitStore block not found")
path.write_text(text.replace(old, new, 1))
