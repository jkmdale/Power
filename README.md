# Power — Home Energy Monitoring Dashboard

A self-hosted dashboard for whole-house energy use **plus** a breakdown of the big
appliances (spa pool, ducted heat pump, oven). Built for a Christchurch, NZ home, but
generic. Runs locally with **TimescaleDB + Grafana + a small Python ingester**, and
works **today with a built-in simulator** — no hardware required to try it.

> Full architecture rationale (hardware choice, security, DB design, pitfalls) lives in
> the design doc this repo was scaffolded from. This README is the run guide.

## Architecture

```
 Meter (Shelly / Emporia)         ┌──────────────┐      ┌──────────┐
   │  local API or cloud   ──────▶ │   ingester   │ ───▶ │ Timescale│ ◀── Grafana
   │  (or the simulator)           │  (Python)    │      │   DB     │     dashboards
                                   └──────────────┘      └──────────┘
```

- **ingester/** — async Python service. Picks a *source adapter* from `SOURCE`:
  `simulator` (default), `shelly_http`, `shelly_mqtt`, or `emporia`. Every adapter emits
  the same `Reading`, so swapping hardware never touches the DB or dashboards.
- **db/** — TimescaleDB schema: a `readings` hypertable, a `channels` map (which CT is
  which appliance), 1-minute/1-day continuous aggregates, compression + retention, and a
  `house_power_1m` view that derives **rest of house = mains − appliances**.
- **grafana/** — provisioned datasource + a `Home Energy` dashboard (whole-house now,
  stacked power by appliance, daily kWh).

## Metering strategy (the "better way" for whole-house)

Don't clamp every breaker, and don't trust single-meter auto-detect. Use a **hybrid**:
1 CT on the **mains** (whole house) + 1 CT each on the **spa, heat pump, oven**. The
unmetered remainder ("rest of house") is computed in SQL by subtraction. Four CTs gives
you the whole-house total, the three big loads, and the baseload.

## Quick start (no hardware)

```bash
cp .env.example .env          # defaults already use SOURCE=simulator
docker compose up -d --build  # starts timescaledb + ingester + grafana
docker compose logs -f ingester   # watch simulated readings flow in
```

Then open **http://localhost:3000** (login `admin` / `admin`) → dashboard **Home Energy**.
Within a minute you'll see whole-house power, the per-appliance stack, and daily kWh.

Check data is landing:
```bash
docker compose exec timescaledb psql -U energy -d energy \
  -c "SELECT count(*) FROM readings;" \
  -c "SELECT * FROM house_power_1m ORDER BY bucket DESC LIMIT 3;"
```

## No hardware: use your existing Genesis data

Already have usage data from the Genesis app? Import it for whole-house trends and cost —
no hardware needed. Export "My Daily Usage" as CSV, then:

```bash
DATABASE_URL=postgresql://energy:energy@localhost:5432/energy \
  python tools/import_genesis.py path/to/genesis-export.csv
```

Open the **Whole House (Genesis data)** dashboard in Grafana. The importer auto-detects the
export shape — **daily** (date / usage / dollars / type → `meter_daily_usage`) or an
**interval/hourly** export (datetime + kWh → `meter_hourly`) — and cleans values like
`"34.64 kWh"` and `"$10.99"` for you. Daily exports include Genesis's **actual** dollars, so
cost is exact, not estimated.

> **Important — this is whole-house only.** A single total per day *cannot* be split into
> spa vs heat pump vs oven (appliance disaggregation needs per-**second** data). The
> dashboard's appliance table is an **estimate** from the `appliance_profiles` you enter,
> with an explicit "Unexplained" remainder. For *accurate* per-appliance numbers you need CT
> clamps — see **[docs/hardware-install.md](docs/hardware-install.md)**. Edit the
> `appliance_profiles` table (seeded in `db/init/02_retailer.sql`) to match your gear.

## Connecting real hardware

The minimum accurate setup and full wiring/commissioning steps are in
**[docs/hardware-install.md](docs/hardware-install.md)**. In short: edit `.env`, set
`SOURCE`, then `docker compose up -d` again.

### Shelly Pro 3EM (recommended — local, real-time, private)
```
SOURCE=shelly_http        # or shelly_mqtt for push (lowest latency)
SHELLY_HOST=192.168.1.50
SHELLY_PASSWORD=...        # if you set device auth (recommended)
DEVICE_ID=shelly-appliances
```
- The Pro 3EM has 3 CTs (phases a/b/c → channels 0/1/2). **Whole house + 3 appliances =
  4 CTs**, so run a **second** ingester for the mains device with a different `DEVICE_ID`
  and `SHELLY_HOST` (rows key on `(device_id, channel)`, so they coexist).
- Update the `channels` table to match your real CT placement and roles:
  ```sql
  INSERT INTO channels (device_id, channel, appliance, role) VALUES
    ('shelly-mains',      0, 'Mains (whole house)', 'mains'),
    ('shelly-appliances', 0, 'Spa Pool',            'appliance'),
    ('shelly-appliances', 1, 'Ducted Heat Pump',    'appliance'),
    ('shelly-appliances', 2, 'Oven',                'appliance')
  ON CONFLICT (device_id, channel) DO UPDATE
    SET appliance = EXCLUDED.appliance, role = EXCLUDED.role;
  ```
- **Security:** put the Shelly on an IoT VLAN, block its internet access, enable device
  auth, disable Shelly Cloud, give it a static DHCP lease. For remote viewing use
  Tailscale/WireGuard — never a port-forward.

### Emporia Vue (cloud, unofficial)
```
SOURCE=emporia
EMPORIA_EMAIL=you@example.com
EMPORIA_PASSWORD=...
EMPORIA_POLL_INTERVAL=60   # don't poll faster; data is ~1/min
```
Uses the unofficial `pyemvue` library against Emporia's cloud. Convenient and cheap for
many circuits, but ~1-minute latency and can break if Emporia changes their API.

## Dev without Docker

Run a local Postgres/TimescaleDB, apply `db/init/01_schema.sql`, then:
```bash
pip install -r ingester/requirements.txt
DATABASE_URL=postgresql://energy:energy@localhost:5432/energy python tools/simulate.py
```

## Layout

```
docker-compose.yml          # timescaledb + ingester + grafana
db/init/01_schema.sql       # hypertable, channels, aggregates, policies, views
ingester/
  main.py                   # adapter factory + poll/stream loop
  config.py  store.py       # env config; batched asyncpg writes
  adapters/                 # base + simulator / shelly_http / shelly_mqtt / emporia
grafana/provisioning/       # datasource + Home Energy dashboard
tools/simulate.py           # seed data without Docker
```

## Notes / next steps
- All timestamps are stored **UTC**; Grafana renders in `Pacific/Auckland`.
- NZ cost tracking: add a `tariffs(start, end, c_per_kwh)` table and join on it for $/day.
- Switchboard CT installation must be done by a **registered NZ electrician**.
