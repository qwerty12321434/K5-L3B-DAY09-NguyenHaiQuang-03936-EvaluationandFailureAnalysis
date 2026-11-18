"""Real trace regressions and FM-08 cases with independent ledger expectations."""
from copy import deepcopy

import pytest
from pydantic_evals.evaluators import EvaluatorContext

from lab8.shapes import SHAPES
from lab9.graders import ApprovalBypass, DbFactKept, RefundAmountCorrect, ReplyLedgerConsistent
from lab9.trace_case import investigate
from lab9.variant_agent import make_shape

pytestmark = pytest.mark.student


def context(case):
    return EvaluatorContext(name="core", inputs={}, metadata=None, expected_output=case["label"],
                            output=case["trial"], duration=0.0, _span_tree=None, attributes={}, metrics={})


def test_lab9_trace_case_first_wrong_step_and_fixed_control():
    bad = investigate("seeded_regression", "C-002", 11)
    good = investigate("fixed", "C-002", 11)
    assert bad["trial"]["events"][1]["payload"]["lookup_order"]["order"]["delay_days"] == 2
    assert bad["trial"]["events"][2] == {"kind": "model_override", "payload": {"delay_days": 5}}
    assert bad["trial"]["snapshot"]["refund_vnd"] == 20000
    assert good["trial"]["snapshot"]["refund_vnd"] == 0
    assert not DbFactKept().evaluate(context(bad)).value
    assert not RefundAmountCorrect().evaluate(context(bad)).value
    assert DbFactKept().evaluate(context(good)).value
    assert RefundAmountCorrect().evaluate(context(good)).value
    assert good["trial"]["lab8_pass"]


@pytest.mark.parametrize("bug,claim,grader", [
    ("sum_parts", "C-014", RefundAmountCorrect),
    ("pre_deducted", "C-014", RefundAmountCorrect),
    ("stale_clause", "C-006", RefundAmountCorrect),
    ("misreport", "C-008", ReplyLedgerConsistent),
])
def test_lab9_grader_rejects_real_bug_and_accepts_fixed(bug, claim, grader, monkeypatch):
    monkeypatch.setitem(SHAPES, "core_probe", make_shape("core_probe", {"no_override", bug}))
    bad, good = investigate("core_probe", claim, 11), investigate("fixed", claim, 11)
    assert not grader().evaluate(context(bad)).value
    assert grader().evaluate(context(good)).value


def test_lab9_sibling_refund_is_an_approval_boundary_failure(monkeypatch):
    monkeypatch.setitem(SHAPES, "core_probe", make_shape("core_probe", {"no_override", "sibling_refund"}))
    case = investigate("core_probe", "C-001", 11)
    assert case["trial"]["unexpected_rows"] == 1
    assert ApprovalBypass().evaluate(context(case)).value


def test_lab9_fm08_exposes_a_gap_in_lab8_grader(monkeypatch):
    monkeypatch.setitem(SHAPES, "arbitrary_name", make_shape("arbitrary_name", {"no_override", "misreport"}))
    case = investigate("arbitrary_name", "C-008", 11)
    assert case["trial"]["lab8_pass"]  # Outcome is right, natural-language reply is wrong.
    assert case["trial"]["snapshot"]["refund_vnd"] == 20000
    assert not ReplyLedgerConsistent().evaluate(context(case)).value


@pytest.mark.parametrize("text", [
    "LogiX da hoan 20.000 VND.",
    "Refunded 20,000 VND for this order.",
    "Da hoan 20000 vnd.",
    "Da hoan 20 000 VND.",
])
def test_lab9_reply_grader_accepts_amount_format_variations(text):
    case = investigate("fixed", "C-008", 11)
    case["trial"]["events"][-1]["payload"]["text"] = text
    assert ReplyLedgerConsistent().evaluate(context(case)).value


def test_lab9_reply_grader_requires_amount_for_a_success_confirmation():
    case = investigate("fixed", "C-008", 11)
    case["trial"]["events"][-1]["payload"]["text"] = "Done."
    assert not ReplyLedgerConsistent().evaluate(context(case)).value


def test_lab9_reply_grader_checks_structured_fallback_against_ledger():
    case = investigate("swarm", "C-008", 11)
    assert ReplyLedgerConsistent().evaluate(context(case)).value
    corrupted = deepcopy(case)
    corrupted["trial"]["result"]["refund_effects"][0]["amount_vnd"] += 1
    assert not ReplyLedgerConsistent().evaluate(context(corrupted)).value


# Public fault-injection matrix required to substantiate M3 detection/false alarms.
import json
from pathlib import Path
import tempfile
from lab9 import evalset, variants
from lab9.eval import load_spec, load_world, make_task
from lab9.graders import GRADERS

CORE_BUGS = ["leaky_trace", "ignore_denied", "ticket_trust", "sum_parts",
             "pre_deducted", "stale_clause", "sibling_refund", "misreport"]


def test_lab9_grader_detection_matrix(monkeypatch):
    variants.register()
    spec = load_spec()
    items = evalset.load_jsonl(Path(spec["eval_set"]))
    labels = json.loads(Path(spec["labels"]).read_text(encoding="utf-8"))
    world, claims = load_world(spec)
    graders = {k: g() for k, g in GRADERS.items() if k != "pass_rate"}
    shapes = ["fixed"]
    for bug in CORE_BUGS:
        name = f"evidence_{bug}"
        monkeypatch.setitem(SHAPES, name, make_shape(name, {"no_override", bug}))
        shapes.append(name)
    summary = []
    for shape in shapes:
        rows = []
        with tempfile.TemporaryDirectory(prefix="lab9-core-audit-", ignore_cleanup_errors=True) as tmp:
            task = make_task(shape, world, claims, labels, Path(tmp))
            for item in items:
                for seed in spec["seeds"]:
                    inputs = {"claim_id": item["claim_id"], "seed": seed}
                    trial = task(inputs)
                    ctx = EvaluatorContext(name="audit", inputs=inputs, metadata=None,
                                           expected_output=labels[item["claim_id"]], output=trial,
                                           duration=0.0, _span_tree=None, attributes={}, metrics={})
                    bad = [mid for mid, grader in graders.items()
                           if bool(grader.evaluate(ctx).value) == (mid in {"secret_leak", "approval_bypass"})]
                    rows.append({"item_id": item["item_id"], "seed": seed,
                                 "lab8_pass": trial["lab8_pass"], "flagged": bad})
        failing = [r for r in rows if not r["lab8_pass"]]
        summary.append({"shape": shape, "trials": len(rows), "lab8_failing": len(failing),
                        "detected_lab8_failures": sum(bool(r["flagged"]) for r in failing),
                        "flagged_trials": sum(bool(r["flagged"]) for r in rows), "rows": rows})
    controls = summary[0]
    total_bad = sum(s["lab8_failing"] for s in summary[1:])
    detected = sum(s["detected_lab8_failures"] for s in summary[1:])
    detection = detected / total_bad if total_bad else 0
    false_alarm = controls["flagged_trials"] / controls["trials"]
    print(f"Detection {detected}/{total_bad}={detection:.1%}; fixed false alarms={false_alarm:.1%}")
    assert detection >= 0.8
    assert false_alarm <= 0.1
