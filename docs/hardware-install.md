# Hardware Install Sheet — accurate per-appliance monitoring

This is the **only** way to accurately know what's using your power. Hourly retailer data
(Genesis) is whole-house only and cannot be split into appliances accurately — measuring
each circuit with a current transformer (CT) clamp is required.

> **Safety / legal (NZ):** All switchboard work and CT installation must be done by a
> **registered NZ electrician**. Do not open the switchboard yourself. CTs clip around a
> live conductor; the electrician confirms supply type and CT orientation.

## Minimum kit (spa + heat pump + oven)

| Item | Qty | Notes |
|---|---|---|
| **Shelly Pro 3EM** | 1 | 3 measurement channels; DIN-rail mount in the switchboard. ~NZ$140–180. |
| **CT clamp** (rating to suit each circuit) | 3 | One per appliance circuit. The 120 A clamps shipped with the Pro 3EM suit most domestic circuits; an electrician confirms sizing. |
| (Optional) 2nd Shelly Pro 3EM **or** Shelly EM | 1 | A 4th CT on the **mains incomer** adds whole-house total + derived "rest of house". |

Both Shelly Pro 3EM and the CTs are **AS/NZS compliant** and stocked by NZ retailers
(e.g. Lykalyte, Auto Light). Works on NZ 230 V single-phase — the 3 channels just measure
three separate circuits.

## Which CT on which circuit

Have the electrician clip:

| Channel (phase) | Circuit | `channels` mapping |
|---|---|---|
| a → channel 0 | Spa pool supply | `appliance` |
| b → channel 1 | Ducted heat pump supply | `appliance` |
| c → channel 2 | Oven / range supply | `appliance` |
| (2nd device) ch 0 | Mains incomer | `mains` |

Arrow direction matters: if a channel reads **negative** power, the CT is on backwards —
the electrician flips it (or fix in software by negating, but flipping is cleaner).

## Wiring / commissioning checklist

- [ ] Shelly Pro 3EM mounted on DIN rail, powered (L/N), Wi-Fi joined to your **IoT VLAN**.
- [ ] Each CT clipped around the correct **single** circuit conductor, arrow toward the load.
- [ ] Give the Shelly a **static DHCP lease**; note its IP.
- [ ] In the Shelly web UI: set a **device password**, **disable Shelly Cloud**, (optional)
      enable MQTT pointing at your local broker.
- [ ] Block the Shelly from outbound internet at the router (it only needs the LAN).

## Connect it to the dashboard (no code changes)

1. In `.env`:
   ```
   SOURCE=shelly_http          # or shelly_mqtt for push
   SHELLY_HOST=<static-ip>
   SHELLY_PASSWORD=<device-password>
   DEVICE_ID=shelly-appliances
   ```
   For the mains device, run a **second** ingester instance with `DEVICE_ID=shelly-mains`
   and its own `SHELLY_HOST`.

2. Seed the channel map to match the physical clamps:
   ```sql
   INSERT INTO channels (device_id, channel, appliance, role) VALUES
     ('shelly-appliances', 0, 'Spa Pool',            'appliance'),
     ('shelly-appliances', 1, 'Ducted Heat Pump',    'appliance'),
     ('shelly-appliances', 2, 'Oven',                'appliance'),
     ('shelly-mains',      0, 'Mains (whole house)', 'mains')
   ON CONFLICT (device_id, channel) DO UPDATE
     SET appliance = EXCLUDED.appliance, role = EXCLUDED.role;
   ```

3. `docker compose up -d`, then open the **Home Energy** dashboard. You now get **accurate,
   real-time** per-appliance watts and daily kWh — the thing hourly data can't give you.

## Verify each clamp reads the right appliance

Turn each appliance on/off in turn and watch its channel on the dashboard respond. If the
spa turns on but the "Spa Pool" line doesn't move (and a different one does), the CTs are
on the wrong circuits — have the electrician swap them, or just relabel the `channels` rows.
