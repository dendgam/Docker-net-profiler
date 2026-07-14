"""
CLI для простого Docker Network Profiler
"""

from __future__ import annotations

import argparse
import os
import sys

from analyzer import analyze_data
from collector import collect_containers, collect_traffic, get_docker_client
from monitor import calculate_traffic_delta, collect_interval, get_host_info
from reporter import generate_reports


def _demo_container(name: str, ip: str, status: str = "running"):
    return {
        "id": name,
        "short_id": name[:12],
        "name": name,
        "image": "demo",
        "status": status,
        "running": status == "running",
        "ip": ip,
        "networks": ["demo_net"],
        "network_details": {"demo_net": {"ip": ip, "ipv4": ip, "ipv6": ""}},
        "started_at": "demo",
        "finished_at": "demo" if status != "running" else "",
        "exit_code": 0 if status != "running" else None,
    }


def run_demo(out_prefix: str, stand: str) -> None:
    """Демо без Docker"""
    start = [
        _demo_container("docker_profiler-receiver_b-1", "172.18.0.3"),
        _demo_container("docker_profiler-sender_a-1", "172.18.0.4"),
        _demo_container("docker_profiler-storage_c-1", "172.18.0.2"),
        _demo_container("docker_profiler-temp_dead-1", "172.18.0.5"),
    ]
    end = [
        _demo_container("docker_profiler-receiver_b-1", "172.18.0.3"),
        _demo_container("docker_profiler-sender_a-1", "172.18.0.4"),
        _demo_container("docker_profiler-storage_c-1", "172.18.0.2"),
        _demo_container("docker_profiler-temp_dead-1", "172.18.0.5", "exited"),
    ]
    traffic = {
        "docker_profiler-receiver_b-1": {"rx_kb": 14.13, "tx_kb": 38.73, "total_kb": 52.86},
        "docker_profiler-sender_a-1": {"rx_kb": 37.17, "tx_kb": 13.58, "total_kb": 50.75},
        "docker_profiler-storage_c-1": {"rx_kb": 0.0, "tx_kb": 0.0, "total_kb": 0.0},
        "docker_profiler-temp_dead-1": {"rx_kb": 0.0, "tx_kb": 0.0, "total_kb": 0.0},
    }
    sockets = {
        "connections": [
            {
                "container_id": "docker_profiler-sender_a-1",
                "container": "docker_profiler-sender_a-1",
                "protocol": "TCP",
                "state": "ESTABLISHED",
                "local_ip": "172.18.0.4",
                "local_port": 49152,
                "remote_ip": "172.18.0.3",
                "remote_port": 9000,
            }
        ],
        "errors": [],
    }

    data = analyze_data(start, end, traffic, sockets, 30, stand, {"cpu_percent": 0.0, "ram_percent": 0.0})
    generate_reports(data, out_prefix)
    print(f"Готово: {out_prefix}.html / {out_prefix}.json / {out_prefix}.md")


def run_profiler(args: argparse.Namespace) -> None:
    client = get_docker_client()

    print(f"=== Docker Network Profiler: {args.time} сек. ===")
    print("[1/5] Начальный снимок контейнеров и трафика...")
    start_containers = collect_containers(client)
    start_traffic = collect_traffic(client)

    print(
        f"[2/5] Мониторим контейнеры {args.time} сек. "
        f"с шагом {args.sample_interval} сек..."
    )

    last_traffic, socket_scan = collect_interval(
        client=client,
        seconds=args.time,
        sample_interval=args.sample_interval,
        scan_sockets=not args.no_socket_scan,
    )

    print("[3/5] Конечный снимок контейнеров...")
    end_containers = collect_containers(client)

    # Последний контрольный снимок
    # Если контейнер ещё работает, обновляем его счётчики
    end_traffic = collect_traffic(client)
    last_traffic.update(end_traffic)

    traffic_delta = calculate_traffic_delta(
        start=start_traffic,
        end=last_traffic,
    )

    print("[4/5] Socket-связи собраны за весь интервал...")

    print("[5/5] Анализ и отчёты...")
    data = analyze_data(
        start_containers=start_containers,
        end_containers=end_containers,
        traffic_delta=traffic_delta,
        socket_scan=socket_scan,
        interval_seconds=args.time,
        stand_name=args.stand,
        host_info=get_host_info(),
    )
    generate_reports(data, args.out)

    summary = data["summary"]
    print(
        "Готово: "
        f"running={summary.get('running', 0)}, "
        f"активных={summary['alive']}, "
        f"без трафика={summary['inactive']}, "
        f"мёртвых/остановленных={summary['dead']}, "
        f"связей={summary['actual_links']}"
    )
    print(f"Отчёты: {args.out}.html / {args.out}.json / {args.out}.md")


def main() -> None:
    parser = argparse.ArgumentParser(description="Docker Network Profiler")
    parser.add_argument("--time", type=int, default=30, help="интервал мониторинга в секундах")
    parser.add_argument("--sample-interval", type=float, default=1.0, help="частота сбора трафика и сокетов в секундах")
    parser.add_argument("--out", default="reports/report", help="путь без расширения для отчётов")
    parser.add_argument("--stand", default="local", help="название стенда")
    parser.add_argument("--demo", action="store_true", help="создать демо-отчёт без Docker")
    parser.add_argument("--no-socket-scan", action="store_true", help="не читать /proc/net/* внутри контейнеров")
    args = parser.parse_args()

    if args.time < 0:
        parser.error("--time не может быть меньше 0")

    if args.sample_interval <= 0:
        parser.error("--sample-interval должен быть больше 0")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)

    try:
        if args.demo:
            run_demo(args.out, args.stand)
        else:
            run_profiler(args)
    except Exception as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        print("Проверьте Docker Desktop и зависимости: pip install -r requirements.txt", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
