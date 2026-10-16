import contextlib
import io
import importlib.util
import json
import sys
import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "lib"))

import sapper  # noqa: E402

SETTINGS_PATH = ROOT / "lib" / "_settings_patch.py"
_spec = importlib.util.spec_from_file_location("settings_patch_for_tests", SETTINGS_PATH)
settings_patch = importlib.util.module_from_spec(_spec)
assert _spec and _spec.loader
_spec.loader.exec_module(settings_patch)


class GraphIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = sapper.Store(Path(self.tmp.name) / ".sapper")
        self.store.init("test", "ship it")

    def tearDown(self):
        self.tmp.cleanup()

    def test_corrupt_node_is_skipped_and_reported_by_validate(self):
        (self.store.facts_dir / "f001.json").write_text('{"id":"f001"}\n', encoding="utf-8")
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr):
            rendered = sapper.render_graph_text(self.store)
        self.assertIn("goal: ship it", rendered)
        self.assertIn("missing string 'description'", stderr.getvalue())
        errors = sapper.validate_graph(self.store)
        self.assertTrue(any("f001.json" in error for error in errors))

    def test_init_refuses_non_empty_directory(self):
        root = Path(self.tmp.name) / "new-store"
        root.mkdir()
        (root / "unrelated.txt").write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(sapper.FGError, "non-empty directory"):
            sapper.Store(root).init("", "goal")
        self.assertTrue((root / "unrelated.txt").exists())

    def test_validate_detects_goal_metadata_drift(self):
        goal = self.store.facts_dir / "goal.json"
        data = json.loads(goal.read_text(encoding="utf-8"))
        data["description"] = "different goal"
        goal.write_text(json.dumps(data), encoding="utf-8")
        errors = sapper.validate_graph(self.store)
        self.assertIn("goal fact description does not match project goal", errors)

    def test_validate_detects_intent_state_mismatch(self):
        seed = self.store.add_fact("seed", "test", None)
        intent = self.store.add_intent([seed["id"]], "work", "test")
        path = self.store.intents_dir / f"{intent['id']}.json"
        data = json.loads(path.read_text(encoding="utf-8"))
        data["status"] = "done"
        path.write_text(json.dumps(data), encoding="utf-8")
        errors = sapper.validate_graph(self.store)
        self.assertTrue(any("completed status requires a target" in error for error in errors))

    def test_confirmation_is_enforced_at_write_boundary(self):
        fact = self.store.add_fact("starting point", "test", None)
        intent = self.store.add_intent(
            [fact["id"]], "delete data", "test", requires_confirmation=True
        )
        with self.assertRaisesRegex(sapper.FGError, "requires confirmation"):
            self.store.conclude_with_new_fact(intent["id"], "must not run", "test")
        self.store.confirm_intent(intent["id"])
        self.store.claim_intent(intent["id"], "owner")
        with self.assertRaisesRegex(sapper.FGError, "claimed by owner"):
            self.store.conclude_with_new_fact(intent["id"], "wrong worker", "other")
        result, concluded = self.store.conclude_with_new_fact(
            intent["id"], "approval was recorded", "owner"
        )
        self.assertEqual(concluded["to"], result["id"])

    def test_lookup_ids_cannot_escape_store(self):
        with self.assertRaisesRegex(sapper.FGError, "invalid fact id"):
            self.store.get_fact("../../outside")

    def test_stale_counter_never_overwrites_existing_node(self):
        first = self.store.add_fact("first", "test", None)
        project = self.store.load_project()
        project["counters"]["fact"] = 0
        self.store.save_project(project)
        second = self.store.add_fact("second", "test", None)
        self.assertEqual(first["id"], "f001")
        self.assertEqual(second["id"], "f002")
        self.assertEqual(self.store.get_fact("f001")["description"], "first")

    def test_fact_from_intent_closes_the_intent_atomically(self):
        seed = self.store.add_fact("seed", "test", None)
        intent = self.store.add_intent([seed["id"]], "observe", "test")
        fact = self.store.add_fact("observed", "test", intent["id"])
        self.assertEqual(self.store.get_intent(intent["id"])["to"], fact["id"])
        self.assertEqual(sapper.validate_graph(self.store), [])

    def test_linking_existing_fact_sets_its_source_edge(self):
        seed = self.store.add_fact("seed", "test", None)
        result = self.store.add_fact("already observed", "test", None)
        intent = self.store.add_intent([seed["id"]], "link result", "test")
        self.store.conclude_intent(intent["id"], result["id"], "test")
        self.assertEqual(self.store.get_fact(result["id"])["source_intent"], intent["id"])
        self.assertEqual(sapper.validate_graph(self.store), [])

    def test_pick_claim_skips_another_workers_lease(self):
        seed = self.store.add_fact("seed", "test", None)
        first = self.store.add_intent([seed["id"]], "first", "test")
        second = self.store.add_intent([seed["id"]], "second", "test")
        self.store.claim_intent(first["id"], "other-worker")
        args = type("Args", (), {
            "store": str(self.store.root), "claim": True,
            "worker": "my-worker", "any": False,
        })()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sapper.cmd_pick(args)
        self.assertEqual(output.getvalue().strip(), second["id"])

    def test_static_view_escapes_script_terminators(self):
        self.store.add_fact("</script><script>alert(1)</script>", "test", None)
        html = sapper._render_static_html(self.store)
        self.assertNotIn("</script><script>", html)
        self.assertIn(r"\u003c/script\u003e", html)

    def test_prompt_substitution_does_not_rewrite_inserted_braces(self):
        self.store.add_fact("literal {goal} marker", "test", None)
        prompt = sapper.render_prompt(self.store, "{graph_yaml}\nGOAL={goal}")
        self.assertIn("literal {goal} marker", prompt)
        self.assertTrue(prompt.endswith("GOAL=ship it"))

    def test_brainstorm_template_token_does_not_rewrite_graph_text(self):
        self.store.add_fact("literal {max_options} marker", "test", None)
        args = type("Args", (), {
            "max_options": 2, "dry_run": True,
        })()
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            sapper._dispatch_brainstorm(
                self.store, ROOT / "templates", "sonnet", 10, False, ROOT, args
            )
        self.assertIn("literal {max_options} marker", output.getvalue())

    def test_verify_payload_requires_actionable_issues_on_failure(self):
        with self.assertRaisesRegex(sapper.FGError, "explain"):
            sapper._parse_verify_payload({"verified": False, "issues": ""})
        with self.assertRaisesRegex(sapper.FGError, "leave 'issues' empty"):
            sapper._parse_verify_payload({"verified": True, "issues": "warning"})

    def test_dispatch_verify_returns_failure_status(self):
        seed = self.store.add_fact("seed", "test", None)
        intent = self.store.add_intent([seed["id"]], "check", "test")
        result, _ = self.store.conclude_with_new_fact(intent["id"], "result", "test")
        args = type("Args", (), {
            "intent": intent["id"], "dry_run": False,
        })()
        with mock.patch.object(
            sapper,
            "run_claude",
            return_value={"result": '{"accepted": true, "data": {"verified": false, "issues": "mismatch"}}'},
        ):
            rc = sapper._dispatch_verify(
                self.store, ROOT / "templates", "sonnet", 10, False, ROOT, args
            )
        self.assertEqual(rc, 1)

    def test_completed_graph_validates_and_duplicate_completion_is_rejected(self):
        fact = self.store.add_fact("evidence", "test", None)
        self.store.complete_project([fact["id"]], "finish", "test")
        self.assertEqual(self.store.load_project()["status"], "completed")
        self.assertEqual(sapper.validate_graph(self.store), [])
        with self.assertRaisesRegex(sapper.FGError, "already completed"):
            self.store.complete_project([fact["id"]], "finish again", "test")

    def test_brainstorm_batches_are_unique(self):
        seed = self.store.add_fact("seed", "test", None)
        payload = {
            "accepted": True,
            "data": {
                "options": [
                    {"from": [seed["id"]], "title": "one", "description": "first"}
                ]
            },
        }
        sapper._apply_brainstorm(self.store, payload)
        sapper._apply_brainstorm(self.store, payload)
        docs = [i["doc"] for i in self.store.list_intents()]
        self.assertEqual(len(docs), 2)
        tags = [line for doc in docs for line in doc.splitlines() if line.startswith("[brainstorm batch:")]
        self.assertEqual(len(set(tags)), 2)

    def test_brainstorm_pick_preserves_abandoned_edges(self):
        seed = self.store.add_fact("seed", "test", None)
        payload = {
            "accepted": True,
            "data": {"options": [
                {"from": [seed["id"]], "title": "one", "description": "first"},
                {"from": [seed["id"]], "title": "two", "description": "second"},
            ]},
        }
        sapper._apply_brainstorm(self.store, payload)
        picked = self.store.list_intents()[0]
        args = type("Args", (), {"store": str(self.store.root), "id": picked["id"], "purge": False})()
        sapper.cmd_brainstorm_pick(args)
        intents = self.store.list_intents()
        self.assertEqual(sum(i["to"] is None for i in intents), 1)
        self.assertEqual(sum(i["to"] is not None for i in intents), 1)
        self.assertEqual(sapper.validate_graph(self.store), [])


