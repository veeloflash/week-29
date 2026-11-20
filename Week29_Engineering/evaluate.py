"""Create reproducible submission evidence in isolated temporary databases."""
import copy
import io
import json
import tempfile
import unittest
from pathlib import Path

from core import Store, example_documents


ROOT = Path(__file__).resolve().parent


def pending(store, employee="A", expense="X"):
    flow = store.create(f"Can Employee {employee} approve Expense {expense} under the current policy?")
    return store.resume(flow["id"])


def write_evidence(output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as temp:
        store = Store(Path(temp) / "evaluation.sqlite")
        store.seed()
        flow = pending(store)
        store.review(flow["id"], "reviewer-1", "approve", "Checked HR role, current limit and expense.",
                     flow["revision"], flow["review_binding"])
        complete = store.resume(flow["id"])
        unknown = pending(store, "Unknown")
        store.resume(unknown["id"])
        missing = store.resume(unknown["id"])
        update = copy.deepcopy(example_documents()[-1])
        update["id"], update["version"] = "conflicting-policy", 1
        update["content"]["limits"]["manager"] = 7000
        store.ingest(update, "admin")
        conflict = pending(store)
        cases = {"happy_path": complete, "missing_employee": missing, "conflicting_policy": conflict}
        (output / "workflow_traces.json").write_text(json.dumps(cases, indent=2), encoding="utf-8")
        (output / "source_inventory.json").write_text(json.dumps(store.inventory(), indent=2), encoding="utf-8")
        lines = ["# Workflow trace evidence", ""]
        for name, trace in cases.items():
            lines += [f"## {name}", "", trace["question"], "", f"Final state is {trace['state']}.", ""]
            for event in trace["audit"]:
                if event["event"] in {"transition", "retrieval", "review"}:
                    lines.append(f"- {event['timestamp']} {event['actor']} "
                                 f"{event['previous_state']} → {event['next_state']} — {event['reason']}")
            lines.append("")
        (output / "trace_evidence.md").write_text("\n".join(lines), encoding="utf-8")
    stream = io.StringIO()
    suite = unittest.defaultTestLoader.discover(str(ROOT), pattern="test_workflow.py")
    result = unittest.TextTestRunner(stream=stream, verbosity=2).run(suite)
    (output / "test_results.txt").write_text(stream.getvalue(), encoding="utf-8")
    summary = {"tests": result.testsRun, "failures": len(result.failures), "errors": len(result.errors),
               "passed": result.wasSuccessful()}
    (output / "evaluation.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary))
    return result.wasSuccessful()


if __name__ == "__main__":
    raise SystemExit(0 if write_evidence(ROOT / "reports") else 1)
