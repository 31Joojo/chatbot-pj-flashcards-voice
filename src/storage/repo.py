# src/storage/repo.py
### Modules importation
from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import List, Optional

from src.core.models import Flashcard, FlashcardCreate


### Function : _dt_to_str()
def _dt_to_str(dt: datetime) -> str:
    """
    Converts a datetime object to an ISO 8601 string.

    :param datetime dt: Date and time to convert
    :return str: ISO 8601 formatted date
    """
    return dt.isoformat(timespec="seconds")


### Function : _str_to_dt()
def _str_to_dt(s: str) -> datetime:
    """
    Converts an ISO 8601 string to a datetime object.

    :param str s: String representing a date and time in ISO 8601 format
    :return datetime: Datetime object corresponding to the string provided
    """
    return datetime.fromisoformat(s)


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

            # Add source_id column if missing
            try:
                conn.execute("ALTER TABLE flashcards ADD COLUMN source_id INTEGER;")
            except Exception:
                # Column already exists (or another harmless migration issue)
                pass

            conn.execute("CREATE INDEX IF NOT EXISTS idx_due_at ON flashcards(due_at);")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_flashcards_source_id ON flashcards(source_id);")
            conn.commit()

    ### Method : add_cards()
    def add_cards(self, cards: List[FlashcardCreate], source_id: int | None = None) -> List[int]:
        """
        Inserts a set of flashcards into the database.

        The cards are initialized with the default SM-2 parameters
        (ease factor = 2.5, zero interval).
        :param List[FlashcardCreate] cards: List of flashcards to insert
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
