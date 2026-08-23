-- A child Event may causally reference an Event row owned by its visible
-- ancestor Timeline. Runtime validates that qualified visible prefix before
-- commit; the legacy same-Timeline foreign key cannot represent that contract.
ALTER TABLE loom_event_causal_link
    DROP CONSTRAINT IF EXISTS loom_event_causal_link_timeline_id_cause_event_id_fkey;
