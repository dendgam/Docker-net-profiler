# Docker Network Profiler — local

Интервал: **30 сек.**

Running: **3**, активных: **2**, без трафика: **1**, мёртвых/остановленных: **1**, умерли за интервал: **0**, реальных связей: **1**.

## Контейнеры

| Контейнер | Состояние | Статус Docker | IP | Трафик |
|---|---|---|---|---|
| `profiler_client` | активен | running | `172.31.60.3` | ▼ 1.57 KB \| ▲ 3.05 KB |
| `profiler_idle` | живой, нет трафика | running | `172.31.60.4` | ▼ 0.0 KB \| ▲ 0.0 KB |
| `profiler_server` | активен | running | `172.31.60.2` | ▼ 3.05 KB \| ▲ 1.57 KB |
| `profiler_stopped` | мёртвый / остановлен | exited | `N/A` | ▼ 0.0 KB \| ▲ 0.0 KB |

## Связи

- `profiler_client` → `profiler_server`: TCP:9000 socket
- `profiler_client` — `profiler_idle`: общая сеть `desktop_profiler_demo_net`, socket не найден
- `profiler_idle` — `profiler_server`: общая сеть `desktop_profiler_demo_net`, socket не найден
