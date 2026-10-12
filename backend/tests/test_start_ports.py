"""启动端口检测回归：真实监听必须拦截，关闭连接后的地址应可重新使用。"""

import importlib.util
import socket
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("supportdesk_dev", Path(__file__).resolve().parents[2] / "scripts/dev.py")
assert spec and spec.loader
dev = importlib.util.module_from_spec(spec)
spec.loader.exec_module(dev)


def test_live_listener_is_rejected():
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        with pytest.raises(RuntimeError, match="无法监听"):
            dev.check_port(server.getsockname()[1])


def test_closed_connection_can_restart():
    # 服务端主动关闭已建立连接，使原监听地址留下 TIME_WAIT，而非残留进程。
    with socket.socket() as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.settimeout(2)
        server.bind(("127.0.0.1", 0))
        port = server.getsockname()[1]
        server.listen(1)
        with socket.create_connection(("127.0.0.1", port), timeout=2) as client:
            connection, _ = server.accept()
            connection.close()
            assert client.recv(1) == b""
    dev.check_port(port)


def test_compose_combines_databases_without_removing_existing_data():
    """两个数据库共用项目配置；不能通过删除孤立容器来消除提示。"""
    command = dev.COMPOSE
    assert command.count("-f") == 2
    assert str(dev.ROOT / "docker-compose.yml") in command
    assert str(dev.ROOT / "docker-compose.graph.yml") in command
    assert command[command.index("--env-file") + 1] == str(dev.ROOT / "backend/.env")
    assert "--remove-orphans" not in command


def test_preflight_validates_compose_without_showing_secrets(monkeypatch, tmp_path):
    """模拟文件和依赖，仅验证启动计划，不连接 Docker 或安装任何工具。"""
    monkeypatch.setattr(dev, "ROOT", tmp_path)
    for relative in (
        "backend/.env", "frontend/.env.local", "frontend/node_modules/vite/bin/vite.js",
        "docker-compose.yml", "docker-compose.graph.yml",
    ):
        file = tmp_path / relative
        file.parent.mkdir(parents=True, exist_ok=True)
        file.touch()
    calls = []
    monkeypatch.setattr(dev.shutil, "which", lambda _: "/test/tool")
    monkeypatch.setattr(dev, "check_port", lambda _: None)
    monkeypatch.setattr(dev, "run", lambda command, **kwargs: calls.append(command))
    dev.preflight()
    assert calls[-1] == [*dev.COMPOSE, "config", "--quiet"]


def test_both_databases_are_healthy_before_migration(monkeypatch, capsys):
    calls = []
    monkeypatch.setattr(dev, "docker_ready", lambda: True)
    monkeypatch.setattr(dev, "run", lambda command, **kwargs: calls.append(command))
    dev.prepare_database()
    assert calls[0][-2:] == ["postgres", "neo4j"]
    assert "--wait" in calls[0]
    assert calls[0][calls[0].index("--pull") + 1] == "never"
    assert calls[1][1:] == ["-m", "alembic", "upgrade", "head"]
    assert "Neo4j 容器已就绪" in capsys.readouterr().out


def test_database_failure_prevents_migration_and_success_message(monkeypatch, capsys):
    """任一数据库健康检查失败，就不能迁移或误报全部启动成功。"""
    calls = []
    monkeypatch.setattr(dev, "docker_ready", lambda: True)

    def fail(command, **kwargs):
        calls.append(command)
        raise dev.subprocess.CalledProcessError(1, command)

    monkeypatch.setattr(dev, "run", fail)
    with pytest.raises(dev.subprocess.CalledProcessError):
        dev.prepare_database()
    assert len(calls) == 1
    output = capsys.readouterr().out
    assert "容器已就绪" not in output
    assert "迁移执行完成" not in output


def test_summary_includes_graph_addresses_and_shutdown_scope(capsys):
    dev.print_ready_summary()
    output = capsys.readouterr().out
    assert "http://127.0.0.1:3000/" in output
    assert "http://127.0.0.1:8000/docs" in output
    assert "http://127.0.0.1:7474/" in output
    assert "bolt://127.0.0.1:7687" in output
    assert "PostgreSQL 和 Neo4j 保持运行" in output
    assert "SUPPORT_GRAPH_ENABLED" in output
