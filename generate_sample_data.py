# -*- coding: utf-8 -*-
"""
Sample Data Generator — Realistic PV Plant Logs with Injected Anomalies
========================================================================

Generates ~500 rows of simulated inverter log data for a 10kW solar
plant in Bogotá, Colombia. Includes realistic daily irradiance curves,
temperature patterns, and three types of injected anomalies:

  1. Soiling (gradual PR degradation over days 3-7)
  2. Clipping (flat power at high irradiance on day 4)
  3. Isolation fault (string voltage mismatch on day 6)

This script is NOT part of the production code — it generates the
sample_data/plant_log_2024.csv file used for demos and testing.

Usage:
    python generate_sample_data.py

Author: Miguel Ángel Mejía Sánchez
"""

import csv
import math
import random
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
OUTPUT_PATH = Path("sample_data/plant_log_2024.csv")
DAYS = 7
INTERVAL_MINUTES = 15
START_HOUR = 5   # 5:00 AM
END_HOUR = 19    # 7:00 PM
TZ_OFFSET = timezone(timedelta(hours=-5))  # UTC-5 (Colombia)

# Plant parameters
NOMINAL_POWER_W = 10000  # 10 kW
BASE_V_DC = 380.0
BASE_I_DC_MAX = 14.0

# Anomaly injection days (0-indexed)
SOILING_START_DAY = 2    # Days 3-7: gradual PR drop
CLIPPING_DAY = 3         # Day 4: power caps at high irradiance
ISOLATION_FAULT_DAY = 5  # Day 6: string voltage mismatch

random.seed(42)  # Reproducibility


def solar_irradiance(hour: float, day: int) -> float:
    """Simulate realistic bell-curve irradiance for Bogotá latitude (~4.7°N).

    Peak irradiance is ~1050 W/m² at solar noon (12:00-13:00).
    Includes random cloud events and daily variation.
    """
    if hour < 6.0 or hour > 18.0:
        return 0.0

    # Bell curve centered at 12:30
    solar_noon = 12.5
    spread = 3.5
    base_irr = 1050 * math.exp(-0.5 * ((hour - solar_noon) / spread) ** 2)

    # Daily variation (±5%)
    daily_factor = 1.0 + 0.05 * math.sin(day * 0.9)

    # Random cloud events (10% chance of 20-40% reduction)
    cloud = 1.0
    if random.random() < 0.10:
        cloud = random.uniform(0.60, 0.80)

    return max(0, base_irr * daily_factor * cloud + random.gauss(0, 10))


def heatsink_temp(hour: float, irradiance: float) -> float:
    """Simulate heatsink temperature based on irradiance and ambient temp.

    Bogotá ambient: ~14°C. Heatsink rises with power generation.
    """
    ambient = 14.0 + 5.0 * math.sin((hour - 6) / 12 * math.pi)  # 14-19°C
    thermal_rise = irradiance / 1000 * 35  # Up to ~35°C rise at full power
    return ambient + thermal_rise + random.gauss(0, 1.5)


def generate_row(ts: datetime, day: int, hour: float) -> dict:
    """Generate a single data row with realistic PV values."""
    irr = solar_irradiance(hour, day)
    temp = heatsink_temp(hour, irr)

    # DC voltages (strings)
    v_dc_1 = BASE_V_DC + random.gauss(0, 2.0) if irr > 20 else random.uniform(0, 5)
    v_dc_2 = BASE_V_DC + random.gauss(0, 2.0) if irr > 20 else random.uniform(0, 5)

    # DC current proportional to irradiance
    i_dc = (irr / 1000) * BASE_I_DC_MAX + random.gauss(0, 0.3) if irr > 20 else 0

    # AC power with typical inverter efficiency (~95%)
    efficiency = random.uniform(0.93, 0.97)
    p_dc = ((v_dc_1 + v_dc_2) / 2) * i_dc
    p_ac = p_dc * efficiency if p_dc > 0 else 0

    # Status code (normal)
    status = "0x00"

    # --- ANOMALY INJECTION ---

    # 1. Soiling: Gradually reduce effective irradiance from day 3 onward
    if day >= SOILING_START_DAY and irr > 50:
        soiling_factor = 1.0 - 0.012 * (day - SOILING_START_DAY + 1)
        p_ac *= soiling_factor

    # 2. Clipping: Cap AC power on day 4 during peak hours
    if day == CLIPPING_DAY and 10.5 <= hour <= 14.5:
        p_ac = min(p_ac, NOMINAL_POWER_W * 0.92)  # Clip at 92% of nominal

    # 3. Isolation fault: String 2 voltage drops on day 6 (10:00-13:00)
    if day == ISOLATION_FAULT_DAY and 10.0 <= hour <= 13.0:
        v_dc_2 *= 0.72  # 28% drop → ΔV > 15%
        status = "0x05"  # Isolation fault code

    # Random hardware errors (~1% chance)
    if random.random() < 0.01 and irr > 100:
        status = random.choice(["0x01", "0x02", "0x04", "0x07"])

    return {
        "timestamp": ts.isoformat(),
        "v_dc_string_1": round(v_dc_1, 2),
        "v_dc_string_2": round(v_dc_2, 2),
        "i_dc_total": round(max(0, i_dc), 2),
        "p_ac_output": round(max(0, p_ac), 1),
        "temp_heatsink": round(temp, 1),
        "irradiance_poa": round(max(0, irr), 1),
        "status_code": status,
    }


def main():
    """Generate the complete sample CSV file."""
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)

    fieldnames = [
        "timestamp",
        "v_dc_string_1",
        "v_dc_string_2",
        "i_dc_total",
        "p_ac_output",
        "temp_heatsink",
        "irradiance_poa",
        "status_code",
    ]

    rows = []
    base_date = datetime(2024, 3, 11, tzinfo=TZ_OFFSET)  # Monday

    for day in range(DAYS):
        current_date = base_date + timedelta(days=day)
        hour = START_HOUR

        while hour <= END_HOUR:
            ts = current_date.replace(
                hour=int(hour),
                minute=int((hour % 1) * 60),
                second=0,
            )
            row = generate_row(ts, day, hour)
            rows.append(row)
            hour += INTERVAL_MINUTES / 60  # 0.25 hour increments

    with open(OUTPUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)

    print(f"[OK] Generated {len(rows)} rows -> {OUTPUT_PATH}")
    print(f"   Period: {rows[0]['timestamp']} to {rows[-1]['timestamp']}")
    print(f"   Anomalies injected:")
    print(f"     - Soiling: days {SOILING_START_DAY + 1}-{DAYS}")
    print(f"     - Clipping: day {CLIPPING_DAY + 1}")
    print(f"     - Isolation fault: day {ISOLATION_FAULT_DAY + 1}")


if __name__ == "__main__":
    main()
