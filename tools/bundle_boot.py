"""Reader of the release's start-up bundle (install contract 6.1, "시동 번들").

The entry points read this file into the `-c` program of `python -S` (python-launcher.sh,
`project_agent_read_boot`); it is never imported. A command that runs for a tenth of a second spends most
of its time opening files: on the workstation every open and close of a file on NFS costs a few milliseconds,
and a CLI imports a hundred modules. The installer therefore writes the compiled code of the three tools'
modules and of the standard library modules they import into one file, and this reader serves those modules
from that one open file.

File `tools/__pycache__/bundle.<cache tag>.pyc` (written by install/project_agent_install/bundle.py, which
owns this layout together with this file; a test builds a bundle and imports through the reader):
    4 bytes  little-endian size of the header
    header   marshal of (MAGIC_NUMBER, sys.version, {module name: (offset, size, is_package, origin)})
    code     marshal of each module's code object; `offset` counts from the end of the header
`origin` is the module's source file: an absolute path (standard library) or a path relative to `tools/`
(the tools' own modules). The code objects name the same files. Only the header is read at the start; a
module's code is read when the module is imported.

Anything that does not fit (no file, another interpreter build, `-O`, a damaged header) leaves the ordinary
import in charge; a module that is not in the bundle is found where it always was.

The finder it installs has the class attribute `project_agent_bundle = True`. A caller that may run after
another one (`agent_session/__init__.py`, which starts the processes the generated commands run: hook,
controller, `mark_process`) looks for it in `sys.meta_path` and does not install a second finder.
"""


def _project_agent_bundle(tools_directory):
    import os
    import sys
    from posixpath import normpath
    if sys.flags.optimize:
        return
    try:
        descriptor = os.open("%s/__pycache__/bundle.%s.pyc" % (tools_directory, sys.implementation.cache_tag), os.O_RDONLY)
    except OSError:
        return
    import marshal
    # The two modules that importlib.machinery and importlib.util re-export from: they are loaded already, while
    # importing those would first load `importlib`, `types` and `warnings` from their own files.
    from _frozen_importlib import ModuleSpec
    from _frozen_importlib_external import MAGIC_NUMBER

    def read(offset, length):
        data = os.pread(descriptor, length, offset)
        while len(data) < length:
            more = os.pread(descriptor, length - len(data), offset + len(data))
            if not more:
                raise ImportError("the start-up bundle is truncated")
            data += more
        return data

    try:
        size = int.from_bytes(read(0, 4), "little")
        magic, version, modules = marshal.loads(read(4, size))
        if magic != MAGIC_NUMBER or version != sys.version:
            raise ValueError("another interpreter")
    except (ValueError, EOFError, TypeError, ImportError):
        os.close(descriptor)
        return
    start = 4 + size

    class BundleFinder:
        project_agent_bundle = True

        @staticmethod
        def _origin(name):
            origin = modules[name][3]
            return origin if origin.startswith("/") else normpath("%s/%s" % (tools_directory, origin))

        def find_spec(self, name, path=None, target=None):
            entry = modules.get(name)
            if entry is None:
                return None
            origin = self._origin(name)
            spec = ModuleSpec(name, self, origin=origin, is_package=entry[2])
            spec.has_location = True
            if entry[2]:
                spec.submodule_search_locations = [origin.rpartition("/")[0]]
            return spec

        def create_module(self, spec):
            return None

        def get_code(self, name):
            offset, length = modules[name][:2]
            return marshal.loads(read(start + offset, length))

        def exec_module(self, module):
            exec(self.get_code(module.__spec__.name), module.__dict__)

        def is_package(self, name):
            return modules[name][2]

        def get_filename(self, name):
            return self._origin(name)

        def get_source(self, name):
            try:
                with open(self._origin(name), encoding="utf-8") as handle:
                    return handle.read()
            except OSError:
                return None

    sys.meta_path.insert(0, BundleFinder())
