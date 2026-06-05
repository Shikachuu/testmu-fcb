"""FCB — FOCUS schema based multi-cloud cost browsing CLI."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import click
import jsonschema
import pandas as pd
import yaml

SCHEMA_PATH = Path(__file__).parent / "fcb.schema.json"

PRICE_FIELD = "BilledCost"
CONSUMPTION_FIELD = "ConsumedQuantity"
RESOURCE_ID_FIELD = "ResourceId"

Row = dict[str, Any]
PipelineStep = Callable[[list[Row]], list[Row]]


def load_schema() -> dict[str, Any]:
    """Load the JSON schema bundled alongside this module."""
    with SCHEMA_PATH.open(encoding="utf-8") as fh:
        return json.load(fh)


def load_config(path: Path) -> dict[str, Any]:
    """Parse a JSON or YAML config file from disk."""
    text = path.read_text(encoding="utf-8")
    if path.suffix.lower() in {".yaml", ".yml"}:
        loaded = yaml.safe_load(text)
    elif path.suffix.lower() == ".json":
        loaded = json.loads(text)
    else:
        msg = f"Unsupported config file extension: {path.suffix!r} (expected .json/.yaml/.yml)"
        raise ValueError(msg)
    if not isinstance(loaded, dict):
        msg = "Config root must be an object."
        raise TypeError(msg)
    return loaded


def validate_config(config: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    """Validate the config against the JSON schema.

    `$schema` keys are stripped before validation because they only exist for IDE support.
    Returns the cleaned config.
    """
    cleaned = {k: v for k, v in config.items() if k != "$schema"}
    jsonschema.validate(instance=cleaned, schema=schema)
    return cleaned


def load_parquet_files(paths: list[str]) -> list[Row]:
    """Read and concatenate all parquet files into a list of row dicts."""
    if not paths:
        return []
    frames = [pd.read_parquet(p) for p in paths]
    merged = pd.concat(frames, ignore_index=True)
    return merged.to_dict(orient="records")


def search_rows(rows: list[Row], field: str, value: str) -> list[Row]:
    """Keep rows whose `field` equals `value` (compared as strings)."""
    return [r for r in rows if field in r and str(r[field]) == value]


def aggregate_by_resource_id(rows: list[Row]) -> list[Row]:
    """Group rows by ResourceId and sum the numeric columns within each group.

    Non-numeric columns are collapsed to the first non-null value in the group.
    Rows without a ResourceId are grouped together under the missing-value key.
    """
    if not rows:
        return []
    df = pd.DataFrame(rows)
    if RESOURCE_ID_FIELD not in df.columns:
        return rows

    numeric_cols = df.select_dtypes(include="number").columns.tolist()
    other_cols = [c for c in df.columns if c not in numeric_cols and c != RESOURCE_ID_FIELD]
    agg_spec: dict[str, str] = dict.fromkeys(numeric_cols, "sum")
    for c in other_cols:
        agg_spec[c] = "first"

    grouped = df.groupby(RESOURCE_ID_FIELD, dropna=False, sort=False).agg(agg_spec).reset_index()
    return grouped.to_dict(orient="records")


def _numeric_key(field: str) -> Callable[[Row], float]:
    def key(row: Row) -> float:
        v = row.get(field)
        if v is None:
            return 0.0
        try:
            f = float(v)
        except TypeError, ValueError:
            return 0.0
        if f != f:  # NaN check without importing math
            return 0.0
        return f

    return key


def order_by_price_asc(rows: list[Row]) -> list[Row]:
    """Order rows by BilledCost ascending."""
    return sorted(rows, key=_numeric_key(PRICE_FIELD))


def order_by_price_desc(rows: list[Row]) -> list[Row]:
    """Order rows by BilledCost descending."""
    return sorted(rows, key=_numeric_key(PRICE_FIELD), reverse=True)


def order_by_consumption(rows: list[Row]) -> list[Row]:
    """Order rows by ConsumedQuantity descending."""
    return sorted(rows, key=_numeric_key(CONSUMPTION_FIELD), reverse=True)


def exclude_fields(rows: list[Row], fields: list[str]) -> list[Row]:
    """Drop the given fields from every row."""
    drop = set(fields)
    return [{k: v for k, v in r.items() if k not in drop} for r in rows]


def include_fields(rows: list[Row], fields: list[str]) -> list[Row]:
    """Keep only the given fields in every row."""
    keep = set(fields)
    return [{k: v for k, v in r.items() if k in keep} for r in rows]


_ORDER_FUNCS: dict[str, PipelineStep] = {
    "price-asc": order_by_price_asc,
    "price-desc": order_by_price_desc,
    "consumption": order_by_consumption,
}


def build_pipeline(
    *,
    search: tuple[str, str] | None,
    aggregate: bool,
    order: str | None,
    included: list[str] | None,
    excluded: list[str] | None,
) -> list[PipelineStep]:
    """Build the ordered list of pipeline steps that match the CLI flags."""
    steps: list[PipelineStep] = []
    if search is not None:
        field, value = search
        steps.append(lambda rows: search_rows(rows, field, value))
    if aggregate:
        steps.append(aggregate_by_resource_id)
    if order is not None:
        steps.append(_ORDER_FUNCS[order])
    if included:
        steps.append(lambda rows: include_fields(rows, included))
    elif excluded:
        steps.append(lambda rows: exclude_fields(rows, excluded))
    return steps


def run_pipeline(rows: list[Row], steps: list[PipelineStep]) -> list[Row]:
    """Apply each pipeline step to the rows in order."""
    for step in steps:
        rows = step(rows)
    return rows


def _json_default(value: Any) -> Any:
    """Convert non-JSON-native scalars (timestamps, numpy types) to plain values."""
    if hasattr(value, "isoformat"):
        return value.isoformat()
    if hasattr(value, "item"):
        try:
            return value.item()
        except ValueError, TypeError:
            return str(value)
    return str(value)


def to_json(rows: list[Row]) -> str:
    """Serialize rows to a pretty-printed JSON array, replacing NaN with null."""
    if not rows:
        return "[]"
    df = pd.DataFrame(rows)
    cleaned = df.astype(object).where(df.notna(), None)
    return json.dumps(cleaned.to_dict(orient="records"), default=_json_default, indent=2)


def execute(
    config: dict[str, Any],
    *,
    search: tuple[str, str] | None,
    aggregate: bool,
    order: str | None,
) -> list[Row]:
    """Orchestrate the full read-and-transform flow for a validated config."""
    rows = load_parquet_files(config["source_files"])
    steps = build_pipeline(
        search=search,
        aggregate=aggregate,
        order=order,
        included=config.get("included_fields"),
        excluded=config.get("excluded_fields"),
    )
    return run_pipeline(rows, steps)


@click.command()
@click.option(
    "-s",
    "--search",
    nargs=2,
    type=str,
    default=None,
    metavar="FIELD VALUE",
    help="Keep only rows where FIELD equals VALUE.",
)
@click.option(
    "-f",
    "--file",
    "config_file",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    required=True,
    help="Path to a JSON or YAML config file.",
)
@click.option(
    "-o",
    "--order",
    type=click.Choice(["price-asc", "price-desc", "consumption"]),
    default=None,
    help="Order the rows by price (asc/desc) or consumption (desc).",
)
@click.option(
    "-a",
    "--aggregate",
    is_flag=True,
    default=False,
    help="Aggregate rows by ResourceId, summing numeric fields.",
)
def cli(
    search: tuple[str, str] | None,
    config_file: Path,
    order: str | None,
    aggregate: bool,
) -> None:
    """Browse FOCUS-schema cloud cost data from parquet exports."""
    raw_config = load_config(config_file)
    schema = load_schema()
    config = validate_config(raw_config, schema)
    search_arg = search if search else None
    result = execute(config, search=search_arg, aggregate=aggregate, order=order)
    click.echo(to_json(result))


if __name__ == "__main__":
    cli()
