-- Original unversioned outbox schema from implementation 58195b8.
CREATE TABLE targets (
  base TEXT NOT NULL, owner INTEGER NOT NULL, PRIMARY KEY(base,owner));
CREATE TABLE sessions (
  id INTEGER PRIMARY KEY AUTOINCREMENT, base TEXT NOT NULL, owner INTEGER NOT NULL,
  external TEXT NOT NULL, source TEXT NOT NULL, create_hash TEXT,
  next_sequence INTEGER NOT NULL DEFAULT 1, server_id INTEGER,
  state TEXT NOT NULL DEFAULT 'open', last_sequence INTEGER, close_hash TEXT,
  UNIQUE(base,owner,source,external), FOREIGN KEY(base,owner) REFERENCES targets(base,owner));
CREATE TABLE tasks (
  id INTEGER PRIMARY KEY AUTOINCREMENT, session INTEGER NOT NULL REFERENCES sessions(id),
  kind TEXT NOT NULL, stable_id TEXT NOT NULL, sequence INTEGER,
  payload TEXT, digest TEXT, state TEXT NOT NULL DEFAULT 'pending',
  attempts INTEGER NOT NULL DEFAULT 0, transient_count INTEGER NOT NULL DEFAULT 0,
  next_at REAL NOT NULL DEFAULT 0, last_error TEXT, receipt TEXT,
  UNIQUE(session,kind,stable_id));
