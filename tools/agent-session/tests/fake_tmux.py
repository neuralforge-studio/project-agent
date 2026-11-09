"""A test double for `agent_session.tmux.Tmux` that cannot drift from the product class.

A fake derives from `FakeTmux`. It writes only the methods its test needs. Two guards keep it honest:

- a fake method must exist on the product `Tmux` with the same parameter names, checked when the fake
  class is defined (a renamed or removed product method fails the test module at import);
- a product method the fake does not write still resolves, but its tmux command raises `AssertionError`
  naming the command, so a new product call into tmux fails loudly instead of `AttributeError` or a real
  tmux call (SESSION-007 added `require_version` to the restart path, and a fake without it broke).
"""

import inspect

from agent_session.tmux import Tmux


def _parameters(function):
    return list(inspect.signature(function).parameters)


class FakeTmux(Tmux):
    def __init__(self):                                  # no socket, and no tmux process
        pass

    def __init_subclass__(cls, **keywords):
        super().__init_subclass__(**keywords)
        for name, value in vars(cls).items():
            if name.startswith("_") or not inspect.isfunction(value):
                continue
            product = getattr(Tmux, name, None)
            assert inspect.isfunction(product), f"{cls.__name__}.{name} is not a method of agent_session.tmux.Tmux"
            assert _parameters(value) == _parameters(product), (
                f"{cls.__name__}.{name}{inspect.signature(value)} differs from Tmux.{name}{inspect.signature(product)}")

    def _run(self, *arguments, allow_missing=False):
        raise AssertionError(f"{type(self).__name__} does not fake the tmux call {arguments!r}; write the method it needs")
