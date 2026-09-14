"""本地开发进程管理：启动基础设施、迁移和前后端，退出时回收本次启动的进程。"""

import argparse
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener

ROOT = Path(__file__).resolve().parents[1]
COMPOSE = ["docker", "compose", "-f", str(ROOT / "docker-compose.yml")]


def announce(message: str) -> None:
    """及时输出启动阶段，避免等待 Docker 时看起来没有响应。"""
    print(f"[启动] {message}", flush=True)


def run(command: list[str], *, cwd: Path = ROOT, timeout: int = 120) -> None:
    """短任务失败立即终止，禁止迁移失败后继续启动应用。"""
    subprocess.run(command, cwd=cwd, check=True, timeout=timeout)


def preflight() -> None:
    """先检查现有工具与配置，不自动安装依赖或覆盖用户文件。"""
    for command in ("docker", "node"):
        if not shutil.which(command):
            raise RuntimeError(f"缺少 {command}，请自行安装后再启动。")
    for relative in (
        "backend/.env",
        "frontend/.env.local",
        "frontend/node_modules/vite/bin/vite.js",
    ):
        if not (ROOT / relative).is_file():
            raise RuntimeError(f"缺少 {relative}，请先完成配置或自行安装依赖。")
    # 端口被占用时明确退出，不误杀用户在其他终端启动的进程，也不悄悄切换前端端口。
    for port in (8000, 3000):
        with socket.socket() as probe:
            try:
                probe.bind(("127.0.0.1", port))
            except OSError as exc:
                raise RuntimeError(
                    f"端口 {port} 已被占用，请在原来的终端停止服务后再试。"
                ) from exc
    run([sys.executable, "-c", "import uvicorn, alembic"], cwd=ROOT / "backend")


