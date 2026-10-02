#!/usr/bin/env python3
"""Gráfico de líneas: cotización del dólar en Bolivia (fuente: BCB)."""

from __future__ import annotations

import csv
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

import matplotlib.dates as mdates
import matplotlib.pyplot as plt

BCB_URL = "https://indicadores.bcb.gob.bo/ServiciosBCB/indicadores"
DATA_CSV = Path(__file__).with_name("cotizacion_dolar_bolivia.csv")
CHART_PNG = Path(__file__).with_name("cotizacion_dolar_bolivia.png")

# codMoneda BCB: 34 = USD compra, 35 = USD venta (tipos de cambio oficiales/referenciales)
MONEDAS = {
    "compra": 34,
    "venta": 35,
}


def _parse_valor(xml_bytes: bytes) -> float | None:
    root = ET.fromstring(xml_bytes)
    data: dict[str, str] = {}
    for node in root.iter():
        if not node.tag.endswith("return"):
            continue
        key = value = None
        for child in node:
            tag = child.tag.split("}")[-1]
            if tag == "codDato":
                key = child.text
            elif tag == "dato":
                value = child.text
        if key:
            data[key] = value or ""
    if data.get("CodError") == "0" and data.get("Valor"):
        return float(data["Valor"])
    return None


def fetch_rate(cod_moneda: int, day: date) -> float | None:
    fecha = day.strftime("%d/%m/%Y")
    body = f"""<?xml version="1.0" encoding="UTF-8"?>
<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/" xmlns:ws="http://ws.bcb.gob.bo">
  <soapenv:Body>
    <ws:obtenerIndicador>
      <codIndicador>1</codIndicador>
      <codMoneda>{cod_moneda}</codMoneda>
      <fecha>{fecha}</fecha>
    </ws:obtenerIndicador>
  </soapenv:Body>
</soapenv:Envelope>"""
    req = Request(
        BCB_URL,
        data=body.encode("utf-8"),
        headers={"Content-Type": "text/xml; charset=utf-8"},
    )
    with urlopen(req, timeout=45) as resp:
        return _parse_valor(resp.read())


def daterange(start: date, end: date):
    current = start
    while current <= end:
        yield current
        current += timedelta(days=1)


def load_or_fetch(start: date, end: date) -> list[dict]:
    rows: list[dict] = []
    if DATA_CSV.exists():
        with DATA_CSV.open(newline="", encoding="utf-8") as fh:
            reader = csv.DictReader(fh)
            for row in reader:
                rows.append(row)
        last = rows[-1]["fecha"] if rows else None
        if last:
            start = max(start, datetime.strptime(last, "%Y-%m-%d").date() + timedelta(days=1))

    tasks = []
    with ThreadPoolExecutor(max_workers=12) as pool:
        for day in daterange(start, end):
            for label, cod in MONEDAS.items():
                tasks.append((day, label, pool.submit(fetch_rate, cod, day)))

        pending_by_day: dict[date, dict] = {}
        for day, label, future in tasks:
            pending_by_day.setdefault(day, {"fecha": day.isoformat()})
            pending_by_day[day][label] = future

        for day in sorted(pending_by_day):
            record = pending_by_day[day]
            for label in MONEDAS:
                record[label] = record[label].result()
            rows.append(
                {
                    "fecha": record["fecha"],
                    "compra": record["compra"] if record["compra"] is not None else "",
                    "venta": record["venta"] if record["venta"] is not None else "",
                }
            )

    with DATA_CSV.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=["fecha", "compra", "venta"])
        writer.writeheader()
        writer.writerows(rows)
    return rows


def plot(rows: list[dict]) -> None:
    dates: list[datetime] = []
    compra: list[float | None] = []
    venta: list[float | None] = []

    for row in rows:
        dates.append(datetime.strptime(row["fecha"], "%Y-%m-%d"))
        compra.append(float(row["compra"]) if row["compra"] else None)
        venta.append(float(row["venta"]) if row["venta"] else None)

    plt.style.use("seaborn-v0_8-whitegrid")
    fig, ax = plt.subplots(figsize=(12, 6), dpi=120)

    ax.plot(dates, compra, color="#1f77b4", linewidth=2, label="Compra (BOB por USD)")

    venta_dates = [d for d, v in zip(dates, venta) if v is not None]
    venta_vals = [v for v in venta if v is not None]
    if venta_vals:
        ax.plot(
            venta_dates,
            venta_vals,
            color="#d62728",
            linewidth=2,
            label="Venta (BOB por USD)",
        )

    ax.set_title(
        "Cotización del dólar estadounidense en Bolivia\n"
        "Fuente: Banco Central de Bolivia (BCB)",
        fontsize=14,
        fontweight="bold",
    )
    ax.set_xlabel("Fecha")
    ax.set_ylabel("Bolivianos (BOB) por 1 USD")
    ax.legend(loc="upper left")
    ax.xaxis.set_major_locator(mdates.MonthLocator())
    ax.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    fig.autofmt_xdate()
    ax.set_xlim(dates[0], dates[-1])
    ax.grid(True, alpha=0.35)

    fig.tight_layout()
    fig.savefig(CHART_PNG, bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    # Publicación referencial diaria desde dic-2025 (comunicado BCB CP56/2025).
    start = date(2025, 12, 1)
    end = date.today()
    rows = load_or_fetch(start, end)
    plot(rows)
    print(f"Datos: {DATA_CSV}")
    print(f"Gráfico: {CHART_PNG}")


if __name__ == "__main__":
    main()
