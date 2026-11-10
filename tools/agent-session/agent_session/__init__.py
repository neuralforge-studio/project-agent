"""Shared tmux sessions for project leaders and workers."""


def _start_from_bundle():
    """Serve this tool's modules and the standard library's from the release's start-up bundle.

    The commands that `launch_artifacts` and the Claude provider generate (registration hook, `mark_process`,
    controller) start `python -S -c ...` and import `agent_session.internal`; each of them would open a file per
    module. The first import of the package comes here before any other module is loaded, so it installs the
    bundle reader (install contract 6.1; `tools/bundle_boot.py` owns the reader and the file layout) as an entry
    point of the CLI does. Nothing happens when a reader is installed already (the CLI entry points do it before
    they import the package) or when `tools/bundle_boot.py` is not beside the tool (a remote runtime's copy). Without
    a bundle that fits, the reader leaves the ordinary import in charge."""
    import os
    import sys

    if any(getattr(finder, "project_agent_bundle", False) for finder in sys.meta_path):
        return
    tools = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    reader = tools + "/bundle_boot.py"
    try:
        with open(reader, encoding="utf-8") as handle:
            source = handle.read()
    except OSError:
        return
    namespace = {}
    exec(compile(source, reader, "exec", dont_inherit=True), namespace)
    namespace["_project_agent_bundle"](tools)


_start_from_bundle()
