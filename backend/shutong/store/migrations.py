"""Versioned schema scripts: ``MIGRATIONS[i]`` upgrades user_version i to i + 1."""

MIGRATIONS: tuple[str, ...] = (
    """
    CREATE TABLE libraries (
      id INTEGER PRIMARY KEY,
      name TEXT NOT NULL UNIQUE,
      kind TEXT NOT NULL CHECK (kind IN ('manga', 'novel')),
      source_dir TEXT NOT NULL,
      library_dir TEXT NOT NULL,
      naming_template TEXT NOT NULL DEFAULT '',
      source_policy TEXT NOT NULL DEFAULT 'keep'
        CHECK (source_policy IN ('keep', 'archive', 'delete')),
      archive_dir TEXT,
      created_at TEXT NOT NULL,
      CHECK ((source_policy = 'archive') = (archive_dir IS NOT NULL))
    );

    CREATE TABLE runs (
      id INTEGER PRIMARY KEY,
      library_id INTEGER NOT NULL REFERENCES libraries(id),
      trigger TEXT NOT NULL CHECK (trigger IN ('manual', 'drop', 'watch')),
      started_at TEXT NOT NULL,
      finished_at TEXT,
      counts TEXT NOT NULL DEFAULT '{}'
    );

    CREATE TABLE items (
      id INTEGER PRIMARY KEY,
      library_id INTEGER NOT NULL REFERENCES libraries(id),
      run_id INTEGER REFERENCES runs(id),
      source_path TEXT NOT NULL,
      fingerprint TEXT NOT NULL,
      status TEXT NOT NULL,
      review_reason TEXT,
      parsed TEXT NOT NULL DEFAULT '{}',
      subject_id INTEGER,
      plan TEXT NOT NULL DEFAULT '{}',
      target_path TEXT,
      error TEXT,
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL,
      UNIQUE (library_id, fingerprint)
    );

    CREATE TABLE item_events (
      id INTEGER PRIMARY KEY,
      item_id INTEGER NOT NULL REFERENCES items(id) ON DELETE CASCADE,
      at TEXT NOT NULL,
      kind TEXT NOT NULL,
      detail TEXT NOT NULL DEFAULT '{}'
    );
    CREATE INDEX item_events_item ON item_events(item_id, id);

    CREATE TABLE publish_journal (
      item_id INTEGER PRIMARY KEY REFERENCES items(id) ON DELETE CASCADE,
      staged_path TEXT NOT NULL,
      final_path TEXT NOT NULL,
      phase TEXT NOT NULL CHECK (phase IN ('building', 'staged', 'published')),
      sha256 TEXT,
      size INTEGER,
      updated_at TEXT NOT NULL
    );

    CREATE TABLE trash (
      id INTEGER PRIMARY KEY,
      item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
      original_path TEXT NOT NULL,
      trash_path TEXT NOT NULL,
      trashed_at TEXT NOT NULL,
      purge_after TEXT NOT NULL
    );

    CREATE TABLE settings (
      key TEXT PRIMARY KEY,
      value TEXT NOT NULL
    );
    """,
    """
    ALTER TABLE libraries ADD COLUMN pdf_to_cbz INTEGER NOT NULL DEFAULT 1;
    """,
    """
    CREATE TABLE rules (
      id INTEGER PRIMARY KEY,
      library_id INTEGER REFERENCES libraries(id) ON DELETE CASCADE,
      position INTEGER NOT NULL,
      text TEXT NOT NULL,
      enabled INTEGER NOT NULL DEFAULT 1,
      origin TEXT NOT NULL CHECK (origin IN ('manual', 'review', 'legacy', 'default')),
      created_at TEXT NOT NULL,
      updated_at TEXT NOT NULL
    );
    CREATE INDEX rules_scope ON rules(library_id, position);
    """,
    """
    CREATE TABLE metadata_cache (
      cache_key TEXT PRIMARY KEY,
      response_json TEXT NOT NULL,
      fetched_at TEXT NOT NULL,
      expires_at TEXT NOT NULL
    );

    CREATE TABLE ai_calls (
      id INTEGER PRIMARY KEY,
      item_id INTEGER REFERENCES items(id) ON DELETE SET NULL,
      purpose TEXT NOT NULL,
      model TEXT NOT NULL,
      request_json TEXT NOT NULL,
      response_text TEXT,
      error TEXT,
      duration_ms INTEGER NOT NULL,
      adopted INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL
    );
    CREATE INDEX ai_calls_created ON ai_calls(created_at);
    """,
    """
    ALTER TABLE items ADD COLUMN overrides TEXT NOT NULL DEFAULT '{}';
    """,
    """
    CREATE TABLE media_servers (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL CHECK (kind IN ('kavita')),
      name TEXT NOT NULL UNIQUE,
      base_url TEXT NOT NULL,
      username TEXT NOT NULL DEFAULT '',
      password TEXT NOT NULL DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    );
    ALTER TABLE libraries ADD COLUMN server_id INTEGER REFERENCES media_servers(id) ON DELETE SET NULL;
    ALTER TABLE libraries ADD COLUMN server_library_id INTEGER;
    """,
    """
    DELETE FROM settings WHERE key = 'ai.daily_limit';
    ALTER TABLE libraries ADD COLUMN include_edition INTEGER NOT NULL DEFAULT 1;
    ALTER TABLE items ADD COLUMN group_key TEXT;
    CREATE INDEX items_group ON items(library_id, group_key);
    """,
    """
    DROP TABLE rules;
    DROP TABLE trash;
    DELETE FROM settings WHERE key IN ('ai.enabled', 'ai.auto_adopt', 'organize.auto_execute',
                                       'trash.retention_days', 'desktop.system_trash');
    UPDATE settings SET value = '0.85' WHERE key = 'ai.threshold' AND value = '0.95';
    """,
    """
    ALTER TABLE libraries ADD COLUMN watch INTEGER NOT NULL DEFAULT 0;
    """,
    """
    ALTER TABLE libraries ADD COLUMN overwrite_policy TEXT NOT NULL DEFAULT 'never'
      CHECK (overwrite_policy IN ('never', 'always', 'larger', 'newer'));
    ALTER TABLE libraries ADD COLUMN rename_files INTEGER NOT NULL DEFAULT 1;
    """,
    """
    ALTER TABLE items ADD COLUMN source_root TEXT;
    ALTER TABLE items ADD COLUMN originals_kept INTEGER NOT NULL DEFAULT 0;
    """,
    # Komga: a second server kind, and its library ids are text such as "0S5E73NR0E2MP". Dropping the old
    # media_servers table clears libraries.server_id (ON DELETE SET NULL), so the links are kept aside first.
    """
    CREATE TABLE library_server_links AS
      SELECT id, server_id, CAST(server_library_id AS TEXT) AS server_library FROM libraries;
    CREATE TABLE media_servers_new (
      id INTEGER PRIMARY KEY,
      kind TEXT NOT NULL CHECK (kind IN ('kavita', 'komga')),
      name TEXT NOT NULL UNIQUE,
      base_url TEXT NOT NULL,
      username TEXT NOT NULL DEFAULT '',
      password TEXT NOT NULL DEFAULT '',
      enabled INTEGER NOT NULL DEFAULT 1,
      created_at TEXT NOT NULL
    );
    INSERT INTO media_servers_new(id, kind, name, base_url, username, password, enabled, created_at)
      SELECT id, kind, name, base_url, username, password, enabled, created_at FROM media_servers;
    DROP TABLE media_servers;
    ALTER TABLE media_servers_new RENAME TO media_servers;
    ALTER TABLE libraries DROP COLUMN server_library_id;
    ALTER TABLE libraries ADD COLUMN server_library_id TEXT;
    UPDATE libraries SET
      server_id = (SELECT server_id FROM library_server_links AS link WHERE link.id = libraries.id),
      server_library_id = (SELECT server_library FROM library_server_links AS link WHERE link.id = libraries.id);
    DROP TABLE library_server_links;
    """,
)