class SettingsPatchTests(unittest.TestCase):
    def test_settings_patch_is_atomic_and_preserves_unrelated_hooks(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                json.dumps({"hooks": {"SessionStart": [{"matcher": "x", "hooks": [
                    {"type": "command", "command": "echo keep"
                    }
                ]}]}}),
                encoding="utf-8",
            )
            changed, _ = settings_patch.add(path, "/tmp/sapper-hook.py")
            self.assertTrue(changed)
            data = json.loads(path.read_text(encoding="utf-8"))
            commands = [
                h["command"]
                for groups in data["hooks"].values()
                for group in groups
                for h in group.get("hooks", [])
            ]
            self.assertIn("echo keep", commands)
            self.assertEqual(sum("sapper-hook.py" in command for command in commands), 2)
            settings_patch.remove(path, "/tmp/sapper-hook.py")
            data = json.loads(path.read_text(encoding="utf-8"))
            self.assertEqual(data["hooks"]["SessionStart"][0]["hooks"][0]["command"], "echo keep")

    def test_settings_patch_rejects_non_object_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text("[]", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                settings_patch.add(path, "/tmp/sapper-hook.py")
            with self.assertRaisesRegex(ValueError, "JSON object"):
                settings_patch.remove(path, "/tmp/sapper-hook.py")

    def test_settings_validation_catches_malformed_event_shape(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(json.dumps({"hooks": {"SessionStart": {}}}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hooks.SessionStart"):
                settings_patch.validate(path)


class PeerConfigTests(unittest.TestCase):
    def test_malformed_peer_config_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = sapper.Store(Path(tmp) / ".sapper")
            store.init("", "peers")
            (store.root / sapper.PEERS_FILE).write_text(
                json.dumps({"version": 1, "channel": "x", "peers": {"bad name": {"target": "x"}}}),
                encoding="utf-8",
            )
            with self.assertRaisesRegex(sapper.FGError, "invalid peer name"):
                sapper._load_peers(store)

    def test_setup_preflights_invalid_settings_before_creating_graph(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp)
            (project / ".claude").mkdir()
            (project / ".claude" / "settings.json").write_text("[]", encoding="utf-8")
            old_cwd = Path.cwd()
            try:
                import os
                os.chdir(project)
                args = type("Args", (), {
                    "store": ".sapper", "goal": "should not initialize",
                    "origin": "", "agents": False, "force": False,
                })()
                with self.assertRaisesRegex(sapper.FGError, "JSON object"):
                    sapper.cmd_setup(args)
            finally:
                os.chdir(old_cwd)
            self.assertFalse((project / ".sapper" / "project.json").exists())


if __name__ == "__main__":
    unittest.main()


class TypedFactTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = sapper.Store(Path(self.tmp.name) / ".sapper")
        self.store.init("test", "capture the flag")

    def tearDown(self):
        self.tmp.cleanup()

    def test_typed_fact_roundtrip_and_render(self):
        fact = self.store.add_fact(
            "nginx 1.18 at 10.0.2.15:80", "user",
            kind="service", data={"host": "10.0.2.15", "port": 80},
        )
        self.assertEqual(fact["kind"], "service")
        self.assertEqual(fact["data"]["port"], "80")
        text = sapper.render_graph_text(self.store)
        self.assertIn("<service>", text)
        self.assertIn("port=80", text)
        yaml = sapper._to_yaml_like(sapper.build_graph_view(self.store))
        self.assertIn("<service>", yaml)
        # prompt rendering scrubs braces so flag{...} cannot eat placeholders
        self.assertIn("port=80", yaml)

    def test_unknown_kind_and_bad_data_rejected(self):
        with self.assertRaises(sapper.FGError):
            self.store.add_fact("x", "user", kind="exploit")
        with self.assertRaises(sapper.FGError):
            self.store.add_fact("x", "user", kind="cred", data={"bad key!": "1"})

    def test_validate_rejects_invalid_kind_on_disk(self):
        fact = self.store.add_fact("x", "user", kind="cred")
        p = self.store.facts_dir / f"{fact['id']}.json"
        node = json.loads(p.read_text(encoding="utf-8"))
        node["kind"] = "exploit"
        p.write_text(json.dumps(node), encoding="utf-8")
        errors = sapper.validate_graph(self.store)
        self.assertTrue(any("kind" in e for e in errors))

    def test_explore_payload_carries_kind_and_data(self):
        payload = {"accepted": True, "data": {
            "description": "RCE confirmed",
            "kind": "vuln",
            "data": {"cve": "CVE-2021-41773"},
        }}
        title, desc, doc, kind, data = sapper._parse_explore_payload(payload)
        self.assertEqual(kind, "vuln")
        self.assertEqual(data, {"cve": "CVE-2021-41773"})


class FlagLedgerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.store = sapper.Store(Path(self.tmp.name) / ".sapper")
        self.store.init("test", "capture the flag")

    def tearDown(self):
        self.tmp.cleanup()

    def test_flag_record_and_dedupe(self):
        fact = self.store.add_fact(
            "flag captured: flag{a}", "agent",
            kind="flag", data={"value": "flag{a}", "challenge": "c01", "status": "recorded"},
        )
        dup = sapper._find_flag_fact(self.store, "flag{a}")
        self.assertEqual(dup["id"], fact["id"])
        self.assertIsNone(sapper._find_flag_fact(self.store, "flag{b}"))

    def test_flag_status_lifecycle_and_type_guard(self):
        fact = self.store.add_fact(
            "flag captured: flag{a}", "agent",
            kind="flag", data={"value": "flag{a}", "status": "recorded"},
        )
        updated = self.store.update_flag_fact(fact["id"], "submitted", '{"ok":true}')
        self.assertEqual(updated["data"]["status"], "submitted")
        self.assertEqual(updated["data"]["result"], '{"ok":true}')
        plain = self.store.add_fact("just text", "agent")
        with self.assertRaises(sapper.FGError):
            self.store.update_flag_fact(plain["id"], "submitted", None)
        with self.assertRaises(sapper.FGError):
            self.store.update_flag_fact(fact["id"], "hacked-status", None)

    def test_status_shows_flag_ledger(self):
        self.store.add_fact(
            "flag captured: flag{z}", "agent",
            kind="flag", data={"value": "flag{z}", "challenge": "c09", "status": "submitted"},
        )
        text = sapper.render_status(self.store)
        self.assertIn("flag(s)", text)
        self.assertIn("status=submitted", text)
        self.assertIn("challenge=c09", text)


class DeadlineTests(unittest.TestCase):
    def test_minutes_and_iso_and_conflict(self):
        import time as _t
        a = type("A", (), {"deadline": None, "minutes": 5})()
        d = sapper.deadline_from_args(a)
        self.assertGreater(d, _t.time())
        b = type("B", (), {"deadline": "2026-10-17T13:00:00", "minutes": None})()
        self.assertIsNotNone(sapper.deadline_from_args(b))
        c = type("C", (), {"deadline": "2026-10-17T13:00:00+08:00", "minutes": 5})()
        with self.assertRaises(sapper.FGError):
            sapper.deadline_from_args(c)
        bad = type("D", (), {"deadline": "not-a-date", "minutes": None})()
        with self.assertRaises(sapper.FGError):
            sapper.deadline_from_args(bad)
        self.assertEqual(sapper.deadline_from_args(type("E", (), {"deadline": None, "minutes": None})()), None)

    def test_format_time_budget(self):
        self.assertEqual(sapper.format_time_budget(None), "")
        self.assertIn("TIME IS UP",
                      sapper.format_time_budget(0))  # 0 -> epoch 1970, always past
        self.assertIn("remaining", sapper.format_time_budget(_t.time() + 600))


import time as _t  # noqa: E402  (DeadlineTests)


class ArenaClientTests(unittest.TestCase):
    """Verify the exact TSecBench Challenges API contract (header, paths,
    params/body, error envelope)."""

    def _arena(self):
        import importlib.util
        spec = importlib.util.spec_from_file_location("_arena_test", ROOT / "lib" / "arena.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_client_contract_against_local_server(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        arena = self._arena()
        seen = []

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def _reply(self, obj, code=200):
                data = json.dumps(obj).encode()
                self.send_response(code)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def _record(self):
                length = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(length)) if length else None
                seen.append((self.command, self.path, self.headers.get("BENCHMARK_TOKEN"), body))

            def do_GET(self):
                self._record()
                if self.path.startswith("/openapi/v1/challenges/hint"):
                    return self._reply({"unique_code": "c1", "hint": "h"})
                return self._reply([{"unique_code": "c1", "difficulty": "easy", "level": "1",
                                     "total_score": 100, "flag_count": 2, "correct_flag_count": 0,
                                     "is_completed": False, "description": "d",
                                     "container_status": "stopped", "container_addr": []}])

            def do_POST(self):
                self._record()
                if self.path.startswith("/openapi/v1/challenges/submit"):
                    return self._reply({"correct": True, "awarded": 50, "cumulative_score": 50,
                                        "correct_flag_count": 1, "total_flag_count": 2,
                                        "matched_flag_index": 0})
                if self.path.startswith("/openapi/v1/challenges/close"):
                    return self._reply({"unique_code": "c1", "closed": True})
                return self._reply({"unique_code": "c1", "container_addr": ["10.0.0.9:80"]})

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = arena.ArenaClient(f"http://127.0.0.1:{server.server_address[1]}", "tok-x")
            chs = client.list_challenges()
            self.assertEqual(chs[0]["unique_code"], "c1")
            started = client.start_challenge("c1")
            self.assertEqual(started["container_addr"], ["10.0.0.9:80"])
            self.assertEqual(client.get_hint("c1")["hint"], "h")
            res = client.submit_flag("c1", "flag{a}")
            self.assertTrue(res["correct"])
            self.assertTrue(client.close_challenge("c1")["closed"])
        finally:
            server.shutdown()

        # every call carried the BENCHMARK_TOKEN header
        self.assertTrue(all(entry[2] == "tok-x" for entry in seen), seen)
        # exact paths + param/body shapes
        submit = [e for e in seen if e[1] == "/openapi/v1/challenges/submit"][0]
        self.assertEqual(submit[3], {"unique_code": "c1", "flag": "flag{a}"})
        start = [e for e in seen if "start" in e[1]][0]
        self.assertIn("unique_code=c1", start[1])
        hint = [e for e in seen if "hint" in e[1]][0]
        self.assertIn("unique_code=c1", hint[1])
        close = [e for e in seen if "close" in e[1]][0]
        self.assertIn("unique_code=c1", close[1])

    def test_error_envelope_surfaces_code(self):
        import threading
        from http.server import BaseHTTPRequestHandler, HTTPServer
        arena = self._arena()

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *args):
                pass

            def do_POST(self):
                data = json.dumps({"code": "invalid_state", "message": "max active", "detail": {}}).encode()
                self.send_response(409)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        server = HTTPServer(("127.0.0.1", 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            client = arena.ArenaClient(f"http://127.0.0.1:{server.server_address[1]}", "t")
            with self.assertRaises(arena.ArenaError) as ctx:
                client.start_challenge("c1")
            self.assertEqual(ctx.exception.code, "invalid_state")
            self.assertEqual(ctx.exception.status, 409)
        finally:
            server.shutdown()

    def test_config_resolution_env_and_file(self):
        arena = self._arena()
        with mock.patch.dict("os.environ", {"BENCHMARK_BASE_URL": "http://env-base",
                                            "BENCHMARK_TOKEN": "env-tok"}):
            c = arena.ArenaClient.load(None)
            self.assertEqual(c.base_url, "http://env-base")
            self.assertEqual(c.token, "env-tok")
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "arena.json").write_text(json.dumps(
                {"base_url": "http://file-base", "token": "ENV:BENCHMARK_TOKEN"}), encoding="utf-8")
            with mock.patch.dict("os.environ", {"BENCHMARK_TOKEN": "env-tok"}):
                c = arena.ArenaClient.load(Path(tmp))
                self.assertEqual(c.base_url, "http://file-base")
                self.assertEqual(c.token, "env-tok")
        with mock.patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(arena.ArenaError):
                arena.ArenaClient.load(None)
        with self.assertRaises(arena.ArenaError):
            arena.ArenaClient("http://x", "")

    def test_rejects_unsafe_unique_code(self):
        arena = self._arena()
        client = arena.ArenaClient("http://x", "t")
        with self.assertRaises(arena.ArenaError):
            client.start_challenge("../etc/passwd")


class CommanderTests(unittest.TestCase):
    def test_parse_command_payload(self):
        ok = {"accepted": True, "data": {"action": "work", "target": "c03", "minutes": 25, "note": "close"}}
        self.assertEqual(sapper._parse_command_payload(ok), ("work", "c03", 25, "close"))
        stop = {"accepted": True, "data": {"action": "stop", "reason": "all done"}}
        self.assertEqual(sapper._parse_command_payload(stop), ("stop", "", 0, "all done"))
        rej = {"accepted": False, "reason": "bad board"}
        self.assertEqual(sapper._parse_command_payload(rej)[0], "reject")
        with self.assertRaises(sapper.FGError):
            sapper._parse_command_payload({"accepted": True, "data": {"action": "hack"}})
        with self.assertRaises(sapper.FGError):
            sapper._parse_command_payload({"accepted": True, "data": {"action": "work", "minutes": 10}})
        with self.assertRaises(sapper.FGError):
            sapper._parse_command_payload({"accepted": True, "data": {"action": "work", "target": "c1", "minutes": 0}})

    def test_board_summary_and_render(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ("c01", "c02"):
                store = sapper.Store(root / name / ".sapper")
                store.init("t", f"flag {name}")
            sapper.Store(root / "c01" / ".sapper").add_fact(
                "flag captured: flag{a}", "agent",
                kind="flag", data={"value": "flag{a}", "challenge": "c01", "status": "submitted"})
            rows = sapper._board_summary(root)
            self.assertEqual([r["name"] for r in rows], ["c01", "c02"])
            by_name = {r["name"]: r for r in rows}
            self.assertEqual(by_name["c01"]["flags_submitted"], 1)
            self.assertEqual(by_name["c02"]["flags_submitted"], 0)
            board = sapper.render_board(rows)
            self.assertIn("c01", board)
            self.assertIn("flags(sub/rec)", board)


class FleetTests(unittest.TestCase):
    def test_fleet_pane_commands(self):
        cfg = {"session": "s", "root": "runs", "deadline": "2026-10-17T13:00:00",
               "panes": []}
        engine = sapper._sapper_engine_prefix()
        self.assertEqual(
            sapper._fleet_pane_command(cfg, {"type": "command"}),
            f"{engine} command --root runs --deadline 2026-10-17T13:00:00")
        self.assertEqual(
            sapper._fleet_pane_command(cfg, {"type": "auto:c02", "extra_args": "--verify"}),
            f"{engine} --store runs/c02/.sapper auto --deadline 2026-10-17T13:00:00 --verify")
        self.assertEqual(
            sapper._fleet_pane_command(cfg, {"type": "auto:c02"}, base_dir=Path("/w")),
            f"cd /w && {engine} --store runs/c02/.sapper auto --deadline 2026-10-17T13:00:00")
        self.assertEqual(
            sapper._fleet_pane_command({"root": "runs", "panes": []}, {"type": "shell", "command": "top"}),
            "top")
        with self.assertRaises(sapper.FGError):
            sapper._fleet_pane_command(cfg, {"type": "warp"})
        with self.assertRaises(sapper.FGError):
            sapper._fleet_pane_command(cfg, {"type": "shell"})

    def test_fleet_init_and_load(self):
        with tempfile.TemporaryDirectory() as tmp:
            old = Path.cwd()
            try:
                import os
                os.chdir(tmp)
                args = type("A", (), {"action": "init", "file": "fleet.json"})()
                self.assertEqual(sapper.cmd_fleet(args), 0)
                cfg = sapper._fleet_load(Path("fleet.json"))
                self.assertTrue(cfg["panes"])
                args2 = type("A", (), {"action": "init", "file": "fleet.json"})()
                with self.assertRaises(sapper.FGError):
                    sapper.cmd_fleet(args2)
            finally:
                os.chdir(old)


class HireFireTests(unittest.TestCase):
    def test_parse_command_payload_hire_fire(self):
        hire = {"accepted": True, "data": {"action": "hire", "target": "c07", "minutes": 30}}
        self.assertEqual(sapper._parse_command_payload(hire), ("hire", "c07", 30, ""))
        fire = {"accepted": True, "data": {"action": "fire", "target": "c07", "note": "stuck"}}
        self.assertEqual(sapper._parse_command_payload(fire), ("fire", "c07", 0, "stuck"))
        with self.assertRaises(sapper.FGError):
            sapper._parse_command_payload({"accepted": True, "data": {"action": "warp", "target": "c"}})
        with self.assertRaises(sapper.FGError):
            sapper._parse_command_payload({"accepted": True, "data": {"action": "hire", "minutes": 10}})
        with self.assertRaises(sapper.FGError):
            sapper._parse_command_payload({"accepted": True, "data": {"action": "hire", "target": "c", "minutes": -1}})

    def test_active_workers_parsing(self):
        with mock.patch.object(sapper, "_tmux") as tm:
            tm.return_value = mock.Mock(returncode=1)
            self.assertEqual(sapper._active_workers("nope"), set())
            tm.return_value = mock.Mock(returncode=0, stdout="commander\nw-c01\nw-c07\nboard\n")
            self.assertEqual(sapper._active_workers("s"), {"c01", "c07"})

    def test_board_render_worker_column(self):
        rows = [
            {"name": "c01", "status": "active", "flags_submitted": 1, "flags_recorded": 0,
             "kinds": "1 flag", "open_intents": 2, "last_activity": "t", "goal": "g", "worker": "yes"},
            {"name": "c02", "status": "active", "flags_submitted": 0, "flags_recorded": 0,
             "kinds": "-", "open_intents": 0, "last_activity": "t", "goal": "g", "worker": "-"},
        ]
        board = sapper.render_board(rows)
        self.assertIn("worker", board)
        self.assertIn("worker=yes means", board)


import os  # noqa: E402  (KeyRotationTests)


class KeyRotationTests(unittest.TestCase):
    def test_quota_matcher(self):
        self.assertTrue(sapper._is_quota_error("insufficient balance (quota exceeded)"))
        self.assertTrue(sapper._is_quota_error("Error 401: Unauthorized"))
        self.assertTrue(sapper._is_quota_error("账户欠费，请充值"))
        self.assertFalse(sapper._is_quota_error("connection timed out"))
        self.assertFalse(sapper._is_quota_error("claude exited 2: bad args"))

    def test_pool_load_and_rotate(self):
        pool_json = json.dumps([
            {"base_url": "http://a", "token": "t1", "model": "m1"},
            {"base_url": "http://b", "token": "t2", "model": "m2"},
        ])
        with mock.patch.dict("os.environ", {
            "SAPPER_KEY_POOL": pool_json, "ANTHROPIC_AUTH_TOKEN": "t1",
            "ANTHROPIC_BASE_URL": "http://a", "SAPPER_MODEL": "m1"}):
            self.assertTrue(sapper._rotate_key())
            self.assertEqual(os.environ["ANTHROPIC_AUTH_TOKEN"], "t2")
            self.assertEqual(os.environ["ANTHROPIC_BASE_URL"], "http://b")
            self.assertEqual(os.environ["SAPPER_MODEL"], "m2")
        with mock.patch.dict("os.environ", {"SAPPER_KEY_POOL": "not json"}):
            self.assertEqual(sapper._load_key_pool(), [])
        with mock.patch.dict("os.environ", {"SAPPER_KEY_POOL": ""}):
            self.assertFalse(sapper._rotate_key())
        # single-entry pool: rotate returns True but keeps the key
        with mock.patch.dict("os.environ", {
            "SAPPER_KEY_POOL": json.dumps([{"base_url": "http://a", "token": "t1"}]),
            "ANTHROPIC_AUTH_TOKEN": "t1"}):
            self.assertTrue(sapper._rotate_key())
            self.assertEqual(os.environ["ANTHROPIC_AUTH_TOKEN"], "t1")
