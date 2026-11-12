"""The tmux minimum version of install-contract.md section 3.2 (the integration file and the contract state one
value). What `install` and `check` do with the tmux they find is in test_tmux_record.py (contract 6.2)."""

import re

from harness import INSTALLER, REPO
import sys

sys.path.insert(0, str(INSTALLER.parent))
from project_agent_install import runs  # noqa: E402

CONTRACT = REPO / "docs/project-team/install-contract.md"


def contract_minimum():
    """The minimum the contract states (the line `최소 버전: tmux X`)."""
    return re.search(r"^최소 버전: tmux (\S+)$", CONTRACT.read_text(), re.MULTILINE).group(1)


def test_the_minimum_of_the_integration_file_is_the_one_of_the_contract():
    conf = (REPO / "integrations/tmux/project-agent.conf").read_text()
    assert re.findall(r"^set-option -g @project_agent_tmux_min '(.+)'$", conf, re.MULTILINE) == [contract_minimum()]
    assert "tmux %s or newer" % contract_minimum() in conf          # the notice of an old tmux names it
    assert runs.api_of(REPO).COMPANY_TMUX in conf         # the one definition is agent_session's; the notice copies it
