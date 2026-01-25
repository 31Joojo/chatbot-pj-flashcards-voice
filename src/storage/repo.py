# src/storage/repo.py
### Modules importation
from __future__ import annotations
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, List, Dict, Optional

from src.core.models import Flashcard, FlashcardCreate

### ------------------------------ Helpers ------------------------------ ###
### Helper : _dt_to_str()
def _dt_to_str(dt: datetime) -> str:
    """
    Converts a datetime object to an ISO 8601 string.

    :param datetime dt: Date and time to convert
    :return str: ISO 8601 formatted date
    """
    return dt.isoformat(timespec="seconds")


### Helper : _str_to_dt()
def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO-formatted datetime string into a naive UTC datetime.

    If the input string contains timezone information, it is converted
    to UTC and returned as a naive datetime to ensure consistency
    across the persistence layer.

    :param Optional[str] s: ISO-formatted datetime string
    :return Optional[datetime]: Parsed naive UTC datetime, or None
    """
    if not s:
        return None

    dt = datetime.fromisoformat(s)

    ### Force naive UTC datetime if timezone info is present
    if dt.tzinfo is not None:
        dt = dt.astimezone(timezone.utc).replace(tzinfo=None)

    return dt

### Helper : _new_iso()
def _now_iso() -> str:
    """
    Return the current UTC time as an ISO 8601 string.

    :return str: Current UTC datetime in ISO format
    """
    return datetime.now(timezone.utc).isoformat()

### Helper : _parse_dt()
def _parse_dt(s: Optional[str]) -> Optional[datetime]:
    """
    Parse an ISO 8601 datetime string into a datetime object.

    This helper also supports strings ending with 'Z' by converting
    them to a valid UTC offset representation.

    :param Optional[str] s: ISO-formatted datetime string
    :return Optional[datetime]: Parsed datetime object, or None
    """
    if not s:
        return None

    ### Normalize Zulu suffix to UTC offset
    return datetime.fromisoformat(s.replace("Z", "+00:00"))

### ------------------------------- Class ------------------------------- ###
### Class : FlashcardRepo
class FlashcardRepo:
    """
    Persistence storage for flashcards and their revision status.

    This class encapsulates access to an SQLite database
    used to store:
    - flashcard content (question, answer, hint, tags),
    - their spaced repetition status (SM-2),
    - temporal metadata (creation, next review, ...)

    It acts as a data access layer, separating the business
    logic (SM-2, generation, UI) from storage.

    :attribute Path db_path: Path to the SQLite file used for storage
    """
    def __init__(self, db_path: Path):
        """
        Initializes the repository and prepares the database.

        The parent directory is created if necessary, and the SQLite tables
        are initialized if they do not already exist.
        :param Path db_path: Path to the SQLite database file
        """
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._init_db()

    ### Method : _connect()
    def _connect(self) -> sqlite3.Connection:
        """
        Creates an SQLite connection configured for the project.

        :return sqlite3.Connection: SQLite connection with access to columns by name
        """
        conn = sqlite3.connect(self.db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        return conn

    ### Method : _init_db()
    def _init_db(self) -> None:
        """
        Initializes the database schema if necessary.

        Creates the `flashcards` table and associated indexes if
        they do not already exist.
        """
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS flashcards (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    hint TEXT,
                    tags TEXT,
                    source_text TEXT,
                    created_at TEXT NOT NULL,
                    ease_factor REAL NOT NULL,
                    interval_days INTEGER NOT NULL,
                    repetitions INTEGER NOT NULL,
                    due_at TEXT NOT NULL,
                    last_reviewed_at TEXT
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS sources (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT,
                    source_text TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )

            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS review_plans (
                    source_id INTEGER PRIMARY KEY,
                    next_review_at TEXT NOT NULL,
                    score REAL NOT NULL,
                    updated_at TEXT NOT NULL
                );
                """
            )

            ### Add source_id column if missing
            try:
                conn.execute("ALTER TABLE flashcards ADD COLUMN source_id INTEGER;")
            except Exception:
                ### Column already exists
                pass

            conn.execute("CREATE INDEX IF NOT EXISTS idx_due_at ON flashcards(due_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_source_id ON flashcards(source_id);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_review_plans_next_review_at ON review_plans(next_review_at);")
            conn.commit()

    ### Method : add_cards()
    def add_cards(self, cards: List[FlashcardCreate], source_id: Optional[int] = None) -> List[int]:
        """
        Inserts a set of flashcards into the database.

        The cards are initialized with the default SM-2 parameters
        (ease factor = 2.5, zero interval).

        :param List[FlashcardCreate] cards: List of flashcards to insert
        :param int source_id: Source id of the flashcards to insert
        :return List[int]: List of flashcards IDs
        """
        now = datetime.now()
        ids: List[int] = []

        with self._connect() as conn:
            for c in cards:
                tags_str = ",".join(c.tags or [])
                cur = conn.execute(
                    """
                    INSERT INTO flashcards
                        (question, answer, hint, tags, source_text, source_id, created_at,
                        ease_factor, interval_days, repetitions, due_at, last_reviewed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        c.question.strip(),
                        c.answer.strip(),
                        (c.hint or "").strip(),
                        tags_str,
                        (c.source_text or "").strip(),
                        source_id,
                        _dt_to_str(now),
                        2.5,
                        0,
                        0,
                        _dt_to_str(now),
                        None,
                    ),
                )
                ids.append(int(cur.lastrowid))
            conn.commit()

        return ids

    ### Method : add_source()
    def add_source(self, source_text: str, title: str | None = None) -> int:
        """
        Inserts a flashcards source into the database.
        :param str source_text:
        :param Optional[str] title:
        :return int:
        """
        now = datetime.now().isoformat()
        with self._connect() as conn:
            cur = conn.execute(
                "INSERT INTO sources(title, source_text, created_at) VALUES (?, ?, ?)",
                (title, source_text, now),
            )
            return int(cur.lastrowid)

    ### Method : list_sources()
    def list_sources(self, limit: int = 50):
        """
        List recently created source entries.

        This method returns a compact representation of sources,
        including a human-readable title fallback when no explicit
        title is stored in the database.

        :param int limit: Maximum number of sources to return
        :return list: List of source descriptors (id, title, created_at)
        """
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT id,
                       COALESCE(NULLIF(title, ''), '')       AS title,
                       COALESCE(NULLIF(source_text, ''), '') AS source_text,
                       created_at
                FROM sources
                ORDER BY id DESC LIMIT ?
                """,
                (int(limit),),
            ).fetchall()

        out = []
        for r in rows:
            title = (r["title"] or "").strip()
            if not title:
                ### Build a readable fallback title if none is stored
                preview = " ".join((r["source_text"] or "").split())
                title = (preview[:60] + "…") if len(preview) > 60 else (preview or f"Cours {r['id']}")
            out.append({
                "id": int(r["id"]),
                "title": title,
                "created_at": r["created_at"],
            })

        return out

    ### Method : list_questions_by_source()
    def list_questions_by_source(self, source_id: int, limit: int = 20) -> list[str]:
        """
        Retrieve recent questions associated with a given source.

        This method is used to avoid generating duplicate
        flashcards by inspecting already existing questions.

        :param int source_id: Identifier of the source/course
        :param int limit: Maximum number of questions to retrieve
        :return list[str]: List of question strings
        """
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row

            ### Fetch most recent questions for the given source
            rows = conn.execute(
                "SELECT question FROM flashcards WHERE source_id=? ORDER BY id DESC LIMIT ?",
                (int(source_id), int(limit)),
            ).fetchall()

        return [r["question"] for r in rows if r["question"]]

    ### Method : count_due()
    def count_due(self, source_id: Optional[int] = None, now_iso: Optional[str] = None) -> int:
        """
        Count the number of flashcards currently due for review.

        The count can be restricted to a specific source if a
        source identifier is provided.

        :param Optional[int] source_id: Source identifier to filter by
        :param Optional[str] now_iso: Reference datetime in ISO format
        :return int: Number of due flashcards
        """
        now_iso = now_iso or _now_iso()

        with self._connect() as conn:
            if source_id is None:
                row = conn.execute(
                    "SELECT COUNT(*) FROM flashcards WHERE due_at IS NOT NULL AND due_at <= ?",
                    (now_iso,),
                ).fetchone()
            else:
                row = conn.execute(
                    """
                    SELECT COUNT(*)
                    FROM flashcards
                    WHERE source_id = ?
                      AND due_at IS NOT NULL
                      AND due_at <= ?
                    """,
                    (int(source_id), now_iso),
                ).fetchone()

        ### Return only non-empty question texts
        return int(row[0] or 0)

    ### Method : get_by_id()
    def get_by_id(self, card_id: int) -> Optional[Flashcard]:
        """
        Retrieves a flashcard from its ID

        :param int card_id: ID of the flashcard
        :return Optional[Flashcard]: Flashcard corresponding to the ID if it exists
        """
        with self._connect() as conn:
            ### Retrieving the flashcard in the database
            row = conn.execute("SELECT * FROM flashcards WHERE id = ?", (int(card_id),)).fetchone()
        return self._row_to_card(row) if row else None

    ### Method : get_due()
    def get_due(self, limit: int = 20, source_id: int | None = None) -> List[Flashcard]:
        """
        Returns flashcards that are due for review.

        :param int limit: Number of flashcards to return
        :param int source_id: ID of the source text
        :return List[Flashcard]: List of flashcards IDs sorted by due date
        """
        now = _dt_to_str(datetime.now())

        sql = """
              SELECT * \
              FROM flashcards
              WHERE due_at <= ? \
              """
        params = [now]

        if source_id is not None:
            sql += " AND source_id = ?"
            params.append(int(source_id))

        sql += """
                ORDER BY due_at ASC
                LIMIT ?
            """
        params.append(int(limit))

        with self._connect() as conn:
            rows = conn.execute(sql, params).fetchall()

        return [self._row_to_card(r) for r in rows]

    ### Method : get_source_preview()
    def get_source_preview(self, source_id: int) -> str:
        """
        Return a short preview of a source text.

        The preview is extracted from the first flashcard
        associated with the given source.

        :param int source_id: Source identifier
        :return str: Short textual preview of the source
        """
        sql = """
                SELECT source_text FROM flashcards WHERE source_id=? LIMIT 1
              """

        with self._connect() as conn:
            row = conn.execute(sql,
                (source_id,),
            ).fetchone()

        if not row or not row[0]:
            return f"Source {source_id}"

        txt = row[0].strip().replace("\n", " ")
        return (txt[:80] + "…") if len(txt) > 80 else txt

    ### Method : get_next_due_at()
    def get_next_due_at(self, source_id: int) -> Optional[datetime]:
        """
        Retrieve the earliest upcoming due date for a source.

        :param int source_id: Source identifier
        :return Optional[datetime]: Next due datetime, or None
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT MIN(due_at) FROM flashcards WHERE source_id=? AND due_at IS NOT NULL",
                (int(source_id),),
            ).fetchone()

        return _parse_dt(row[0]) if row else None

    ### Method : get_review_plan()
    def get_review_plan(self, source_id: int) -> Optional[Dict[str, Any]]:
        """
        Retrieve the stored review plan for a given source.

        :param int source_id: Source identifier
        :return Optional[Dict[str, Any]]: Review plan data, or None
        """
        with self._connect() as conn:
            row = conn.execute(
                "SELECT source_id, next_review_at, score, updated_at FROM review_plans WHERE source_id=?",
                (int(source_id),),
            ).fetchone()

        if not row:
            return None

        return {
            "source_id": int(row[0]),
            "next_review_at": row[1],
            "score": float(row[2]),
            "updated_at": row[3],
        }

    ### Method : update_review()
    def update_review(
        self,
        card_id: int,
        ease_factor: float,
        interval_days: int,
        repetitions: int,
        due_at: datetime,
    ) -> None:
        """
        Updates the revision status of a flashcard after evaluation.

        This method is typically called after applying the SM-2 algorithm.

        :param int card_id: ID of the flashcard
        :param float ease_factor: New ease factor
        :param int interval_days: Number of days to wait until the next review
        :param int repetitions: Number of consecutive successful repetitions
        :param datetime due_at: Date and time of the next review
        """
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE flashcards
                SET ease_factor=?,
                    interval_days=?,
                    repetitions=?,
                    due_at=?,
                    last_reviewed_at=?
                WHERE id=?
                """,
                (
                    float(ease_factor),
                    int(interval_days),
                    int(repetitions),
                    _dt_to_str(due_at),
                    _dt_to_str(datetime.now()),
                    int(card_id),
                ),
            )
            conn.commit()

    ### Method : upsert_review_plan()
    def upsert_review_plan(self, source_id: int, next_review_at: datetime, score: float) -> None:
        """
        Insert or update a review plan for a source.

        If a review plan already exists for the source, it is
        updated atomically using an UPSERT operation.

        :param int source_id: Source identifier
        :param datetime next_review_at: Recommended next review datetime
        :param float score: Session performance score
        :return None: This method does not return anything
        """
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO review_plans (source_id, next_review_at, score, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(source_id) DO UPDATE SET
                  next_review_at=excluded.next_review_at,
                  score=excluded.score,
                  updated_at=excluded.updated_at
                """,
                (int(source_id), next_review_at.isoformat(), float(score), _now_iso()),
            )
            conn.commit()

    ### Method : upsert_review_plan()
    def update_source_title(self, source_id: int, title: str) -> None:
        """
        Update the title of a source entry.

        Empty or whitespace-only titles are ignored.

        :param int source_id: Source identifier
        :param str title: New title to set
        :return None: This method does not return anything
        """
        title = (title or "").strip()
        if not title:
            return
        with self._conn() as con:
            con.execute(
                "UPDATE sources SET title = ? WHERE id = ?",
                (title, int(source_id)),
            )
            con.commit()

    ### Method : _row_to_card()
    def _row_to_card(self, r: sqlite3.Row) -> Flashcard:
        """
        Converts a sqlite3.Row to a flashcard.

        :param sqlite3.Row r: Row to convert
        :return Flashcard: Flashcard corresponding to the row
        """
        tags = (r["tags"] or "").split(",") if r["tags"] else []
        last = _str_to_dt(r["last_reviewed_at"]) if r["last_reviewed_at"] else None

        return Flashcard(
            id=int(r["id"]),
            question=r["question"],
            answer=r["answer"],
            hint=r["hint"] or "",
            tags=[t for t in tags if t],
            source_text=r["source_text"] or "",
            created_at=_str_to_dt(r["created_at"]),
            ease_factor=float(r["ease_factor"]),
            interval_days=int(r["interval_days"]),
            repetitions=int(r["repetitions"]),
            due_at=_str_to_dt(r["due_at"]),
            last_reviewed_at=last,
        )
