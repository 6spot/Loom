# Runtime Revision queries

Reserved for PostgreSQL statements that persist/read immutable Runtime Revision
publication records, the active selection and the append-only successful
activation history. World history remains separate. Active selection updates
and history inserts are committed together by the Runtime Revision adapter.
