import csv
import json
import shutil
import tempfile
import unittest
from pathlib import Path

from motifvm.adversarial import run_adversarial
from motifvm.adapter_conformance import run_adapter_conformance
from motifvm.adapters import adapt_path, verify_adapter_result
from motifvm.audit import export_audit_pack
from motifvm.compiler import compile_reasoning_plan, create_motif_frame, load_pass_effects
from motifvm.compiler_eval import run_compiler_evaluation
from motifvm.verify_pack import verify_pack
from motifvm.graph import compare_states
from motifvm.llm import DeepSeekLLMClient
from motifvm.model import StatePatch
from motifvm.passes import registry
from motifvm.patch_auth import authorize_patch
from motifvm.runtime import (
    check_pass_preconditions,
    diagnose,
    emit_llm_narrative,
    initial_state,
    parse_request,
    run_task,
    select_passes,
    validate_llm_patch,
)
from motifvm.schema import validate_state_patch


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
            self.assertIn("motifFrame", state)
            self.assertIn("reasoningPlan", state)
            self.assertEqual(state["verificationPolicy"]["strength"], "strict")
            self.assertIn("extract_constraints", state["reasoningPlan"]["selectedPasses"])
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
            self.assertEqual(state["failureClass"], "reconciliation_required")
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
            self.assertEqual(state["replanEvents"][0]["failureClass"], "reconciliation_required")
            self.assertEqual(state["replanEvents"][0]["action"], "run_reconciliation")
            self.assertTrue(any(item["passName"] == "motif_compiler_replan" for item in state["patchTimeline"]))

            export_path = export_audit_pack(root, "001")
            ok, issues = verify_pack(export_path)
            self.assertTrue(ok, issues)
            self.assertTrue((export_path / "report.md").exists())
            self.assertTrue((export_path / "state.json").exists())
            self.assertTrue((export_path / "lineage.json").exists())
            self.assertTrue((export_path / "motif_frame.json").exists())
            self.assertTrue((export_path / "reasoning_plan.json").exists())
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
            self.assertEqual(state["failureClass"], "computation_blocked")
            self.assertEqual(state["replanEvents"][0]["action"], "request_more_evidence")
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
            self.assertEqual(auth["replanEvents"][0]["action"], "commit_security_failure")
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
            self.assertEqual([call["callType"] for call in state["llmCalls"]], ["CALL_PARSE", "CALL_DIAGNOSE", "CALL_EMIT"])
            export_path = export_audit_pack(root, "001")
            self.assertTrue((export_path / "llm_calls.json").exists())

    def test_mock_llm_emit_adds_bounded_narrative(self):
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

            self.assertEqual(state["status"], "committed_success")
            self.assertIn("CALL_EMIT", [call["callType"] for call in state["llmCalls"]])
            narrative = [artifact for artifact in state["artifacts"] if artifact["type"] == "llm_narrative"][0]
            self.assertFalse(narrative["content"]["mayAlterTerminalStatus"])
            self.assertTrue(any(item["passName"] == "CALL_EMIT" and item["role"] == "llm" for item in state["patchTimeline"]))

    def test_llm_patch_authorization_rejects_forbidden_emit(self):
        task = parse_request("Review this code diff for security risk", "code_review")
        state = initial_state(task, diagnose(task))
        patch = StatePatch(task_updates={"status": "committed_success"})

        errors = validate_llm_patch(state, patch)

        self.assertTrue(any("modify_task_ast" in error for error in errors))

    def test_repo_code_review_detects_helper_indirection_and_exports_timeline(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in ("examples", "config", "authority_sources", "static"):
                shutil.copytree(repo / dirname, root / dirname)

            state = run_task(
                "Review this repository diff for security risk",
                root=root,
                domain="code_review",
                input_files=["examples/code_review/repo_helper"],
            )

            self.assertEqual(state["status"], "committed_failed")
            self.assertEqual(state["failureClass"], "security_risk_detected")
            review = [artifact for artifact in state["artifacts"] if artifact["type"] == "code_review_result"][0]
            self.assertEqual(review["content"]["repoPath"], str(root / "examples" / "code_review" / "repo_helper"))
            self.assertIn("auth.py", review["content"]["changedFiles"])
            self.assertTrue(any(finding["id"] == "finding:code:auth_helper_bypass" for finding in review["content"]["findings"]))
            self.assertTrue(any(str(item["path"]).endswith("auth.py") for item in state["inputManifest"]))
            export_path = export_audit_pack(root, state["parentCommit"])
            self.assertTrue((export_path / "patch_timeline.json").exists())
            self.assertTrue((export_path / "patch_timeline.md").exists())
            ok, issues = verify_pack(export_path)
            self.assertTrue(ok, issues)

    def test_authority_refs_include_section_citations(self):
        task = parse_request("Verify CRAR using examples/crar_good.csv", "dccb_audit")
        state = initial_state(task, diagnose(task))

        authority = state["authorityRefs"][0]

        self.assertEqual(authority["sectionId"], "crar-formula")
        self.assertIn("quotedRuleExcerpt", authority)
        self.assertIn("sectionHash", authority)

    def test_csv_adapter_emits_evidence_refs_and_extracted_facts(self):
        repo = Path(__file__).resolve().parents[1]
        path = repo / "examples" / "crar_good.csv"

        result = adapt_path({"id": "input:1", "label": path.name, "location": str(path)}, path)

        self.assertIsNotNone(result)
        self.assertEqual(result.adapter_id, "adapter:csv:v0.5")
        self.assertEqual(verify_adapter_result(result), [])
        facts = [fact.to_dict() for fact in result.extracted_facts]
        self.assertTrue(any(fact["kind"] == "dccb_component" and fact["value"]["component"] == "tier1" for fact in facts))

    def test_adapter_conformance_runner_checks_builtin_adapters(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            shutil.copytree(repo / "examples", root / "examples")

            output = run_adapter_conformance(root)
            with (output / "results.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))

            self.assertEqual(len(rows), 3)
            self.assertTrue(all(row["schema_valid"] == "yes" for row in rows))

    def test_compiler_selects_different_plans_by_motif_risk(self):
        pass_effects = load_pass_effects(Path(__file__).resolve().parents[1])
        low_task = parse_request("Summarize this project note")
        low_state = initial_state(low_task, diagnose(low_task))
        low_frame = create_motif_frame(low_task, low_state["motifState"]["required"], low_state["motifState"]["supported"])
        low_plan = compile_reasoning_plan(low_task, low_frame, registry(), pass_effects)

        audit_task = parse_request("Verify CRAR using examples/crar_good.csv", "dccb_audit")
        audit_state = initial_state(audit_task, diagnose(audit_task))
        audit_frame = create_motif_frame(audit_task, audit_state["motifState"]["required"], audit_state["motifState"]["supported"])
        audit_plan = compile_reasoning_plan(audit_task, audit_frame, registry(), pass_effects)

        self.assertEqual(low_plan["verificationPolicy"]["strength"], "light")
        self.assertEqual(audit_plan["verificationPolicy"]["strength"], "strict")
        self.assertNotEqual(low_plan["selectedPasses"], audit_plan["selectedPasses"])
        self.assertNotIn("extract_constraints", low_plan["selectedPasses"])
        self.assertIn("extract_constraints", audit_plan["selectedPasses"])

    def test_pass_effect_registry_covers_runtime_passes(self):
        effects = load_pass_effects(Path(__file__).resolve().parents[1])
        missing = [item.name for item in registry() if item.name not in effects]
        self.assertEqual(missing, [])
        self.assertTrue(all("failureModes" in effects[item.name] for item in registry()))

    def test_compiler_evaluation_reports_required_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            output = run_compiler_evaluation(root)
            summary = json.loads((output / "summary.json").read_text(encoding="utf-8"))

            self.assertEqual(summary["planSelectionAccuracy"], "4/4")
            self.assertEqual(summary["verificationPolicyAccuracy"], "4/4")
            self.assertEqual(summary["missedRequiredPassRate"], "0/4")

    def test_schema_validation_rejects_bad_patch(self):
        errors = validate_state_patch({"nodesToAdd": "bad", "motifSupportDelta": {"nope": -1}})
        self.assertTrue(any("nodesToAdd" in error for error in errors))
        self.assertTrue(any("Unknown motif key" in error for error in errors))

    def test_patch_authorization_rejects_llm_source_mutation(self):
        patch = StatePatch(
            task_updates={"domain": "dccb_audit"},
            artifacts_to_add=[
                {
                    "id": "artifact:bad_recon",
                    "type": "reconciliation_patch",
                    "content": {"sourceMutated": True},
                }
            ],
        )

        errors = authorize_patch(patch, "llm", "dccb_audit")

        self.assertTrue(any("modify_task_ast" in error for error in errors))
        self.assertTrue(any("reconciliation patches" in error for error in errors))
        self.assertTrue(any("mutate source" in error for error in errors))

    def test_adversarial_suite_reports_expected_contracts(self):
        repo = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for dirname in ("adversarial", "config", "authority_sources"):
                shutil.copytree(repo / dirname, root / dirname)

            output = run_adversarial(root)
            with (output / "adversarial_results.csv").open(encoding="utf-8") as handle:
                rows = list(csv.DictReader(handle))
            taxonomy = json.loads((output / "failure_taxonomy.json").read_text(encoding="utf-8"))

            self.assertEqual(len(rows), 20)
            self.assertTrue(all(row["status_correct"] == "yes" for row in rows))
            self.assertTrue(all(row["failed_invariant_correct"] == "yes" for row in rows))
            self.assertTrue(all(row["failure_class_correct"] == "yes" for row in rows))
            self.assertEqual(taxonomy["security_risk_detected"], 8)

    def test_deepseek_requires_env_key(self):
        import os

        previous = os.environ.pop("DEEPSEEK_API_KEY", None)
        try:
            with self.assertRaises(ValueError):
                DeepSeekLLMClient()
        finally:
            if previous is not None:
                os.environ["DEEPSEEK_API_KEY"] = previous


if __name__ == "__main__":
    unittest.main()
