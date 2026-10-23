import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import runde  # noqa: E402

PROTO = """# Forschungsprotokoll

# Runde 169: Put/Call (Vorab, 2026-10-20)

BESTANDEN, wenn 2016-2019 ...

## Ergebnis Runde 169 (2026-10-20): NICHT BESTANDEN

# Runde 170: Insiderbreite (Vorab, 2026-10-20)

text
"""


def test_round_numbers_and_flags():
    assert runde.next_round(PROTO) == 171
    assert runde.has_round(PROTO, "170") and not runde.has_round(PROTO, "17")
    assert runde.has_result(PROTO, "169") and not runde.has_result(PROTO, "170")
    assert runde.round_title(PROTO, "170") == "Insiderbreite"


def test_check_vorab_requires_criterion_and_period():
    runde.check_vorab("Regel ... BESTANDEN, wenn 2016-2025 p.a. > SPY")
    with pytest.raises(runde.Fehler, match="Bestehenskriterium"):
        runde.check_vorab("Regel ohne Kriterium 2016")
    with pytest.raises(runde.Fehler, match="Zeitraum"):
        runde.check_vorab("BESTANDEN, wenn besser")


def test_blocks_and_verdict():
    assert runde.vorab_block("171", "X", "a\n", date(2026, 10, 24)) == "\n# Runde 171: X (Vorab, 2026-10-24)\n\na\n"
    assert runde.result_block("171", "NICHT BESTANDEN", "b", date(2026, 10, 24)).startswith(
        "\n## Ergebnis Runde 171 (2026-10-24): NICHT BESTANDEN")
    assert runde.parse_verdict("x\nURTEIL: BESTANDEN (A)\n") == "BESTANDEN (A)"
    assert runde.parse_verdict("ohne") is None


def test_set_override_adds_and_replaces():
    src = 'A = 1\nOVERRIDE = {\n    "1": "x", "170": "nicht bestanden",\n}\n\nB = 2\n'
    out = runde.set_override(src, "171", "NICHT BESTANDEN")
    assert '"170": "nicht bestanden", "171": "nicht bestanden",\n}' in out and out.endswith("B = 2\n")
    out2 = runde.set_override(out, "171", "BESTANDEN (Regel A)")
    assert '"171": "bestanden"' in out2 and out2.count('"171"') == 1
    ns = {}
    exec(out2, ns)
    assert ns["OVERRIDE"]["171"] == "bestanden"


def _git(cwd, *args):
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True)


def test_full_round_flow(tmp_path, monkeypatch, capsys):
    """neu -> rechnen -> abschluss mit lokalem 'origin'; rechnen verweigert ohne gepushten Vorab-Eintrag."""
    origin, main = tmp_path / "origin.git", tmp_path / "main"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", "-b", "feature", str(main))
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(main, "config", k, v)
    _git(main, "remote", "add", "origin", str(origin))
    (main / "x.txt").write_text("x")
    _git(main, "add", "x.txt")
    _git(main, "commit", "-q", "-m", "init")
    _git(main, "checkout", "-q", "-b", "research/ideas")
    scripts = main / "research" / "scripts"
    scripts.mkdir(parents=True)
    (main / "research" / "PROTOCOL.md").write_text(PROTO, encoding="utf-8")
    (scripts / "_vorlage.py").write_text('print("Runde {NR}: {TITEL}")\nprint("URTEIL: NICHT BESTANDEN")\n',
                                         encoding="utf-8")
    _git(main, "add", ".")
    _git(main, "commit", "-q", "-m", "protokoll")
    _git(main, "push", "-q", "origin", "research/ideas")
    _git(main, "checkout", "-q", "feature")
    _git(main, "branch", "-q", "-D", "research/ideas")
    vault = tmp_path / "vault"
    (vault / "_werkzeug").mkdir(parents=True)
    (vault / "_werkzeug" / "vault_gen.py").write_text('OVERRIDE = {\n    "170": "nicht bestanden",\n}\n')
    (vault / "_werkzeug" / "linkcheck.py").write_text('print("Notizen: 1, kaputte Links: 0")\n')
    monkeypatch.setattr(runde, "REPO", main)
    monkeypatch.setattr(runde, "VAULT", vault)
    wt = tmp_path / "wt_ideas"
    _git(main, "fetch", "-q", "origin", "research/ideas:research/ideas")

    vorab = tmp_path / "vorab.md"
    vorab.write_text("Regel R. BESTANDEN, wenn 2016-2025 p.a. > SPY.", encoding="utf-8")
    assert runde.main(["rechnen", "171", "--wt", str(main)]) == 1           # kein Worktree mit Protokoll
    assert runde.main(["neu", "171", "Testidee", "--vorab", str(vorab), "--wt", str(wt)]) == 0
    pushed = subprocess.run(["git", "show", "origin/research/ideas:research/PROTOCOL.md"], cwd=wt,
                            capture_output=True, text=True, encoding="utf-8").stdout
    assert "# Runde 171: Testidee (Vorab," in pushed and "Skript research/scripts/r171.py" in pushed
    assert runde.main(["neu", "171", "doppelt", "--vorab", str(vorab)]) == 1    # Nummer vergeben

    assert runde.main(["rechnen", "171"]) == 0
    assert (wt / "research/scripts/r171_output.txt").read_text(encoding="utf-8").endswith("URTEIL: NICHT BESTANDEN\n")

    erg = tmp_path / "erg.md"
    erg.write_text("- Zahlen ...", encoding="utf-8")
    assert runde.main(["abschluss", "171", "--ergebnis", str(erg), "--aufraeumen"]) == 0
    proto = subprocess.run(["git", "show", "origin/research/ideas:research/PROTOCOL.md"], cwd=main,
                           capture_output=True, text=True, encoding="utf-8").stdout
    assert "## Ergebnis Runde 171 (" in proto and "): NICHT BESTANDEN" in proto
    assert '"171": "nicht bestanden"' in (vault / "_werkzeug" / "vault_gen.py").read_text()
    assert not wt.exists()
    assert "kaputte Links: 0" in capsys.readouterr().out


def test_rechnen_refuses_without_pushed_vorab(tmp_path, monkeypatch):
    origin, wt = tmp_path / "o.git", tmp_path / "wt"
    _git(tmp_path, "init", "-q", "--bare", str(origin))
    _git(tmp_path, "init", "-q", "-b", "research/ideas", str(wt))
    for k, v in (("user.email", "t@example.com"), ("user.name", "t")):
        _git(wt, "config", k, v)
    _git(wt, "remote", "add", "origin", str(origin))
    (wt / "research" / "scripts").mkdir(parents=True)
    (wt / "research" / "PROTOCOL.md").write_text(PROTO, encoding="utf-8")
    _git(wt, "add", ".")
    _git(wt, "commit", "-q", "-m", "p")
    _git(wt, "push", "-q", "origin", "research/ideas")
    with (wt / "research" / "PROTOCOL.md").open("a", encoding="utf-8") as f:   # nur lokal, nicht gepusht
        f.write("\n# Runde 171: heimlich (Vorab, 2026-10-24)\n\nBESTANDEN, wenn 2016 ...\n")
    (wt / "research" / "scripts" / "r171.py").write_text('print("URTEIL: BESTANDEN")\n')
    monkeypatch.setattr(runde, "REPO", wt)
    assert runde.main(["rechnen", "171", "--wt", str(wt)]) == 1
    assert not (wt / "research" / "scripts" / "r171_output.txt").exists()
