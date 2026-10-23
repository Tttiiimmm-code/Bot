"""Forschungsrunden nach Protokoll (CLAUDE.md, research/PROTOCOL.md auf Branch research/ideas), aus dem Haupt-Repo:

  python tools/runde.py status   [--wt PFAD]
  python tools/runde.py neu      NNN "Titel" --vorab vorab.md --wt PFAD   Vorab-Eintrag + Skriptgerüst, commit, push
  python tools/runde.py rechnen  NNN [--wt PFAD]                          nur wenn der Vorab-Eintrag auf GitHub liegt
  python tools/runde.py abschluss NNN --ergebnis ergebnis.md [--urteil TEXT] [--aufraeumen] [--wt PFAD]
                                 Ergebnis ins Protokoll, commit, push, Vault-Notizen + Linkcheck, Worktree entfernen

Der Worktree liegt im Scratchpad der Sitzung (--wt beim ersten Aufruf; danach wird er über `git worktree list`
gefunden). Rundenskripte laufen im Haupt-Repo (data_cache) mit PYTHONPATH=<worktree>; ihre letzte Zeile
"URTEIL: ..." (research/scripts/rlib.py) liefert das Urteil. Commit-Zusatzzeile optional über RUNDE_COMMIT_TRAILER.
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from datetime import date
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
BRANCH = "research/ideas"
VAULT = Path(r"C:\Users\Nutzer\Trading-Bot-Vault")
PROTOCOL = Path("research") / "PROTOCOL.md"
SCRIPTS = Path("research") / "scripts"
CRITERION_RE = re.compile(r"bestanden,?\s+wenn", re.I)


class Fehler(RuntimeError):
    pass


def git(*args: str, cwd: Path | None = None, check: bool = True) -> str:
    p = subprocess.run(["git", *args], cwd=cwd or REPO, capture_output=True, text=True, encoding="utf-8")
    if check and p.returncode != 0:
        raise Fehler(f"git {' '.join(args)}: {p.stderr.strip() or p.stdout.strip()}")
    return p.stdout.strip()


# ------------------------------------------------------------------ reine Funktionen (getestet)

def round_numbers(protocol: str) -> list[int]:
    return sorted({int(m) for m in re.findall(r"^# Runden? (\d+)", protocol, re.M)})


def next_round(protocol: str) -> int:
    nums = round_numbers(protocol)
    return (max(nums) + 1) if nums else 1


def has_round(protocol: str, nr: str) -> bool:
    return re.search(rf"^# Runden? {re.escape(nr)}[:\s/]", protocol, re.M) is not None


def has_result(protocol: str, nr: str) -> bool:
    return re.search(rf"^## Ergebnis(?:se)? Runde {re.escape(nr)}\b", protocol, re.M) is not None


def round_title(protocol: str, nr: str) -> str:
    m = re.search(rf"^# Runde {re.escape(nr)}: (.+?)(?: \(Vorab, [\d-]+\))?$", protocol, re.M)
    return m.group(1) if m else ""


def check_vorab(text: str) -> None:
    """Vorab-Eintrag muss das Bestehenskriterium und einen Zeitraum nennen (Protokoll Regel 1)."""
    if not CRITERION_RE.search(text):
        raise Fehler('Vorab-Text ohne Bestehenskriterium ("BESTANDEN, wenn ...")')
    if not re.search(r"\b(19|20)\d\d\b", text):
        raise Fehler("Vorab-Text ohne Zeitraum (Jahreszahl)")


def vorab_block(nr: str, title: str, text: str, day: date) -> str:
    return f"\n# Runde {nr}: {title} (Vorab, {day.isoformat()})\n\n{text.strip()}\n"


def result_block(nr: str, urteil: str, text: str, day: date) -> str:
    return f"\n## Ergebnis Runde {nr} ({day.isoformat()}): {urteil}\n\n{text.strip()}\n"


def parse_verdict(output: str) -> str | None:
    found = re.findall(r"^URTEIL: (.+)$", output, re.M)
    return found[-1].strip() if found else None


def set_override(vault_gen_src: str, nr: str, urteil: str) -> str:
    """Trägt das Urteil in OVERRIDE von vault_gen.py ein (bestehender Eintrag wird ersetzt)."""
    entry = f'"{nr}": "{urteil.split(" (")[0].lower()}"'
    pat = rf'"{re.escape(nr)}": "[^"]*"'
    m = re.search(r"^OVERRIDE = \{.*?^\}", vault_gen_src, re.M | re.S)
    if not m:
        raise Fehler("OVERRIDE in vault_gen.py nicht gefunden")
    body = m.group(0)
    if re.search(pat, body):
        new = re.sub(pat, entry, body, count=1)
    else:
        inner = body[:-1].rstrip()
        if not inner.endswith(("{", ",")):
            inner += ","
        new = inner + f" {entry},\n}}"
    return vault_gen_src[:m.start()] + new + vault_gen_src[m.end():]


# ------------------------------------------------------------------ Worktree und Git

def find_worktree(explicit: str | None) -> Path | None:
    if explicit:
        return Path(explicit)
    path = None
    for line in git("worktree", "list", "--porcelain").splitlines():
        if line.startswith("worktree "):
            path = Path(line[len("worktree "):])
        elif line == f"branch refs/heads/{BRANCH}" and path is not None:
            return path
    return None


def ensure_worktree(explicit: str | None) -> Path:
    wt = find_worktree(explicit)
    if wt is None:
        raise Fehler("Kein Worktree für research/ideas -- beim ersten Aufruf --wt <scratchpad>/wt_ideas angeben")
    git("fetch", "-q", "origin", BRANCH)
    if not (wt / PROTOCOL).exists():
        git("worktree", "add", "-q", str(wt), BRANCH)
        print(f"Worktree angelegt: {wt}")
    git("pull", "-q", "--ff-only", "origin", BRANCH, cwd=wt)
    return wt


def need_worktree(explicit: str | None) -> Path:
    wt = find_worktree(explicit)
    if wt is None or not (wt / PROTOCOL).exists():
        raise Fehler("Kein Worktree für research/ideas gefunden (--wt angeben oder 'neu' zuerst)")
    return wt


def commit_push(wt: Path, files: list[Path], message: str) -> str:
    git("add", *[f.as_posix() for f in files], cwd=wt)
    trailer = os.environ.get("RUNDE_COMMIT_TRAILER", "").strip()
    git("commit", "-q", "-m", message + (f"\n\n{trailer}" if trailer else ""), cwd=wt)
    git("push", "-q", "origin", BRANCH, cwd=wt)
    return git("log", "--oneline", "-1", cwd=wt)


def pushed_protocol(wt: Path) -> str:
    git("fetch", "-q", "origin", BRANCH, cwd=wt)
    return git("show", f"origin/{BRANCH}:{PROTOCOL.as_posix()}", cwd=wt)


# ------------------------------------------------------------------ Befehle

def cmd_status(a) -> None:
    wt = find_worktree(a.wt)
    if wt is None or not (wt / PROTOCOL).exists():
        proto = git("show", f"origin/{BRANCH}:{PROTOCOL.as_posix()}")
        print("Worktree: keiner (für 'neu' --wt angeben)")
    else:
        proto = (wt / PROTOCOL).read_text(encoding="utf-8")
        dirty = git("status", "--porcelain", cwd=wt)
        print(f"Worktree: {wt}" + (f"\n  nicht committet:\n{dirty}" if dirty else ""))
    nums = round_numbers(proto)
    print(f"Runden im Protokoll: {len(nums)}, nächste freie Nummer: {next_round(proto)}")
    open_rounds = [n for n in nums[-10:] if not has_result(proto, str(n))]
    if open_rounds:
        print("Ohne Ergebnis (letzte 10): " + ", ".join(map(str, open_rounds)))


def cmd_neu(a) -> None:
    text = Path(a.vorab).read_text(encoding="utf-8")
    check_vorab(text)
    wt = ensure_worktree(a.wt)
    proto_path = wt / PROTOCOL
    proto = proto_path.read_text(encoding="utf-8")
    if has_round(proto, a.nr):
        raise Fehler(f"Runde {a.nr} steht schon im Protokoll")
    if a.nr.isdigit() and int(a.nr) != next_round(proto):
        print(f"Hinweis: nächste freie Nummer wäre {next_round(proto)}")
    if f"r{a.nr}.py" not in text:
        text = text.rstrip() + f"\nSkript research/scripts/r{a.nr}.py, Ausgabe r{a.nr}_output.txt.\n"
    with proto_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(vorab_block(a.nr, a.titel, text, date.today()))
    script = wt / SCRIPTS / f"r{a.nr}.py"
    files = [PROTOCOL]
    if not script.exists():
        tpl = (wt / SCRIPTS / "_vorlage.py").read_text(encoding="utf-8")
        script.write_text(tpl.replace("{NR}", a.nr).replace("{TITEL}", a.titel), encoding="utf-8", newline="\n")
        files.append(SCRIPTS / script.name)
    print("Vorab committet und gepusht: " + commit_push(wt, files, f"Runde {a.nr} vorab: {a.titel}"))
    print(f"Skript: {script}")


def cmd_rechnen(a) -> None:
    wt = need_worktree(a.wt)
    if not has_round(pushed_protocol(wt), a.nr):
        raise Fehler(f"Vorab-Eintrag Runde {a.nr} liegt nicht auf origin/{BRANCH} -- erst 'neu' (Protokoll Regel 1)")
    script = wt / SCRIPTS / f"r{a.nr}.py"
    out_path = wt / SCRIPTS / f"r{a.nr}_output.txt"
    if out_path.exists():
        print(f"Hinweis: {out_path.name} existiert schon -- ein erneuter Lauf gehört mit Grund ins Ergebnis")
    env = dict(os.environ, PYTHONPATH=str(wt), PYTHONIOENCODING="utf-8")
    p = subprocess.run([sys.executable, str(script)], cwd=REPO, env=env, capture_output=True, text=True,
                       encoding="utf-8")
    out_path.write_text(p.stdout, encoding="utf-8", newline="\n")
    print(p.stdout)
    if p.returncode != 0:
        print(p.stderr[-3000:], file=sys.stderr)
        raise Fehler(f"Skript endete mit Fehler {p.returncode} (Ausgabe bis dahin in {out_path.name})")
    print(f"Ausgabe: {out_path}\nUrteil laut Skript: {parse_verdict(p.stdout) or '(keine URTEIL-Zeile)'}")


def cmd_abschluss(a) -> None:
    wt = need_worktree(a.wt)
    proto_path = wt / PROTOCOL
    proto = proto_path.read_text(encoding="utf-8")
    if not has_round(pushed_protocol(wt), a.nr):
        raise Fehler(f"Vorab-Eintrag Runde {a.nr} fehlt auf origin/{BRANCH}")
    if has_result(proto, a.nr):
        raise Fehler(f"Ergebnis Runde {a.nr} steht schon im Protokoll")
    out_path = wt / SCRIPTS / f"r{a.nr}_output.txt"
    if not out_path.exists():
        raise Fehler(f"{out_path.name} fehlt -- erst 'rechnen'")
    urteil = a.urteil or parse_verdict(out_path.read_text(encoding="utf-8"))
    if not urteil:
        raise Fehler("Kein Urteil: Ausgabe ohne URTEIL-Zeile, bitte --urteil angeben")
    text = Path(a.ergebnis).read_text(encoding="utf-8")
    with proto_path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(result_block(a.nr, urteil, text, date.today()))
    title = round_title(proto, a.nr)
    files = [PROTOCOL, SCRIPTS / f"r{a.nr}.py", SCRIPTS / out_path.name]
    print("Ergebnis committet und gepusht: "
          + commit_push(wt, files, f"Runde {a.nr} Ergebnis: {title} {urteil.lower()}".strip()))
    gen = VAULT / "_werkzeug" / "vault_gen.py"
    if gen.exists():
        gen.write_text(set_override(gen.read_text(encoding="utf-8"), a.nr, urteil), encoding="utf-8", newline="\n")
        for cmd in ([sys.executable, "-I", str(gen), str(proto_path), str(VAULT)],
                    [sys.executable, "-I", str(VAULT / "_werkzeug" / "linkcheck.py"), str(VAULT)]):
            p = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                               env=dict(os.environ, PYTHONIOENCODING="utf-8"))
            print((p.stdout.strip().splitlines() or [""])[-1] + (f"\n{p.stderr[-1500:]}" if p.returncode else ""))
        print("Vault: Logbuch, Kontext (nächste Rundennummer) und ggf. Erkenntnisse noch von Hand ergänzen")
    if a.aufraeumen:
        if git("status", "--porcelain", cwd=wt):
            print("Worktree NICHT entfernt: nicht committete Änderungen")
        else:
            git("worktree", "remove", str(wt))
            print("Worktree entfernt")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Forschungsrunden nach Protokoll")
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("status", "neu", "rechnen", "abschluss"):
        sp = sub.add_parser(name)
        sp.add_argument("--wt", help="Worktree-Pfad (Scratchpad), sonst über git worktree list")
        if name != "status":
            sp.add_argument("nr", help="Rundennummer, z. B. 171 oder 171b")
    sub.choices["neu"].add_argument("titel")
    sub.choices["neu"].add_argument("--vorab", required=True,
                                    help="Datei mit dem Vorab-Text (Regeln, Zeitraum, Kosten, Kriterium)")
    sub.choices["abschluss"].add_argument("--ergebnis", required=True, help="Datei mit dem Ergebnistext")
    sub.choices["abschluss"].add_argument("--urteil", help="Urteil, falls die Ausgabe keine URTEIL-Zeile hat")
    sub.choices["abschluss"].add_argument("--aufraeumen", action="store_true", help="Worktree danach entfernen")
    a = ap.parse_args(argv)
    try:
        {"status": cmd_status, "neu": cmd_neu, "rechnen": cmd_rechnen, "abschluss": cmd_abschluss}[a.cmd](a)
    except Fehler as e:
        print(f"Fehler: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
