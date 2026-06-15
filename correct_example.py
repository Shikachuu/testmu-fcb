"""fcb — browse cloud costs in FOCUS-schema parquet exports."""

import json
from pathlib import Path
from typing import Any

import click
import pandas as pd
import yaml
from jsonschema import validate

PRICE_FIELD = "BilledCost"
CONSUMPTION_FIELD = "ConsumedQuantity"
RESOURCE_FIELD = "ResourceId"

ORDERINGS = ("price-asc", "price-desc", "consumption")
SCHEMA_PATH = Path(__file__).with_name("fcb.schema.json")


def load_schema() -> dict[str, Any]:
    """Load the JSON Schema bundled alongside this module."""
    return json.loads(SCHEMA_PATH.read_text())


def load_config(path: str) -> dict[str, Any]:
    """Read a JSON or YAML config file and validate it against the schema.

    The ``$schema`` key (an IDE-only hint in JSON configs) is stripped before
    validation.

    Args:
        path: Path to a ``.json``, ``.yaml`` or ``.yml`` config file.

    Returns:
        The parsed, schema-validated configuration object.

    Raises:
        ValueError: If the file extension is not supported.
    """
    p = Path(path)
    ext = p.suffix.lower()
    text = p.read_text()
    if ext == ".json":
        config = json.loads(text)
    elif ext in (".yaml", ".yml"):
        config = yaml.safe_load(text)
    else:
        msg = f"unsupported config extension: {ext}"
        raise ValueError(msg)

    config.pop("$schema", None)
    validate(instance=config, schema=load_schema())
    return config


def read_sources(source_files: list[str]) -> pd.DataFrame:
    """Read and concatenate all parquet source files into one frame."""
    frames = [pd.read_parquet(f) for f in source_files]
    return pd.concat(frames, ignore_index=True)


def search(frame: pd.DataFrame, field: str, value: str) -> pd.DataFrame:
    """Return only the rows whose ``field`` equals ``value``."""
    return frame[frame[field] == value]


def aggregate_by_resource(frame: pd.DataFrame) -> pd.DataFrame:
    """Sum every numeric column, grouped by resource id."""
    numeric = frame.select_dtypes("number").copy()
    numeric[RESOURCE_FIELD] = frame[RESOURCE_FIELD]
    return numeric.groupby(RESOURCE_FIELD, as_index=False).sum()


def _order_by(frame: pd.DataFrame, field: str, *, ascending: bool) -> pd.DataFrame:
    """Sort ``frame`` by ``field`` in the requested direction."""
    return frame.sort_values(by=field, ascending=ascending)


def order_price_asc(frame: pd.DataFrame) -> pd.DataFrame:
    """Order rows by BilledCost, cheapest first."""
    return _order_by(frame, PRICE_FIELD, ascending=True)


def order_price_desc(frame: pd.DataFrame) -> pd.DataFrame:
    """Order rows by BilledCost, most expensive first."""
    return _order_by(frame, PRICE_FIELD, ascending=False)


def order_consumption(frame: pd.DataFrame) -> pd.DataFrame:
    """Order rows by consumed quantity, highest first."""
    return _order_by(frame, CONSUMPTION_FIELD, ascending=False)


def exclude_fields(frame: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    """Drop the named fields, keeping every other column."""
    return frame.drop(columns=list(fields))


def include_fields(frame: pd.DataFrame, fields: list[str]) -> pd.DataFrame:
    """Keep only the named fields, dropping every other column."""
    return frame[list(fields)]


def run_pipeline(
    frame: pd.DataFrame,
    search_term: tuple[str, str] | None,
    order: str | None,
    *,
    aggregate: bool,
    excluded: list[str] | None,
    included: list[str] | None,
) -> pd.DataFrame:
    """Apply search, aggregation, ordering and scrubbing to the data.

    Args:
        frame: The merged cost data.
        search_term: Optional ``(field, value)`` equality filter.
        order: One of :data:`ORDERINGS`, or ``None`` to keep input order.
        aggregate: Whether to aggregate rows by resource id.
        excluded: Fields to drop (mutually exclusive with ``included``).
        included: Fields to keep (mutually exclusive with ``excluded``).

    Returns:
        The transformed frame.
    """
    if search_term is not None:
        field, value = search_term
        frame = search(frame, field, value)

    if aggregate:
        frame = aggregate_by_resource(frame)

    orderers = {
        "price-asc": order_price_asc,
        "price-desc": order_price_desc,
        "consumption": order_consumption,
    }
    if order is not None:
        frame = orderers[order](frame)

    if excluded:
        frame = exclude_fields(frame, excluded)
    elif included:
        frame = include_fields(frame, included)

    return frame


def to_json(frame: pd.DataFrame) -> str:
    """Serialise the result rows to an indented JSON string."""
    records = frame.to_dict(orient="records")
    return json.dumps(records, indent=2, default=str)


@click.command()
@click.option(
    "-s",
    "--search",
    "search_term",
    nargs=2,
    type=str,
    default=None,
    help="Keep only rows where FIELD equals VALUE.",
)
@click.option(
    "-f",
    "--file",
    "config_file",
    required=True,
    help="Path to the JSON or YAML config file.",
)
@click.option(
    "-o",
    "--order",
    type=click.Choice(ORDERINGS),
    default=None,
    help="Ordering applied to the rows.",
)
@click.option(
    "-a",
    "--aggregate",
    is_flag=True,
    default=False,
    help="Aggregate rows by ResourceId.",
)
def cli(
    search_term: tuple[str, str] | None,
    config_file: str,
    order: str | None,
    *,
    aggregate: bool,
) -> None:
    """Browse cloud costs in FOCUS-schema parquet exports."""
    config = load_config(config_file)
    source_files = config["source_files"]
    excluded = config.get("excluded_fields")
    included = config.get("included_fields")

    frame = read_sources(source_files)
    result = run_pipeline(
        frame,
        search_term or None,
        order,
        aggregate=aggregate,
        excluded=excluded,
        included=included,
    )
    click.echo(to_json(result))


if __name__ == "__main__":
    cli()
