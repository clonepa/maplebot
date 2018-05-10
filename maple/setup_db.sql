CREATE TABLE IF NOT EXISTS users (
  discord_id TEXT, name TEXT, elo_rating INTEGER, cash REAL,
  PRIMARY KEY(discord_id),
  UNIQUE(name COLLATE NOCASE)
);


CREATE TABLE IF NOT EXISTS match_history (
  winner TEXT, loser TEXT, winner_deckhash TEXT, loser_deckhash TEXT,
  FOREIGN KEY(winner) REFERENCES users(discord_id), FOREIGN KEY(loser) REFERENCES users(discord_id)
);


CREATE TABLE IF NOT EXISTS cards (
  multiverse_id INTEGER PRIMARY KEY, card_name TEXT, card_set TEXT,
  card_type TEXT, rarity TEXT, colors TEXT, cmc TEXT
);


CREATE TABLE IF NOT EXISTS collection (
  owner_id TEXT, multiverse_id INTEGER, amount_owned INTEGER, date_obtained TIMESTAMP,
  FOREIGN KEY(owner_id) REFERENCES users(discord_id),
  FOREIGN KEY(multiverse_id) REFERENCES cards(multiverse_id),
  PRIMARY KEY(owner_id, multiverse_id)
);


CREATE TABLE IF NOT EXISTS booster_inventory (
  owner_id TEXT, card_set TEXT, seed INTEGER,
  FOREIGN KEY(owner_id) REFERENCES users(discord_id),
  FOREIGN KEY(card_set) REFERENCES set_map(code)
);


CREATE TABLE IF NOT EXISTS set_map (
  name TEXT, code TEXT, alt_code TEXT,
  PRIMARY KEY (code, alt_code)
);


CREATE TABLE IF NOT EXISTS timestamped_base64_strings (
  name TEXT PRIMARY KEY, b64str TEXT, timestamp REAL
);


CREATE TRIGGER IF NOT EXISTS delete_from_collection_on_zero
  AFTER UPDATE OF amount_owned ON collection
  BEGIN
      DELETE FROM collection WHERE amount_owned < 1;
  END;


CREATE TRIGGER IF NOT EXISTS update_date_obtained
  AFTER UPDATE OF amount_owned ON collection
  WHEN new.amount_owned > old.amount_owned
  BEGIN
    UPDATE collection SET date_obtained = CURRENT_TIMESTAMP WHERE rowid = new.rowid;
  END;
