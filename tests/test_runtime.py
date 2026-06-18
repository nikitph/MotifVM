import csv
import json
import tempfile
import unittest
from pathlib import Path

from motifvm.audit import export_audit_pack
from motifvm.graph import compare_states
from motifvm.passes import registry
from motifvm.runtime import (
    check_pass_preconditions,
    diagnose,
    initial_state,
    parse_request,
    run_task,
    select_passes,
)


class RuntimeTests(unittest.TestCase):
    def test_planner_keeps_resolve_after_normalize(self):
        task = parse_request("Verify CRAR using examples/crar_components.csv", "dccb_audit")
        state = initial_state(task, diagnose(task))
        plan = [item.name for item in select_passes(registry(), state["motifState"]["required"], state["motifState"]["supported"])]
        self.assertLess(plan.index("normalize_intent"), plan.index("resolve_inputs"))
        self.assertLess(plan.index("resolve_inputs"), plan.index("build_evidence_graph"))

    def test_pass_preconditions_require_goal_before_resolve_inputs(self):
        task = parse_request("Verify CRAR using examples/crar_components.csv", "dccb_audit")
        state = initial_state(task, diagnose(task))
        resolve_inputs = [item for item in registry() if item.name == "resolve_inputs"][0]
        self.assertEqual(check_pass_preconditions(state, resolve_inputs), ["Missing required node type: goal"])

    def test_run_commits_crar_state(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            csv_path = examples / "crar_components.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["component", "amount"])
                writer.writerow(["tier1", "120"])
                writer.writerow(["tier2", "40"])
                writer.writerow(["rwa", "1000"])
                writer.writerow(["reported_crar", "16"])
                writer.writerow(["threshold", "9"])

            state = run_task(
                "Verify CRAR using examples/crar_components.csv",
                root=root,
                domain="dccb_audit",
            )

            self.assertEqual(state["status"], "committed_success")
            self.assertEqual(state["parentCommit"], "001")
            self.assertTrue((root / ".motifvm" / "state" / "current.json").exists())
            self.assertEqual(len(state["inputManifest"]), 1)
            self.assertEqual(len(state["inputManifest"][0]["sha256"]), 64)
            final = [
                artifact
                for artifact in state["artifacts"]
                if artifact["type"] == "final_output"
            ][0]
            self.assertIn("16.00%", final["content"]["text"])
            errors = [
                item
                for item in state["invariants"]
                if not item["passed"] and item["severity"] == "error"
            ]
            self.assertEqual(errors, [])
            crar_node = state["graph"]["nodes"]["output:crar"]
            self.assertEqual(
                crar_node["meta"]["lineage"]["evidenceNodeIds"],
                [
                    "evidence:csv:crar_components:tier1",
                    "evidence:csv:crar_components:tier2",
                    "evidence:csv:crar_components:rwa",
                ],
            )
            formula = [
                item
                for item in state["invariants"]
                if item["invariantId"] == "DCCB_001_FORMULA"
            ][0]
            self.assertEqual(formula["authorityRefs"], ["domain_profile:dccb:crar_formula"])
            evidence = state["graph"]["nodes"]["evidence:csv:crar_components:tier1"]
            self.assertEqual(evidence["meta"]["inputHash"], state["inputManifest"][0]["sha256"])

    def test_run_catches_reported_crar_mismatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            csv_path = examples / "crar_mismatch.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["component", "amount"])
                writer.writerow(["tier1", "120"])
                writer.writerow(["tier2", "40"])
                writer.writerow(["rwa", "1000"])
                writer.writerow(["reported_crar", "19"])
                writer.writerow(["threshold", "9"])

            state = run_task(
                "Verify CRAR using examples/crar_mismatch.csv",
                root=root,
                domain="dccb_audit",
            )

            self.assertEqual(state["status"], "committed_failed")
            self.assertEqual(state["terminalReason"], "DCCB_003_REPORTED_CRAR_MATCH")
            mismatch = [
                item
                for item in state["invariants"]
                if item["invariantId"] == "DCCB_003_REPORTED_CRAR_MATCH"
            ][0]
            self.assertFalse(mismatch["passed"])
            self.assertIn("reported = 19.00%", mismatch["message"])
            self.assertIn("computed = 16.00%", mismatch["message"])
            final = [
                artifact
                for artifact in state["artifacts"]
                if artifact["type"] == "final_output"
            ][0]
            self.assertIn("Reported CRAR mismatch", final["content"]["text"])
            self.assertIn("claim:dccb:reported_crar", state["graph"]["nodes"])
            self.assertIn(
                {
                    "from": "claim:dccb:reported_crar",
                    "to": "claim:dccb:computed_crar",
                    "relation": "contradicts",
                    "weight": 1.0,
                },
                state["graph"]["edges"],
            )
            self.assertIn("output:corrected_crar", state["graph"]["nodes"])
            self.assertTrue(
                any(artifact["type"] == "reconciliation_patch" for artifact in state["artifacts"])
            )
            recon_001 = [
                item for item in state["invariants"] if item["invariantId"] == "RECON_001"
            ][0]
            recon_002 = [
                item for item in state["invariants"] if item["invariantId"] == "RECON_002"
            ][0]
            self.assertTrue(recon_001["passed"])
            self.assertTrue(recon_002["passed"])

            export_path = export_audit_pack(root, "001")
            self.assertTrue((export_path / "report.md").exists())
            self.assertTrue((export_path / "state.json").exists())
            self.assertTrue((export_path / "lineage.json").exists())
            self.assertTrue((export_path / "inputs_manifest.json").exists())
            self.assertTrue((export_path / "reconciliation_patch.json").exists())
            manifest = json.loads((export_path / "inputs_manifest.json").read_text())
            self.assertEqual(len(manifest["inputs"][0]["sha256"]), 64)

    def test_run_commits_below_threshold_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            csv_path = examples / "crar_below_threshold.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["component", "amount"])
                writer.writerow(["tier1", "50"])
                writer.writerow(["tier2", "35"])
                writer.writerow(["rwa", "1000"])
                writer.writerow(["reported_crar", "8.5"])
                writer.writerow(["reported_status", "non-compliant"])
                writer.writerow(["threshold", "9"])

            state = run_task(
                "Verify CRAR using examples/crar_below_threshold.csv",
                root=root,
                domain="dccb_audit",
            )

            self.assertEqual(state["status"], "committed_failed")
            threshold = [
                item
                for item in state["invariants"]
                if item["invariantId"] == "DCCB_002_THRESHOLD"
            ][0]
            self.assertFalse(threshold["passed"])
            self.assertIn("below", threshold["message"])
            self.assertEqual(state["graph"]["nodes"]["output:compliance"]["content"], "non-compliant")

    def test_run_commits_blocked_missing_rwa(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            csv_path = examples / "crar_missing_rwa.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["component", "amount"])
                writer.writerow(["tier1", "120"])
                writer.writerow(["tier2", "40"])
                writer.writerow(["reported_crar", "16"])
                writer.writerow(["reported_status", "compliant"])
                writer.writerow(["threshold", "9"])

            state = run_task(
                "Verify CRAR using examples/crar_missing_rwa.csv",
                root=root,
                domain="dccb_audit",
            )

            self.assertEqual(state["status"], "committed_failed")
            components = [
                item
                for item in state["invariants"]
                if item["invariantId"] == "DCCB_004_CAPITAL_COMPONENTS_PRESENT"
            ][0]
            self.assertFalse(components["passed"])
            self.assertIn("rwa", components["message"])
            self.assertTrue(
                any(artifact["type"] == "dccb_crar_input_validation" for artifact in state["artifacts"])
            )

    def test_code_review_safe_and_unsafe_fixtures(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture_root = root / "examples" / "code_review"
            for name, patch_text in {
                "safe": """--- a/auth.py
+++ b/auth.py
@@ -1,2 +1,2 @@
 def is_admin(user):
-    return bool(user and user.role == "admin")
+    return bool(user and user.role in {"admin", "owner"})
""",
                "unsafe_auth_bypass": """--- a/auth.py
+++ b/auth.py
@@ -1,2 +1,2 @@
 def is_admin(user):
-    return bool(user and user.role == "admin")
+    return True
""",
                "secret_literal": """--- a/config.py
+++ b/config.py
@@ -1 +1,2 @@
 API_TIMEOUT = 30
+API_TOKEN = "sk_live_123456789"
""",
            }.items():
                path = fixture_root / name
                path.mkdir(parents=True)
                (path / "diff.patch").write_text(patch_text, encoding="utf-8")

            safe = run_task(
                "Review this code diff for security risk",
                root=root,
                domain="code_review",
                input_files=["examples/code_review/safe/diff.patch"],
            )
            auth = run_task(
                "Review this code diff for security risk",
                root=root,
                domain="code_review",
                input_files=["examples/code_review/unsafe_auth_bypass/diff.patch"],
            )
            secret = run_task(
                "Review this code diff for security risk",
                root=root,
                domain="code_review",
                input_files=["examples/code_review/secret_literal/diff.patch"],
            )

            self.assertEqual(safe["status"], "committed_success")
            self.assertEqual(auth["status"], "committed_failed")
            self.assertEqual(auth["terminalReason"], "CODE_003_NO_UNCONDITIONAL_AUTH_ALLOW")
            self.assertEqual(secret["status"], "committed_failed")
            self.assertEqual(secret["terminalReason"], "CODE_004_NO_SECRET_LITERAL")
            self.assertTrue(auth["inputManifest"][0]["sha256"])
            evidence = [
                node
                for node in auth["graph"]["nodes"].values()
                if node["type"] == "evidence" and node["id"].startswith("evidence:line:")
            ][0]
            self.assertEqual(evidence["meta"]["evidenceRef"]["locatorType"], "line")
            export_path = export_audit_pack(root, "002")
            self.assertTrue((export_path / "graph.json").exists())
            self.assertTrue((export_path / "graph.dot").exists())
            self.assertTrue((export_path / "graph.mmd").exists())
            diff = compare_states(safe, auth)
            self.assertEqual(diff["terminalStatus"], {"a": "committed_success", "b": "committed_failed"})

    def test_mock_llm_logs_structured_calls(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            examples = root / "examples"
            examples.mkdir()
            csv_path = examples / "crar_good.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as handle:
                writer = csv.writer(handle)
                writer.writerow(["component", "amount"])
                writer.writerow(["tier1", "120"])
                writer.writerow(["tier2", "40"])
                writer.writerow(["rwa", "1000"])
                writer.writerow(["reported_crar", "16"])
                writer.writerow(["threshold", "9"])

            state = run_task(
                "Verify CRAR using examples/crar_good.csv",
                root=root,
                domain="dccb_audit",
                llm_provider="mock",
            )
            self.assertEqual([call["callType"] for call in state["llmCalls"]], ["CALL_PARSE", "CALL_DIAGNOSE"])
            export_path = export_audit_pack(root, "001")
            self.assertTrue((export_path / "llm_calls.json").exists())


if __name__ == "__main__":
    unittest.main()