def docker_ready() -> bool:
    """限制单次检测时间，Docker Desktop 未就绪时不会无限等待。"""
    try:
        return (
            subprocess.run(
                ["docker", "info"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=5,
                check=False,
            ).returncode
            == 0
        )
    except subprocess.TimeoutExpired:
        return False


def prepare_database() -> None:
    """macOS 自动打开 Docker Desktop，并等待 Compose 数据库健康检查通过。"""
    if not docker_ready():
        if sys.platform != "darwin":
            raise RuntimeError("Docker 服务未运行，请先启动 Docker daemon。")
        announce("正在启动 Docker Desktop，最多等待 120 秒……")
        run(["open", "-a", "Docker"], timeout=15)
        deadline = time.monotonic() + 120
        while not docker_ready():
            if time.monotonic() >= deadline:
                raise RuntimeError("Docker 启动超时，请检查 Docker Desktop 窗口。")
            time.sleep(2)
    announce("[成功] Docker 服务已运行（docker info 检查通过）。")
    announce("启动 PostgreSQL，等待健康检查……")
    run(
        [*COMPOSE, "up", "-d", "--wait", "--wait-timeout", "120", "postgres"],
        timeout=240,
    )
    announce("[成功] PostgreSQL 容器已就绪（Compose 健康检查通过）。")
    announce("执行数据库迁移……")
    run([sys.executable, "-m", "alembic", "upgrade", "head"], cwd=ROOT / "backend")
    announce("[成功] 数据库迁移执行完成。")


def print_ready_summary() -> None:
    """仅在基础设施及两个 HTTP 入口检查通过后展示汇总，不代表模型 API 已验证。"""
    print(
        "\n========== 本地环境启动成功 ==========\n"
        "[成功] Docker   ：服务可用\n"
        "[成功] PostgreSQL：容器健康，数据库迁移完成\n"
        "[成功] 后端      ：/health 返回 HTTP 200\n"
        "[成功] 前端      ：页面返回 HTTP 200\n"
        "\n前端首页：http://127.0.0.1:3000/\n"
        "客户入口：http://127.0.0.1:3000/customer/login\n"
        "企业入口：http://127.0.0.1:3000/staff/login\n"
        "后端地址：http://127.0.0.1:8000\n"
        "接口文档：http://127.0.0.1:8000/docs\n"
        "健康检查：http://127.0.0.1:8000/health\n"
        f"\n后端日志：{ROOT / 'logs/backend.log'}\n"
        f"前端日志：{ROOT / 'logs/frontend.log'}\n"
        "\n以上为启动时的检查结果；模型 API 请通过实际聊天验证。\n"
        "请保持此终端运行。按 Ctrl+C 停止前后端，PostgreSQL 保持运行。\n"
        "======================================\n",
        flush=True,
    )


def stop_children(children: list[subprocess.Popen[bytes]]) -> None:
    """每个服务使用独立进程组，退出时一并回收 Uvicorn reload 子进程。"""
    for child in reversed(children):
        try:
            os.killpg(child.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    deadline = time.monotonic() + 10
    while (
        any(child.poll() is None for child in children) and time.monotonic() < deadline
    ):
        time.sleep(0.1)
    for child in children:
        try:
            os.killpg(child.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        child.wait()


def main() -> int:
    """前台管理服务，Ctrl+C 统一停止前后端，数据库容器继续保留。"""
    parser = argparse.ArgumentParser(
        description="一键启动 SupportDeskAgent 本地开发环境"
    )
    parser.add_argument(
        "--check", action="store_true", help="只检查依赖、配置和端口，不启动服务"
    )
    args = parser.parse_args()
    children: list[subprocess.Popen[bytes]] = []

    def interrupted(_signum: int, _frame: object) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, interrupted)
    try:
        preflight()
        if args.check:
            announce("启动前检查通过。")
            return 0
        prepare_database()
        # 日志写入已忽略的 logs/，前台只输出启动状态；重启时追加日志方便回查故障。
        log_directory = ROOT / "logs"
        log_directory.mkdir(exist_ok=True)
        services = [
            (
                "backend",
                ROOT / "backend",
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "app.main:app",
                    "--reload",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "8000",
                ],
            ),
            (
                "frontend",
                ROOT / "frontend",
                [
                    "node",
                    "node_modules/vite/bin/vite.js",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    "3000",
                    "--strictPort",
                ],
            ),
        ]
        for name, cwd, command in services:
            announce(
                f"正在启动{'后端' if name == 'backend' else '前端'}，等待 HTTP 检查……"
            )
            with (log_directory / f"{name}.log").open("ab") as log:
                children.append(
                    subprocess.Popen(
                        command,
                        cwd=cwd,
                        stdout=log,
                        stderr=subprocess.STDOUT,
                        start_new_session=True,
                    )
                )
        # 同时确认两个 HTTP 入口可用；不经过系统代理，避免本机 VPN 影响健康检查。
        opener = build_opener(ProxyHandler({}))
        pending = {
            "http://127.0.0.1:8000/health": "后端",
            "http://127.0.0.1:3000/": "前端",
        }
        deadline = time.monotonic() + 60
        while True:
            if any(child.poll() is not None for child in children):
                raise RuntimeError(
                    "前端或后端已退出，请查看 logs/backend.log 和 logs/frontend.log。"
                )
            for url in list(pending):
                try:
                    with opener.open(url, timeout=1) as response:
                        if response.status == 200:
                            name = pending.pop(url)
                            announce(f"[成功] {name}已就绪：{url}（HTTP 200）。")
                except (URLError, TimeoutError):
                    pass
            if not pending:
                break
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    f"{'、'.join(pending.values())}启动超时，未通过 HTTP 检查。"
                    f"请查看 {log_directory} 下的日志。"
                )
            time.sleep(0.5)
        print_ready_summary()
        while all(child.poll() is None for child in children):
            time.sleep(1)
        raise RuntimeError("服务意外退出，请查看 logs/ 下的日志。")
    except KeyboardInterrupt:
        announce("正在停止本次启动的前后端……")
        return 0
    except (RuntimeError, OSError, subprocess.SubprocessError) as exc:
        print(f"[启动失败] {exc}", file=sys.stderr)
        return 1
    finally:
        # 清理期间忽略重复中断，确保进程组完整退出。
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        stop_children(children)


if __name__ == "__main__":
    sys.exit(main())
