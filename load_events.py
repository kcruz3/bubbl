#!/usr/bin/env python3
"""
Robust loader for Venue + Single_Events with composite PK.

Assumes schema:

CREATE TABLE Venue (
    venue_address     VARCHAR(100) NOT NULL,
    venue_location VARCHAR(100) NOT NULL,
    PRIMARY KEY (venue_address, venue_location)
) ENGINE=InnoDB;

CREATE TABLE Single_Events (
    event_id          BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    event_name        VARCHAR(100) NOT NULL,
    event_description TEXT,
    venue_address        VARCHAR(100) NOT NULL,
    venue_location    VARCHAR(100) NOT NULL,
    link              TEXT,
    FOREIGN KEY (venue_address, venue_location)
        REFERENCES Venue(venue_address, venue_location)
        ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB;
"""

import argparse
import json
import re
import sys
from typing import Any, Dict, List, Optional

import mysql.connector
from mysql.connector import errorcode

# ---- Defaults ----
DEFAULT_JSON = "/var/www/html/cse30246/bubbl/all_events.json"
DEFAULT_HOST = "localhost"
DEFAULT_PORT = 3306
DEFAULT_USER = "mrocazap"
DEFAULT_PASS = "newpassword"
DEFAULT_DB   = "mrocazap"

# ---- Schema limits ----
LEN_venue_address      = 100
LEN_VENUE_LOCATION  = 100
LEN_EVENT_NAME      = 100
LEN_LINK_SOFT_LIMIT = 4096  # soft cap for TEXT


# ---------- Helpers ----------
_space_re = re.compile(r"\s+")

def normalize(s: Optional[str]) -> str:
    if s is None:
        return ""
    s = s.strip()
    s = _space_re.sub(" ", s)
    return s

def clip(s: str, n: int) -> str:
    return s[:n] if len(s) > n else s

def safe_get(dct: Dict[str, Any], *keys, default=None):
    cur = dct
    for k in keys:
        if not isinstance(cur, dict) or k not in cur:
            return default
        cur = cur[k]
    return cur

def extract_venue_address(item: Dict[str, Any]) -> str:
    vname = safe_get(item, "venue", "name")
    if isinstance(vname, str) and vname.strip():
        return normalize(vname)
    addr = item.get("address")
    if isinstance(addr, list) and addr:
        first = addr[0]
        if isinstance(first, str) and first.strip():
            return normalize(first.split(",")[0])
    return "Unknown Venue"

def extract_venue_location(item: Dict[str, Any]) -> str:
    addr = item.get("address")
    if isinstance(addr, list) and addr:
        last = addr[-1]
        if isinstance(last, str) and last.strip():
            return normalize(last)
        rest = [normalize(a) for a in addr[1:] if isinstance(a, str) and a.strip()]
        if rest:
            return normalize(", ".join(rest))
        first = addr[0]
        if isinstance(first, str) and first.strip():
            parts = [p.strip() for p in first.split(",")]
            if len(parts) >= 2:
                return normalize(", ".join(parts[1:]))
    return "Unknown"

def extract_event_name(item: Dict[str, Any]) -> str:
    title = item.get("title")
    if isinstance(title, str) and title.strip():
        return normalize(title)
    return "Untitled Event"

def extract_description(item: Dict[str, Any]) -> Optional[str]:
    desc = item.get("description")
    if isinstance(desc, str) and desc.strip():
        return desc.strip()
    return None

def extract_link(item: Dict[str, Any]) -> Optional[str]:
    link = item.get("link")
    if isinstance(link, str) and link.strip():
        ln = normalize(link)
        if len(ln) > LEN_LINK_SOFT_LIMIT:
            ln = ln[:LEN_LINK_SOFT_LIMIT]
        return ln
    return None

# ---------- DB Operations ----------
def upsert_venue(cur, venue_address: str, venue_location: str):
    sql = """
        INSERT INTO Venue (venue_address, venue_location)
        VALUES (%s, %s)
        ON DUPLICATE KEY UPDATE
            venue_address = VALUES(venue_address),
            venue_location = VALUES(venue_location)
    """
    cur.execute(sql, (venue_address, venue_location))


def insert_event(cur, event_name: str, event_desc: Optional[str],
                 venue_address: str, venue_location: str, link: Optional[str]):
    sql = """
        INSERT INTO Single_Events (event_name, event_description, venue_address, venue_location, link)
        VALUES (%s, %s, %s, %s, %s)
    """
    cur.execute(sql, (event_name, event_desc, venue_address, venue_location, link))


def process_events(cnx, events: List[Dict[str, Any]], batch_size: int = 500):
    cur = cnx.cursor()
    inserted_events = 0
    upserted_venues = 0
    skipped = 0

    try:
        for i, item in enumerate(events, 1):
            vname = extract_venue_address(item)
            vloc  = extract_venue_location(item)
            ename = extract_event_name(item)
            edesc = extract_description(item)
            link  = extract_link(item)

            # normalize + enforce lengths
            vname = clip(normalize(vname), LEN_venue_address)
            vloc  = clip(normalize(vloc), LEN_VENUE_LOCATION)
            ename = clip(normalize(ename), LEN_EVENT_NAME)

            if not vname or not vloc:
                skipped += 1
                continue

            # upsert venue
            upsert_venue(cur, vname, vloc)
            upserted_venues += 1

            # insert event
            try:
                insert_event(cur, ename, edesc, vname, vloc, link)
                inserted_events += 1
            except mysql.connector.Error as e:
                if e.errno in (errorcode.ER_NO_REFERENCED_ROW_2, errorcode.ER_ROW_IS_REFERENCED_2):
                    skipped += 1
                else:
                    raise

            if i % batch_size == 0:
                cnx.commit()

        cnx.commit()
    finally:
        cur.close()

    return upserted_venues, inserted_events, skipped


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--json", default=DEFAULT_JSON)
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--port", default=DEFAULT_PORT, type=int)
    ap.add_argument("--user", default=DEFAULT_USER)
    ap.add_argument("--password", default=DEFAULT_PASS)
    ap.add_argument("--db", default=DEFAULT_DB)
    ap.add_argument("--batch", default=500, type=int)
    args = ap.parse_args()

    try:
        with open(args.json, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        print("Failed to read JSON:", e, file=sys.stderr)
        sys.exit(1)

    if not isinstance(data, list):
        print("JSON root must be an array of events", file=sys.stderr)
        sys.exit(1)

    try:
        cnx = mysql.connector.connect(
            host=args.host, port=args.port,
            user=args.user, password=args.password,
            database=args.db,
            autocommit=False,
        )
    except mysql.connector.Error as e:
        print("DB connection failed:", e, file=sys.stderr)
        sys.exit(2)

    try:
        v, e, s = process_events(cnx, data, batch_size=args.batch)
        print(f"Done. Upserted venues: {v}, Inserted events: {e}, Skipped: {s}")
    except Exception as e:
        cnx.rollback()
        print("Error during load:", e, file=sys.stderr)
        sys.exit(3)
    finally:
        cnx.close()


if __name__ == "__main__":
    main()
