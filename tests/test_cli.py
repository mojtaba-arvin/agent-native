import json
from argparse import Namespace

from agent_native.cli import command_init, command_inspect, command_validate, command_verify


def test_init_creates_service_contract_and_app(tmp_path, capsys):
    result = command_init(Namespace(path=str(tmp_path / "svc"), name="orders-api"))
    payload = json.loads(capsys.readouterr().out)
    assert result == 0
    assert payload["ok"] is True
    assert (tmp_path / "svc" / "agent-native.json").is_file()
    assert (tmp_path / "svc" / "main.py").is_file()


def test_init_rejects_invalid_service_name(tmp_path, capsys):
    result = command_init(Namespace(path=str(tmp_path / "svc"), name="Invalid Name"))
    payload = json.loads(capsys.readouterr().out)
    assert result == 2
    assert payload["ok"] is False
    assert not (tmp_path / "svc").exists()


def test_validate_and_inspect_example(capsys):
    from pathlib import Path
    example = Path(__file__).parents[1] / "examples" / "orders-service"
    assert command_validate(Namespace(path=str(example))) == 0
    assert json.loads(capsys.readouterr().out)["valid"] is True
    assert command_inspect(Namespace(path=str(example))) == 0
    assert json.loads(capsys.readouterr().out)["contract"] == "agent-native.service/v1"


def test_verify_example(capsys):
    from pathlib import Path
    example = Path(__file__).parents[1] / "examples" / "orders-service"
    assert command_verify(Namespace(path=str(example))) == 0
    result = json.loads(capsys.readouterr().out)
    assert result["verified"] is True
