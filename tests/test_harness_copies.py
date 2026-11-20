from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TARGETS = ("agents/skills", ".claude/skills", "opencode/skills")
FILES = (
    "SKILL.md",
    "gauntlet_core.py",
    "contracts/contrato-editorial.json",
    "contracts/contrato-codigo.json",
)


def test_harness_copies_match_canonical():
    for target in TARGETS:
        for relative in FILES:
            canonical = (ROOT / relative).read_bytes()
            copy = (ROOT / target / "gauntlet-core" / relative).read_bytes()
            assert copy == canonical, f"{target}/gauntlet-core/{relative} divergiu do canonico"
