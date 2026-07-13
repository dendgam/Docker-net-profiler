# Docker Network Profiler — local

Интервал: **30 сек.**

Running: **3**, активных: **2**, без трафика: **1**, мёртвых/остановленных: **1**, умерли за интервал: **1**, реальных связей: **1**.

## Контейнеры

| Контейнер | Состояние | Статус Docker | IP | Трафик |
|---|---|---|---|---|
| `docker_profiler-receiver_b-1` | активен | running | `172.18.0.3` | ▼ 14.13 KB \| ▲ 38.73 KB |
| `docker_profiler-sender_a-1` | активен | running | `172.18.0.4` | ▼ 37.17 KB \| ▲ 13.58 KB |
| `docker_profiler-storage_c-1` | живой, нет трафика | running | `172.18.0.2` | ▼ 0.0 KB \| ▲ 0.0 KB |
| `docker_profiler-temp_dead-1` | мёртвый / остановлен | exited | `172.18.0.5` | ▼ 0.0 KB \| ▲ 0.0 KB |

## Связи

- `docker_profiler-sender_a-1` → `docker_profiler-receiver_b-1`: TCP:9000 socket
- `docker_profiler-receiver_b-1` — `docker_profiler-storage_c-1`: общая сеть `demo_net`, socket не найден
- `docker_profiler-sender_a-1` — `docker_profiler-storage_c-1`: общая сеть `demo_net`, socket не найден
