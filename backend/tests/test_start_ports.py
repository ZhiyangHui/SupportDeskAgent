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
