import contextlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest import mock

from repo_bugbot import checkers, desktop_api, review, revisions, storage


@contextlib.contextmanager
def provider_server(sync=False):
    requests = []
    barrier = threading.Barrier(3) if sync else None

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            requests.append((self.path, body, self.headers))
            if barrier:
                barrier.wait(4)
            if body["model"] == "unavailable":
                self.send_error(503)
                return
            finding = {
                "file": "billing.py",
                "line": 2,
                "severity": "high",
                "title": "Lost cents",
                "detail": "Ten dollars would become ten cents.",
            }
            answer = json.dumps(
                {"findings": [] if body["model"] == "clean" else [finding]}
            )
            if self.path.endswith("/messages"):
                response = {"content": [{"type": "text", "text": answer}]}
            elif self.path.endswith("/api/chat"):
                response = {"message": {"content": answer}}
            else:
                response = {"choices": [{"message": {"content": answer}}]}
            if body["model"] == "short":
                response["done_reason"] = "length"
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(response).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:" + str(server.server_port), requests
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.repo = Path(self.temp.name) / "code"
        self.repo.mkdir()
        env = mock.patch.dict(
            os.environ, {"REPO_BUGBOT_HOME": str(self.repo.parent / "home")}
        )
        env.start()
        self.addCleanup(env.stop)
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.hooksPath", os.devnull)
        self.git("config", "user.name", "Fixture")
        self.git("config", "user.email", "fixture@example.invalid")
        self.git("config", "commit.gpgSign", "false")
        self.initial_history = revisions.history(self.repo)
        (self.repo / "billing.py").write_text(
            "def cents(dollars):\n    return round(dollars * 100)\n"
        )
        self.commit("Introduce billing (#42)")
        self.first = self.git("rev-parse", "HEAD")
        (self.repo / "billing.py").write_text(
            "def cents(dollars):\n    return round(dollars)\n"
        )
        self.commit(
            "Change currency conversion",
            "See #42, other/project#9 and https://github.com/other/project/issues/9.",
        )
        self.head = self.git("rev-parse", "HEAD")

    def git(self, *args):
        return subprocess.check_output(
            ["git", "-C", str(self.repo), *args], text=True
        ).strip()

    def commit(self, message, body=""):
        self.git("add", "-A")
        self.git("commit", "-qm", message, "-m", body)

    def test_history_root_and_immutable_comparison(self):
        self.assertFalse(self.initial_history["commits"])
        (self.repo / "billing.py").write_text(
            "uncommitted edits must not affect review\n"
        )
        root = revisions.inspect(self.repo, self.first)
        self.assertEqual(root["files"][0]["status"], "A")
        changes = revisions.inspect(self.repo)
        self.assertEqual(changes["base"], self.first)
        self.assertEqual(changes["files"][0]["added"], 1)
        self.assertEqual({r["id"] for r in changes["refs"]}, {"#42", "other/project#9"})
        self.assertEqual(changes["related"][0]["sha"], self.first)
        patch = revisions.patch(self.repo, self.first, self.head)["text"]
        self.assertIn("+    return round(dollars)", patch)
        self.assertNotIn("uncommitted", patch)
        self.assertEqual(
            revisions.comparison(self.repo, self.head, self.first),
            (self.first, self.head),
        )
        self.assertTrue(
            revisions.patch(self.repo, self.first, self.head, limit=10)["truncated"]
        )

    def test_rename_binary_and_literal_paths(self):
        self.git("mv", "billing.py", "line\t[name].py")
        (self.repo / "raw.bin").write_bytes(b"\0\1\2")
        self.commit("Rename billing")
        snapshot = revisions.inspect(self.repo)
        files = {f["path"]: f for f in snapshot["files"]}
        new = files["line\t[name].py"]
        self.assertEqual((new["status"], new["oldPath"]), ("R", "billing.py"))
        self.assertIsNone(files["raw.bin"]["added"])
        self.assertIn(
            "rename from",
            revisions.patch(
                self.repo,
                snapshot["base"],
                snapshot["head"],
                [new["path"], new["oldPath"]],
            )["text"],
        )

    def test_three_concurrent_protocols_and_stored_attribution(self):
        with provider_server(sync=True) as (base, calls):
            rows = [
                dict(checkers.defaults(p), model="sample", endpoint=base, keyEnv="")
                for p in ("openai", "anthropic", "ollama")
            ]
            result = review.run(self.repo, self.head, None, {"checkers": rows})
        self.assertEqual(result["status"], "complete")
        self.assertEqual(len(result["findings"]), 1)
        self.assertEqual(len(result["findings"][0]["checkers"]), 3)
        self.assertEqual(
            {p for p, _, _ in calls}, {"/messages", "/api/chat", "/chat/completions"}
        )
        self.assertEqual(storage.runs(self.repo, self.first, self.head), [result])
        self.assertFalse(storage.runs(self.repo, self.head, self.head))
        self.assertTrue(
            all(self.head in body["messages"][0]["content"] for _, body, _ in calls)
        )

    def test_model_error_survives_alongside_success(self):
        with provider_server() as (base, _):
            rows = [
                dict(
                    checkers.defaults("lmstudio"),
                    name=model,
                    model=model,
                    endpoint=base,
                )
                for model in ("unavailable", "clean")
            ]
            result = review.run(self.repo, self.head, None, {"checkers": rows})
        self.assertEqual(result["status"], "incomplete")
        self.assertEqual(
            [c["status"] for c in result["checkers"]], ["error", "completed"]
        )
        self.assertFalse(result["findings"])

    def test_compatible_providers_and_cli_adapters(self):
        with provider_server() as (base, calls):
            for provider in ("gemini", "openrouter", "lmstudio"):
                cfg = dict(
                    checkers.defaults(provider), endpoint=base, model="clean", keyEnv=""
                )
                self.assertEqual(
                    json.loads(checkers.ask(cfg, "fixture")), {"findings": []}
                )
            self.assertEqual([p for p, _, _ in calls], ["/chat/completions"] * 3)

        def fake(command, **opts):
            self.assertNotEqual(Path(opts["cwd"]), self.repo)
            self.assertEqual(opts["input"], "fixture")
            if command[0] == "codex":
                self.assertIn("read-only", command)
                Path(command[command.index("--output-last-message") + 1]).write_text(
                    '{"findings":[]}'
                )
            else:
                self.assertEqual(command[command.index("--tools") + 1], "")
            return subprocess.CompletedProcess(command, 0, '{"findings":[]}', "")

        with mock.patch.object(checkers.subprocess, "run", side_effect=fake):
            for provider in ("codex", "claude"):
                self.assertEqual(
                    json.loads(checkers.ask(checkers.defaults(provider), "fixture")),
                    {"findings": []},
                )

    def test_config_and_model_output_validation(self):
        with self.assertRaises(ValueError):
            checkers.validate_config({"checkers": [checkers.defaults("codex")] * 2})
        with self.assertRaises(ValueError):
            checkers.validate_config(
                {
                    "checkers": [
                        dict(
                            checkers.defaults("ollama"),
                            endpoint="http://remote.example",
                        )
                    ]
                }
            )
        for answer in ("{}", '{"findings":[{}]}', "not JSON"):
            with self.assertRaises((TypeError, ValueError)):
                review.parse_answer(answer, {"billing.py"})
        self.assertEqual(
            review.parse_answer('```json\n{"findings":[]}\n```', set()), []
        )

    def test_cli_and_legacy_commands(self):
        def module(name, *args):
            return subprocess.run(
                [sys.executable, "-m", "repo_bugbot." + name, *args],
                check=False,
                capture_output=True,
                text=True,
            )

        config = self.repo.parent / "chosen.json"
        self.assertEqual(module("review", "--init-config", str(config)).returncode, 0)
        self.assertEqual(module("review", "--init-config", str(config)).returncode, 2)
        with provider_server() as (base, _):
            for model, expected in (
                ("clean", 0),
                ("finding", 1),
                ("unavailable", 2),
                ("short", 2),
            ):
                storage.save(
                    config,
                    {
                        "checkers": [
                            dict(
                                checkers.defaults("ollama"), endpoint=base, model=model
                            )
                        ]
                    },
                )
                outcome = module(
                    "review", "--repo", str(self.repo), "--config", str(config)
                )
                self.assertEqual(outcome.returncode, expected, outcome.stderr)
                self.assertEqual(json.loads(outcome.stdout)["head"], self.head)
        self.assertEqual(
            module("index_repo_graph", "--repo", str(self.repo)).returncode, 0
        )
        self.assertEqual(
            module(
                "diff_impact", "--repo", str(self.repo), "--base", self.first
            ).returncode,
            0,
        )

    def test_issue_lookup_links_by_evidence(self):
        issue = {
            "title": "Wrong amount",
            "state": "open",
            "body": "See #9 and #42",
            "pull_request": {},
        }
        response = subprocess.CompletedProcess([], 0, json.dumps(issue).encode(), b"")
        with mock.patch.object(
            desktop_api.subprocess, "run", return_value=response
        ) as gh:
            data = desktop_api.issue_details("sample/store", 42)
        self.assertEqual(data["refs"][0]["id"], "sample/store#9")
        self.assertEqual(gh.call_args.args[0][-1], "repos/sample/store/issues/42")
        with self.assertRaises(ValueError):
            desktop_api.issue_details("--bad", 4)


if __name__ == "__main__":
    unittest.main()
