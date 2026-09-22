"""Deterministic fixture tests for the Trellis Harness distribution."""

from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


MODULE_PATH = Path(__file__).with_name("harness.py")
SPEC = importlib.util.spec_from_file_location("harness_distribution", MODULE_PATH)
assert SPEC and SPEC.loader
harness = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(harness)


class HarnessDistributionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.release = MODULE_PATH.parent.parent

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def project(self, name: str, version: str = "0.6.12") -> Path:
        project = self.root / "projects" / name
        (project / ".trellis").mkdir(parents=True)
        (project / ".trellis" / ".version").write_text(version + "\n", encoding="utf-8")
        (project / ".trellis" / ".template-hashes.json").write_text(
            json.dumps({"__version": 2, "hashes": {".trellis/workflow.md": "a" * 64}}),
            encoding="utf-8",
        )
        return project

    def next_release(self) -> Path:
        target = self.root / "release-next"
        shutil.copytree(self.release, target)
        changed = target / "core" / "spec" / "agent-quality-gates.md"
        changed.write_text(changed.read_text(encoding="utf-8") + "\nFixture release 0.3.1.\n", encoding="utf-8")
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["harness_version"] = "0.3.1"
        for entry in manifest["managed_core_files"]:
            if entry["source"] == "core/spec/agent-quality-gates.md":
                entry["sha256"] = hashlib.sha256(changed.read_bytes()).hexdigest()
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    def previous_release(self) -> Path:
        target = self.root / "release-previous"
        shutil.copytree(self.release, target)
        manifest_path = target / "manifest.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["harness_version"] = "0.1.1"
        removed = {
            "core/skills/dev-grill/SKILL.md",
            "core/scripts/intake.py",
            "core/scripts/test_intake.py",
            "core/scripts/test_dev_grill_contract.py",
            "core/skills/dev-review/SKILL.md",
            "core/skills/dev-review/references/common.md",
            "core/skills/dev-review/references/vue2.md",
            "core/skills/dev-review/references/vue3.md",
            "core/skills/dev-review/references/react.md",
            "core/skills/dev-review/references/nextjs.md",
            "core/scripts/review_artifact.py",
            "core/scripts/test_review_artifact.py",
        }
        manifest["managed_core_files"] = [
            entry for entry in manifest["managed_core_files"] if entry["source"] not in removed
        ]
        shutil.rmtree(target / "core" / "skills" / "dev-review")
        shutil.rmtree(target / "core" / "skills" / "dev-grill")
        (target / "core" / "scripts" / "intake.py").unlink()
        (target / "core" / "scripts" / "test_intake.py").unlink()
        (target / "core" / "scripts" / "test_dev_grill_contract.py").unlink()
        (target / "core" / "scripts" / "review_artifact.py").unlink()
        (target / "core" / "scripts" / "test_review_artifact.py").unlink()
        for profile in manifest["profiles"]:
            profile_path = target / profile["source"]
            profile_data = json.loads(profile_path.read_text(encoding="utf-8"))
            profile_data.pop("review", None)
            profile_data.pop("grill", None)
            profile_path.write_text(json.dumps(profile_data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        return target

    def test_clean_and_repeated_install_are_idempotent(self) -> None:
        project = self.project("clean")
        first = harness.install(project, self.release, profile="nextjs")
        metadata = (project / ".trellis" / "harness" / "manifest.json").read_bytes()
        second = harness.install(project, self.release, profile="nextjs")
        self.assertEqual(first["harness_status"], "current")
        self.assertEqual(second["written_core_files"], [])
        self.assertEqual(metadata, (project / ".trellis" / "harness" / "manifest.json").read_bytes())

    # dev-review acceptance 16
    def test_new_install_gets_dev_review(self) -> None:
        project = self.project("review-install")
        harness.install(project, self.release, profile="vue2")
        self.assertTrue((project / ".agents" / "skills" / "dev-review" / "SKILL.md").is_file())
        self.assertTrue((project / ".trellis" / "scripts" / "harness" / "review_artifact.py").is_file())
        profile = json.loads((project / ".trellis" / "harness" / "quality-gates.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["review"]["profile"], "vue2")

    # dev-grill acceptance 1 and 4
    def test_new_install_gets_dev_grill_and_profile(self) -> None:
        project = self.project("grill-install")
        harness.install(project, self.release, profile="nextjs")
        self.assertTrue((project / ".agents" / "skills" / "dev-grill" / "SKILL.md").is_file())
        self.assertTrue((project / ".trellis" / "scripts" / "harness" / "intake.py").is_file())
        profile = json.loads((project / ".trellis" / "harness" / "quality-gates.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["grill"]["profile"], "nextjs")

    # dev-review acceptance 17
    def test_existing_project_sync_gets_dev_review(self) -> None:
        project = self.project("review-sync")
        old_release = self.previous_release()
        harness.install(project, old_release, profile="react")
        self.assertFalse((project / ".agents" / "skills" / "dev-review" / "SKILL.md").exists())
        self.assertEqual(harness.status(project, self.release)["harness_status"], "outdated")
        result = harness.sync(project, self.release)
        self.assertEqual(result["harness_status"], "current")
        self.assertTrue((project / ".agents" / "skills" / "dev-review" / "SKILL.md").is_file())

    # dev-grill acceptance 2 and 28
    def test_existing_project_sync_gets_dev_grill(self) -> None:
        project = self.project("grill-sync")
        old_release = self.previous_release()
        harness.install(project, old_release, profile="react")
        self.assertFalse((project / ".agents" / "skills" / "dev-grill" / "SKILL.md").exists())
        self.assertEqual(harness.status(project, self.release)["harness_status"], "outdated")
        result = harness.sync(project, self.release)
        self.assertEqual(result["harness_status"], "current")
        self.assertTrue((project / ".agents" / "skills" / "dev-grill" / "SKILL.md").is_file())

    def test_cli_install_and_status(self) -> None:
        project = self.project("cli")
        installed = subprocess.run(
            [sys.executable, str(MODULE_PATH), "install", "--project", str(project), "--profile", "vue2", "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(installed.returncode, 0, installed.stderr or installed.stdout)
        checked = subprocess.run(
            [sys.executable, str(MODULE_PATH), "status", "--project", str(project), "--json"],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(checked.returncode, 0, checked.stderr or checked.stdout)
        self.assertEqual(json.loads(checked.stdout)["harness_status"], "current")

    def test_sync_from_010_to_fixture_release(self) -> None:
        project = self.project("upgrade")
        harness.install(project, self.release)
        new_release = self.next_release()
        self.assertEqual(harness.status(project, new_release)["harness_status"], "outdated")
        result = harness.sync(project, new_release)
        self.assertEqual(result["harness_version"], "0.3.1")
        self.assertEqual(result["harness_status"], "current")

    def test_sync_preserves_profile_task_handoff_journal_runtime_and_official_hashes(self) -> None:
        project = self.project("preserve")
        task = project / ".trellis" / "tasks" / "task-a"
        task.mkdir(parents=True)
        (task / "handoff.md").write_text("handoff\n", encoding="utf-8")
        journal = project / ".trellis" / "workspace" / "developer.md"
        journal.parent.mkdir(parents=True)
        journal.write_text("journal\n", encoding="utf-8")
        runtime = project / ".trellis" / ".runtime" / "active.json"
        runtime.parent.mkdir(parents=True)
        runtime.write_text("runtime\n", encoding="utf-8")
        official = project / ".trellis" / ".template-hashes.json"
        harness.install(project, self.release, profile="vue3")
        profile = project / ".trellis" / "harness" / "quality-gates.json"
        profile.write_text(profile.read_text(encoding="utf-8") + "\n", encoding="utf-8")
        protected = {path: path.read_bytes() for path in (task / "handoff.md", journal, runtime, official, profile)}
        harness.sync(project, self.next_release())
        self.assertEqual(protected, {path: path.read_bytes() for path in protected})

    def test_local_core_change_conflicts(self) -> None:
        project = self.project("conflict")
        harness.install(project, self.release)
        core = project / ".agents" / "skills" / "dev-start" / "SKILL.md"
        unchanged = project / ".trellis" / "spec" / "agent-quality-gates.md"
        before = unchanged.read_bytes()
        core.write_text("local change\n", encoding="utf-8")
        with self.assertRaisesRegex(harness.HarnessError, "locally modified Core"):
            harness.sync(project, self.next_release())
        self.assertEqual(unchanged.read_bytes(), before)

    def test_deleted_installed_core_conflicts_and_force_restores_only_core(self) -> None:
        project = self.project("deleted-core")
        harness.install(project, self.release, profile="vue3")
        core = project / ".agents" / "skills" / "dev-start" / "SKILL.md"
        profile = project / ".trellis" / "harness" / "quality-gates.json"
        task = project / ".trellis" / "tasks" / "keep" / "handoff.md"
        task.parent.mkdir(parents=True)
        task.write_text("keep\n", encoding="utf-8")
        protected = {profile: profile.read_bytes(), task: task.read_bytes()}
        core.unlink()
        with self.assertRaisesRegex(harness.HarnessError, "locally modified Core"):
            harness.sync(project, self.release)
        self.assertFalse(core.exists())
        result = harness.sync(project, self.release, force=True)
        self.assertEqual(result["harness_status"], "current")
        self.assertTrue(core.is_file())
        self.assertEqual(protected, {path: path.read_bytes() for path in protected})

    def test_force_overwrites_core_only(self) -> None:
        project = self.project("force")
        harness.install(project, self.release, profile="react")
        core = project / ".agents" / "skills" / "dev-start" / "SKILL.md"
        core.write_text("local change\n", encoding="utf-8")
        profile = project / ".trellis" / "harness" / "quality-gates.json"
        task = project / ".trellis" / "tasks" / "keep" / "handoff.md"
        task.parent.mkdir(parents=True)
        task.write_text("keep\n", encoding="utf-8")
        protected = {profile: profile.read_bytes(), task: task.read_bytes()}
        result = harness.sync(project, self.next_release(), force=True)
        self.assertEqual(result["harness_status"], "current")
        self.assertNotEqual(core.read_text(encoding="utf-8"), "local change\n")
        self.assertEqual(protected, {path: path.read_bytes() for path in protected})

    def test_status_current_outdated_and_drift(self) -> None:
        project = self.project("status")
        harness.install(project, self.release)
        self.assertEqual(harness.status(project, self.release)["harness_status"], "current")
        self.assertEqual(harness.status(project, self.next_release())["harness_status"], "outdated")
        core = project / ".agents" / "skills" / "dev-verify" / "SKILL.md"
        core.write_text("drift\n", encoding="utf-8")
        self.assertEqual(harness.status(project, self.release)["harness_status"], "drift")

    def test_status_all_reports_multiple_projects(self) -> None:
        current = self.project("a-current")
        missing = self.project("b-missing")
        harness.install(current, self.release)
        rows = harness.status_all(self.root / "projects", self.release)
        self.assertEqual([row["harness_status"] for row in rows], ["current", "not-installed"])
        self.assertEqual({Path(row["project"]) for row in rows}, {current, missing})

    def test_trellis_compatibility_matrix_and_write_guard(self) -> None:
        supported = self.project("supported-015", "0.6.15")
        result = harness.install(supported, self.release)
        self.assertEqual(result["harness_status"], "current")
        self.assertEqual(harness.status(supported, self.release)["trellis_compatibility"]["status"], "supported")

        below_floor = self.project("below-floor", "0.6.11")
        with self.assertRaisesRegex(harness.HarnessError, "below minimum"):
            harness.install(below_floor, self.release)
        self.assertFalse((below_floor / ".trellis" / "harness" / "manifest.json").exists())
        self.assertEqual(
            harness.status(below_floor, self.release)["trellis_compatibility"]["status"],
            "incompatible",
        )

        unknown = self.project("unknown", "0.6.14")
        with self.assertRaisesRegex(harness.HarnessError, "tested project-version matrix"):
            harness.install(unknown, self.release)
        self.assertFalse((unknown / ".trellis" / "harness" / "manifest.json").exists())
        self.assertEqual(harness.status(unknown, self.release)["trellis_compatibility"]["status"], "unsupported")

    # dev-review acceptance 18
    def test_profiles_coexist_and_sync_never_replaces_them(self) -> None:
        snapshots = {}
        for profile_name in ("nextjs", "vue2", "vue3", "react"):
            project = self.project(profile_name)
            harness.install(project, self.release, profile=profile_name)
            profile = project / ".trellis" / "harness" / "quality-gates.json"
            snapshots[project] = profile.read_bytes()
        new_release = self.next_release()
        for project, expected in snapshots.items():
            harness.sync(project, new_release)
            self.assertEqual((project / ".trellis" / "harness" / "quality-gates.json").read_bytes(), expected)

    def test_profiles_are_valid_quality_gate_configs(self) -> None:
        scripts = self.release / "core" / "scripts"
        sys.path.insert(0, str(scripts))
        try:
            quality_spec = importlib.util.spec_from_file_location("distribution_quality_gate", scripts / "quality_gate.py")
            assert quality_spec and quality_spec.loader
            quality_gate = importlib.util.module_from_spec(quality_spec)
            quality_spec.loader.exec_module(quality_gate)
            for profile_name in ("nextjs", "vue2", "vue3", "react"):
                project = self.project(f"valid-{profile_name}")
                harness.install(project, self.release, profile=profile_name)
                config = quality_gate.load_config(project)
                self.assertTrue(config["fast"])
                self.assertTrue(config["full"])
                raw = json.loads((project / ".trellis" / "harness" / "quality-gates.json").read_text(encoding="utf-8"))
                self.assertEqual(raw["review"]["profile"], profile_name)
        finally:
            sys.path.remove(str(scripts))

    def test_sync_all_updates_installed_and_skips_uninstalled(self) -> None:
        installed = self.project("sync-installed")
        uninstalled = self.project("sync-uninstalled")
        harness.install(installed, self.release)
        results = harness.sync_all(self.root / "projects", self.next_release())
        by_project = {Path(item["project"]): item for item in results}
        self.assertEqual(by_project[installed]["harness_status"], "current")
        self.assertEqual(by_project[uninstalled]["action"], "skipped")

    def test_official_managed_target_is_rejected_without_hash_changes(self) -> None:
        project = self.project("official-conflict")
        official = project / ".trellis" / ".template-hashes.json"
        data = json.loads(official.read_text(encoding="utf-8"))
        data["hashes"][".agents/skills/dev-start/SKILL.md"] = "b" * 64
        official.write_text(json.dumps(data), encoding="utf-8")
        before = official.read_bytes()
        with self.assertRaisesRegex(harness.HarnessError, "overlap official Trellis"):
            harness.install(project, self.release)
        self.assertEqual(before, official.read_bytes())

    def test_core_target_alias_is_rejected(self) -> None:
        project = self.project("alias")
        target = project / ".agents" / "skills" / "dev-start"
        redirected = project / ".trellis" / "tasks" / "keep"
        redirected.mkdir(parents=True)
        target.parent.mkdir(parents=True)
        try:
            target.symlink_to(redirected, target_is_directory=True)
        except OSError:
            self.skipTest("symlink fixture unavailable on this host")
        with self.assertRaisesRegex(harness.HarnessError, "symlink or junction aliases"):
            harness.install(project, self.release, force=True)
        self.assertEqual(list(redirected.iterdir()), [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
