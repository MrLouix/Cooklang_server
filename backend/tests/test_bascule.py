import sys

from app.config import Config
from app.db import Base
from app.depots import Depot
from scripts import bascule


def test_bascule_importe_le_drive_une_seule_fois(tmp_path, monkeypatch, capsys):
    drive = tmp_path / "drive"
    (drive / "Dessert").mkdir(parents=True)
    (drive / "Dessert" / "Flan.cook").write_text("---\ntitle: Flan\n---\nCuire le @lait{500%g}.\n")
    (drive / "Dessert" / "Flan.jpg").write_bytes(b"\xff\xd8")
    (drive / "Dessert" / "Cassé.cook").write_text("---\ntitle: Cassé\nservings: 2 parts\n---\nMélanger.\n")
    (drive / ".shopping-list").write_text("farine")
    monkeypatch.setenv("AC_RACINE", str(tmp_path / "srv"))
    monkeypatch.setenv("AC_RCLONE_DEST", str(drive))
    monkeypatch.setattr(sys, "argv", ["bascule"])

    assert bascule.principal() == 0
    sortie = capsys.readouterr().out
    assert "2 recette(s) importée(s)" in sortie and "Cassé.cook" in sortie and "1 anomalie" in sortie
    config = Config()
    depot = Depot(config.recettes)
    assert depot.fichiers() == [
        "Dessert/Cassé.cook",
        "Dessert/Flan.cook",
        "Dessert/Flan.jpg",
    ]  # images reprises, fichiers de l'appli laissés
    assert depot.historique()[0]["sujet"] == "Import initial depuis Google Drive"
    assert Base(config.base).meta("drive_synchro") == depot.tete()
    assert bascule.principal() == 2  # jamais deux fois
