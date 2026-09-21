"""Credentials are shared locally without becoming public defaults or log output."""

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor

import pytest

from examples import _session
from wrs_agent.processes import NO_WINDOW, python_command


@pytest.fixture
def token_dir(monkeypatch, tmp_path):
    monkeypatch.setenv("WRS_AGENT_TOKEN", "")
    monkeypatch.setattr(_session, "_TOKEN_DIR", tmp_path / "tokens")
    return _session._TOKEN_DIR


def test_service_generates_and_client_reuses_private_configuration(monkeypatch, token_dir, capsys):
    _session.use_local_token("wrs", create=True)
    token = os.environ["WRS_AGENT_TOKEN"]
    assert len(token) == 43
    assert (token_dir / "wrs.token").read_text() == token
    if os.name != "nt":
        assert (token_dir / "wrs.token").stat().st_mode & 0o777 == 0o600
    monkeypatch.delenv("WRS_AGENT_TOKEN")
    _session.use_local_token("wrs")
    assert os.environ["WRS_AGENT_TOKEN"] == token
    monkeypatch.delenv("WRS_AGENT_TOKEN")
    _session.use_local_token("wrs", create=True)
    assert os.environ["WRS_AGENT_TOKEN"] == token
    assert token not in capsys.readouterr().out


def test_example_groups_do_not_share_credentials(monkeypatch, token_dir):
    tokens = set()
    for group in ("connect", "nodes", "wrs", "tts", "voice"):
        monkeypatch.delenv("WRS_AGENT_TOKEN", raising=False)
        _session.use_local_token(group, create=True)
        tokens.add(os.environ["WRS_AGENT_TOKEN"])
    assert len(tokens) == 5


def test_explicit_environment_wins_without_reading_or_saving_it(monkeypatch, token_dir, capsys):
    token = "explicit-test-credential"
    monkeypatch.setenv("WRS_AGENT_TOKEN", token)
    _session.use_local_token("wrs", create=True)
    assert os.environ["WRS_AGENT_TOKEN"] == token
    assert not token_dir.exists()
    assert token not in capsys.readouterr().out


@pytest.mark.parametrize("token", ["short", "x" * 129, " " * 20, "密" * 20])
def test_invalid_explicit_token_is_not_replaced(monkeypatch, token_dir, token):
    monkeypatch.setenv("WRS_AGENT_TOKEN", token)
    with pytest.raises(SystemExit, match="WRS_AGENT_TOKEN"):
        _session.use_local_token("wrs", create=True)
    assert os.environ["WRS_AGENT_TOKEN"] == token
    assert not token_dir.exists()


@pytest.mark.parametrize("group", ["connect", "nodes", "wrs", "tts", "voice"])
def test_client_first_names_the_service_to_run(token_dir, group):
    with pytest.raises(SystemExit, match="请先运行") as error:
        _session.use_local_token(group)
    assert _session._STARTERS[group] in str(error.value)
    assert not token_dir.exists()


@pytest.mark.parametrize("contents", [b"", b"short", b"x" * 129, b" " * 20, b"\xff" * 20])
def test_corrupt_file_requires_explicit_recovery(token_dir, contents):
    token_dir.mkdir()
    path = token_dir / "wrs.token"
    path.write_bytes(contents)
    with pytest.raises(SystemExit, match="口令文件无效"):
        _session.use_local_token("wrs", create=True)
    assert path.read_bytes() == contents
    assert not os.environ["WRS_AGENT_TOKEN"]


def test_concurrent_starters_publish_one_complete_credential(token_dir, tmp_path):
    worker = tmp_path / "token_worker.py"
    worker.write_text(
        "import os, sys\nfrom pathlib import Path\n"
        "from examples import _session\n"
        "_session._TOKEN_DIR = Path(sys.argv[1])\n"
        "_session.use_local_token('nodes', create=True)\n"
        "assert os.environ['WRS_AGENT_TOKEN'] == "
        "(_session._TOKEN_DIR / 'nodes.token').read_text()\n",
        encoding="utf-8",
    )

    def run():
        return subprocess.run(
            python_command(worker, token_dir),
            capture_output=True, text=True, encoding="utf-8",
            cwd=tmp_path, timeout=15, creationflags=NO_WINDOW,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(lambda _: run(), range(4)))
    token = (token_dir / "nodes.token").read_text()
    assert len(token) == 43
    assert [path.name for path in token_dir.iterdir()] == ["nodes.token"]
    for result in results:
        assert result.returncode == 0, result.stderr
        assert token not in result.stdout + result.stderr
