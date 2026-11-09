"""PERF-001 instrumentation, loaded only through PYTHONPATH of the harness.

- every subprocess.Popen: one `spawn` line (name) and, when it is waited, one `wait` line (seconds)
- time.sleep: one `sleep` line (seconds)
- PERF_FAKE=1: agent_session.providers.get_provider returns the test fixture's FakeClaudeProvider, so the
  product code runs unchanged but no real Claude CLI is involved (the provider cost is measured apart).
"""
import os
import sys
import time

LOG = os.environ.get("PERF_SPAWN_LOG")
if LOG:
    import subprocess
    _fd = os.open(LOG, os.O_WRONLY | os.O_APPEND | os.O_CREAT, 0o644)

    def _w(text):
        try:
            os.write(_fd, text.encode())
        except OSError:
            pass

    _init, _wait, _sleep = subprocess.Popen.__init__, subprocess.Popen.wait, time.sleep

    def _name(args):
        first = args[0] if isinstance(args, (list, tuple)) and args else str(args).split()[0]
        name = os.path.basename(str(first))
        if name.startswith("python"):
            name = "python"
        if name.startswith("tmux"):
            name = "tmux"
        return name

    def init(self, args, *a, **k):
        self._perf_name = _name(args)
        self._perf_t = time.perf_counter()
        _w(f"spawn\t{self._perf_name}\t0\n")
        _init(self, args, *a, **k)

    def wait(self, timeout=None):
        result = _wait(self, timeout)
        if not getattr(self, "_perf_done", False) and getattr(self, "_perf_t", None) is not None:
            self._perf_done = True
            _w(f"wait\t{self._perf_name}\t{time.perf_counter() - self._perf_t:.4f}\n")
        return result

    def sleep(seconds):
        _w(f"sleep\t{seconds}\n")
        return _sleep(seconds)

    subprocess.Popen.__init__ = init
    subprocess.Popen.wait = wait
    time.sleep = sleep

if os.environ.get("PERF_FAKE") == "1":
    import importlib.abc
    import importlib.machinery

    class _Patch(importlib.abc.MetaPathFinder):
        def find_spec(self, name, path, target=None):
            if name != "agent_session.providers":
                return None
            sys.meta_path.remove(self)
            spec = importlib.machinery.PathFinder.find_spec(name, path)
            sys.meta_path.insert(0, self)
            if spec is None or spec.loader is None:
                return spec
            loader = spec.loader
            real_exec = loader.exec_module

            def exec_module(module):
                real_exec(module)
                fixtures = os.environ.get("PERF_FIXTURES")
                if not fixtures:                  # a pane of the tmux server: its fake CLI patches itself
                    return
                if fixtures not in sys.path:
                    sys.path.insert(0, fixtures)
                from agent_session_fake_provider import FakeClaudeProvider
                module.get_provider = lambda provider: FakeClaudeProvider()
            loader.exec_module = exec_module
            return spec

    sys.meta_path.insert(0, _Patch())
