from pathlib import Path

from gauntlet_core import load_contract

ROOT = Path(__file__).resolve().parent.parent


def test_examples_load():
    for name in ("contrato-editorial.json", "contrato-codigo.json"):
        contract = load_contract(ROOT / "contracts" / name)
        assert contract["criteria"]
        assert any(criterion["blocking"] for criterion in contract["criteria"])
