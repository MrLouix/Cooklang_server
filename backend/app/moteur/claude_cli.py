"""Moteur Claude Code CLI (M-2 à M-4) : `claude -p` en sous-processus, sortie stream-json."""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path

from ..config import OUTILS_AUTORISES, OUTILS_INTERDITS, Config
from .base import Demande, Evenement, classer_erreur


def resumer_outil(nom: str, entree: dict) -> str:
    for cle in ("query", "url", "file_path", "pattern", "skill", "path"):
        if entree.get(cle):
            return str(entree[cle])[:300]
    return ""


def interpreter(ligne: dict, etat: dict) -> list[Evenement]:
    """Traduit un objet stream-json en événements. `etat` porte le texte déjà émis."""
    genre = ligne.get("type")
    if genre == "system" and ligne.get("subtype") == "init":
        return [Evenement("session", session=ligne.get("session_id"))]
    if genre == "stream_event":
        ev = ligne.get("event", {})
        if ev.get("type") == "content_block_start" and ev.get("content_block", {}).get("type") == "text":
            if etat["texte"] and not etat["texte"].endswith("\n"):
                etat["texte"] += "\n\n"
                return [Evenement("texte", texte="\n\n")]
        if ev.get("type") == "content_block_delta" and ev.get("delta", {}).get("type") == "text_delta":
            morceau = ev["delta"].get("text", "")
            etat["texte"] += morceau
            return [Evenement("texte", texte=morceau)] if morceau else []
        return []
    if genre == "assistant":
        sortie = []
        for bloc in ligne.get("message", {}).get("content", []):
            if bloc.get("type") in ("tool_use", "server_tool_use"):
                sortie.append(
                    Evenement(
                        "outil",
                        nom=bloc.get("name", ""),
                        detail=resumer_outil(bloc.get("name", ""), bloc.get("input") or {}),
                    )
                )
        return sortie
    if genre == "rate_limit_event":
        if ligne.get("rate_limit_info", {}).get("status") == "rejected":
            etat["quota"] = True
        return []
    if genre == "result":
        etat["resultat"] = True
        if ligne.get("is_error"):
            message = "; ".join(ligne.get("errors") or []) or str(
                ligne.get("result") or ligne.get("subtype") or ""
            )
            code = "quota" if etat.get("quota") else classer_erreur(message)
            return [
                Evenement("erreur", code=code, texte=message, cout=float(ligne.get("total_cost_usd") or 0))
            ]
        sortie = []
        final = str(ligne.get("result") or "")
        if not etat["texte"] and final:
            etat["texte"] = final
            sortie.append(Evenement("texte", texte=final))
        sortie.append(
            Evenement("fin", session=ligne.get("session_id"), cout=float(ligne.get("total_cost_usd") or 0))
        )
        return sortie
    return []


class MoteurClaudeCLI:
    nom = "claude"

    def __init__(self, config: Config):
        self.config = config

    def arguments(self, demande: Demande) -> list[str]:
        args = [
            self.config.claude_bin, "-p",
            "--output-format", "stream-json", "--verbose", "--include-partial-messages",
            "--model", demande.modele,
        ]  # fmt: skip
        if demande.ephemere:
            args += ["--tools", "", "--no-session-persistence"]
        else:
            # Read, Glob et Grep restent bornés au répertoire de travail et à --add-dir :
            # ils ne figurent pas dans --allowedTools, donc toute lecture ailleurs est refusée.
            args += ["--tools", ",".join(OUTILS_AUTORISES)]
            args += ["--allowedTools", "Skill,WebSearch,WebFetch"]
            args += ["--disallowedTools", ",".join(OUTILS_INTERDITS)]
            args += ["--add-dir", str(self.config.recettes)]
            if demande.session:
                args += ["--resume", demande.session]
        if demande.consignes:
            args += ["--append-system-prompt", demande.consignes]
        return args

    def environnement(self) -> dict[str, str]:
        env = dict(os.environ)
        jeton = Path(self.config.jeton_fichier)
        if jeton.is_file():
            env["CLAUDE_CODE_OAUTH_TOKEN"] = jeton.read_text().strip()
        return env

    async def run(self, demande: Demande) -> AsyncIterator[Evenement]:
        self.config.agent.mkdir(parents=True, exist_ok=True)
        try:
            proc = await asyncio.create_subprocess_exec(
                *self.arguments(demande),
                cwd=self.config.agent,
                env=self.environnement(),
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                limit=16 * 1024 * 1024,
            )
        except FileNotFoundError:
            yield Evenement("erreur", code="moteur", texte=f"CLI introuvable : {self.config.claude_bin}")
            return
        etat = {"texte": "", "resultat": False}
        try:
            proc.stdin.write(demande.message.encode())
            proc.stdin.close()
            async for brut in proc.stdout:
                brut = brut.strip()
                if not brut:
                    continue
                try:
                    ligne = json.loads(brut)
                except json.JSONDecodeError:
                    continue
                for evenement in interpreter(ligne, etat):
                    yield evenement
            await proc.wait()
            if not etat["resultat"]:
                erreur = (await proc.stderr.read()).decode(errors="replace").strip()
                yield Evenement(
                    "erreur",
                    code=classer_erreur(erreur),
                    texte=erreur or f"Le CLI s'est arrêté (code {proc.returncode}).",
                )
        finally:
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()

    async def version(self) -> str:
        try:
            proc = await asyncio.create_subprocess_exec(
                self.config.claude_bin,
                "--version",
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
            sortie, _ = await asyncio.wait_for(proc.communicate(), 10)
            return sortie.decode().strip()
        except (OSError, TimeoutError):
            return "indisponible"
