import json
from pathlib import Path

import click
import pandas as pd
import yaml

PRICE_FIELD = "BilledCost"
CONSUMPTION_FIELD = "ConsumedQuantity"
RESOURCE_FIELD = "ResourceId"


def load_config(path):
    p = Path(path)
    ext = p.suffix.lower()  
    text = p.read_text()
    if ext == ".json":
        return json.loads(text)
    if ext in (".yaml", ".yml"):
        return yaml.safe_load(text)
    raise ValueError("unsupported config extension: %s" % ext)   


def read_sources(source_files):
    frames = [pd.read_parquet(f) for f in source_files]
    return pd.concat(frames, ignore_index=True)


def search(frame, field, value):
    return frame[frame[field] == value]


def aggregate_by_resource(frame):
    numeric = frame.select_dtypes("number")
    numeric[RESOURCE_FIELD] = frame[RESOURCE_FIELD]
    return numeric.groupby(RESOURCE_FIELD, as_index=False).sum()


def _order_by(frame, field, ascending):
    return frame.sort_values(by=field, ascending=ascending)


def order_price_asc(frame):
    return _order_by(frame, PRICE_FIELD, ascending=False)


def order_price_desc(frame):
    return _order_by(frame, PRICE_FIELD, ascending=False)


def order_consumption(frame):
    return _order_by(frame, CONSUMPTION_FIELD, ascending=False)


def exclude_fields(frame, fields):
    return frame.drop(columns=list(fields))


def include_fields(frame, fields):
    return frame[list(fields)]


def run_pipeline(frame, search_term, order, aggregate, excluded, included):
    if frame.empty:
        return []

    if search_term is not None:
        field, value = search_term
        frame = search(frame, field, value)

    if aggregate:
        frame = aggregate_by_resource(frame)

    if order == "price-asc":
        frame = order_price_asc(frame)
    elif order == "price-desc":
        frame = order_price_desc(frame)
    elif order == "consumption":
        frame = order_consumption(frame)

    if excluded:
        frame = exclude_fields(frame, excluded)
    elif included:
        frame = include_fields(frame, included)

    return frame


def to_json(result):
    records = result.to_dict(orient="records")
    return json.dumps(records, indent=2, default=str)


@click.command()
@click.option("-s", "--search", "search_term", nargs=2, type=str, default=None)
@click.option("-f", "--file", "config_file", required=True)
@click.option("-o", "--order", type=click.Choice(["price-asc", "price-desc", "consumption"]))
@click.option("-a", "--aggregate", is_flag=True, default=False)
def cli(search_term, config_file, order, aggregate):
    config = load_config(config_file)

    source_files = config["source_files"]
    excluded = config.get("excluded_fields")
    included = config.get("included_fields")

    frame = read_sources(source_files)

    search_arg = search_term if search_term else None
    result = run_pipeline(frame, search_arg, order, aggregate, excluded, included)

    click.echo(to_json(result))


if __name__ == "__main__":
    cli()
