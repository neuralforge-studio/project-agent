"""Fixtures of the installer tests: an isolated HOME and a Git copy of the product to release."""

from pathlib import Path
import shutil
import tempfile

import pytest

from harness import Home, build_product_repository, release_name
import private_root  # noqa: E402  (harness puts tools/tests on sys.path)


@pytest.fixture(scope="session")
def product_repository():
    root = Path(tempfile.mkdtemp(prefix="pi-src-"))
    yield build_product_repository(root / "product")
    shutil.rmtree(root, ignore_errors=True)


@pytest.fixture
def home():
    isolated = Home()
    yield isolated
    isolated.close()


def pytest_configure(config):
    config.addinivalue_line("markers", "mutates: the test commits to or edits its source repository")
    private_root.configure(config, temp=True)  # the `pi-*` directories below go inside the run's private root


def pytest_sessionfinish(session, exitstatus):
    private_root.finish(session, exitstatus)


@pytest.fixture
def source(request, home, product_repository):
    """The product repository to release. A test marked `mutates` gets its own copy; the others share one
    that they only read."""
    if request.node.get_closest_marker("mutates") is None:
        return product_repository
    target = home.root / "src"
    shutil.copytree(product_repository, target, symlinks=True)
    return target


@pytest.fixture
def name(source):
    return release_name(source)


@pytest.fixture
def runs(home):
    """A registered project on a private tmux server (create before the install)."""
    if shutil.which("tmux") is None:
        pytest.skip("tmux is unavailable")
    from harness import Runs
    project = Runs(home)
    yield project
    project.close()
