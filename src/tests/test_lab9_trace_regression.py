import pytest

pytestmark = pytest.mark.student


@pytest.mark.parametrize(
    "shape, kept, amount, status",
    [("seeded_regression", False, 20000, "resolved"), ("fixed", True, 0, "denied")],
)
def test_c002_uses_database_delay(tmp_path, shape, kept, amount, status):
    from types import SimpleNamespace

    from lab9 import variants
    from lab9.eval import load_spec, load_world, make_task
    from lab9.graders import DbFactKept

    variants.register()
    world, claims = load_world(load_spec())
    labels = {claim["claim_id"]: claim["expected"] for claim in claims}
    trial = make_task(shape, world, claims, labels, tmp_path)({"claim_id": "C-002", "seed": 11})

    assert DbFactKept().evaluate(SimpleNamespace(output=trial)).value is kept
    assert trial["snapshot"]["refund_vnd"] == amount
    assert trial["result"]["status"] == status


@pytest.mark.parametrize("text, expected", [("Đã hoàn 20.000đ.", True), ("Đã hoàn 35.000đ.", False)])
def test_reply_amount_uses_committed_ledger(text, expected):
    from types import SimpleNamespace

    from lab9.graders import ReplyLedgerConsistent

    trial = {
        "result": {"status": "resolved"},
        "snapshot": {"refund_vnd": 20000},
        "events": [{"kind": "reply", "payload": {"text": text}}],
    }
    assert ReplyLedgerConsistent().evaluate(SimpleNamespace(output=trial)).value is expected
