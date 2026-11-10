"""Accès SQLite : une connexion partagée, protégée par un verrou."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = """
CREATE TABLE IF NOT EXISTS discussions (
    id TEXT PRIMARY KEY,
    titre TEXT NOT NULL,
    titre_auto INTEGER NOT NULL DEFAULT 1,
    session_claude TEXT,
    modele TEXT NOT NULL,
    domaine TEXT,
    recette_contexte TEXT,
    cree_le TEXT NOT NULL,
    modifie_le TEXT NOT NULL,
    archivee INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    discussion_id TEXT NOT NULL REFERENCES discussions(id) ON DELETE CASCADE,
    role TEXT NOT NULL,
    contenu TEXT NOT NULL DEFAULT '',
    pieces TEXT NOT NULL DEFAULT '[]',
    outils TEXT NOT NULL DEFAULT '[]',
    cout REAL NOT NULL DEFAULT 0,
    etat TEXT NOT NULL DEFAULT 'termine',
    erreur TEXT,
    duree_ms INTEGER,
    cree_le TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS messages_discussion ON messages(discussion_id, id);
CREATE TABLE IF NOT EXISTS propositions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id) ON DELETE CASCADE,
    discussion_id TEXT NOT NULL REFERENCES discussions(id) ON DELETE CASCADE,
    cible TEXT NOT NULL,
    type TEXT NOT NULL,
    chemin TEXT NOT NULL,
    contenu TEXT NOT NULL,
    etat TEXT NOT NULL DEFAULT 'en_attente',
    commit_sha TEXT,
    sha_base TEXT,
    erreur TEXT,
    cree_le TEXT NOT NULL,
    traite_le TEXT
);
CREATE INDEX IF NOT EXISTS propositions_chemin ON propositions(chemin);
CREATE TABLE IF NOT EXISTS synchro (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    date TEXT NOT NULL,
    cible TEXT NOT NULL,
    fichiers TEXT NOT NULL DEFAULT '[]',
    resultat TEXT NOT NULL,
    erreur TEXT
);
CREATE TABLE IF NOT EXISTS sources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    type TEXT NOT NULL,
    titre TEXT NOT NULL,
    chemin TEXT,
    url TEXT,
    mode TEXT,
    etat TEXT NOT NULL DEFAULT 'en_attente',
    actif INTEGER NOT NULL DEFAULT 1,
    erreur TEXT,
    ajoutee_le TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS meta (cle TEXT PRIMARY KEY, valeur TEXT NOT NULL);
CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING fts5(
    contenu, tokenize = "unicode61 remove_diacritics 2"
);
CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(
    source_id UNINDEXED, titre, page UNINDEXED, texte, tokenize = "unicode61 remove_diacritics 2"
);
"""


def maintenant() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def requete_fts(texte: str) -> str:
    """Transforme une saisie libre en requête FTS5 sûre (préfixe sur chaque mot)."""
    mots = ["".join(c for c in mot if c.isalnum()) for mot in texte.split()]
    return " ".join(f'"{m}"*' for m in mots if m)


class Base:
    def __init__(self, chemin: Path | str):
        if chemin != ":memory:":
            Path(chemin).parent.mkdir(parents=True, exist_ok=True)
        self._verrou = threading.RLock()
        self._cx = sqlite3.connect(str(chemin), check_same_thread=False, isolation_level=None)
        self._cx.row_factory = sqlite3.Row
        self._cx.execute("PRAGMA journal_mode=WAL")
        self._cx.execute("PRAGMA foreign_keys=ON")
        self._cx.executescript(SCHEMA)

    def executer(self, sql: str, params: tuple | list = ()) -> sqlite3.Cursor:
        with self._verrou:
            return self._cx.execute(sql, params)

    def lignes(self, sql: str, params: tuple | list = ()) -> list[dict[str, Any]]:
        with self._verrou:
            return [dict(r) for r in self._cx.execute(sql, params).fetchall()]

    def ligne(self, sql: str, params: tuple | list = ()) -> dict[str, Any] | None:
        with self._verrou:
            r = self._cx.execute(sql, params).fetchone()
            return dict(r) if r else None

    def meta(self, cle: str, defaut: str | None = None) -> str | None:
        r = self.ligne("SELECT valeur FROM meta WHERE cle = ?", (cle,))
        return r["valeur"] if r else defaut

    def definir_meta(self, cle: str, valeur: str) -> None:
        self.executer(
            "INSERT INTO meta(cle, valeur) VALUES(?, ?) ON CONFLICT(cle) DO UPDATE SET valeur = excluded.valeur",
            (cle, valeur),
        )

    def fermer(self) -> None:
        with self._verrou:
            self._cx.close()


def decoder(ligne: dict[str, Any] | None, *champs: str) -> dict[str, Any] | None:
    """Décode les colonnes JSON d'une ligne."""
    if ligne is None:
        return None
    for champ in champs:
        if isinstance(ligne.get(champ), str):
            ligne[champ] = json.loads(ligne[champ])
    return ligne
