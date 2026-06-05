import json
from pathlib import Path

import jsonschema
import pandas as pd
import pytest
import yaml
from click.testing import CliRunner

import main

# ----- load_schema -----


def test_load_schema_returns_object():
    schema = main.load_schema()
    assert isinstance(schema, dict)
    assert schema["title"] == "FCB Configuration"


def test_load_schema_path_is_correct():
    assert main.SCHEMA_PATH.exists()


# ----- load_config -----


def test_load_config_json(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text('{"source_files": ["a.parquet"]}')
    assert main.load_config(p) == {"source_files": ["a.parquet"]}


def test_load_config_yaml(tmp_path: Path):
    p = tmp_path / "c.yaml"
    p.write_text("source_files:\n  - a.parquet\n")
    assert main.load_config(p) == {"source_files": ["a.parquet"]}


def test_load_config_rejects_unknown_extension(tmp_path: Path):
    p = tmp_path / "c.toml"
    p.write_text("source_files = []")
    with pytest.raises(ValueError, match="Unsupported config file extension"):
        main.load_config(p)


def test_load_config_rejects_non_object_root(tmp_path: Path):
    p = tmp_path / "c.json"
    p.write_text("[1, 2, 3]")
    with pytest.raises(TypeError, match="must be an object"):
        main.load_config(p)


# ----- validate_config -----


def test_validate_config_strips_dollar_schema():
    schema = main.load_schema()
    cleaned = main.validate_config({"$schema": "irrelevant", "source_files": ["a.parquet"]}, schema)
    assert "$schema" not in cleaned
    assert cleaned["source_files"] == ["a.parquet"]


def test_validate_config_accepts_excluded_only():
    schema = main.load_schema()
    main.validate_config({"source_files": ["a"], "excluded_fields": ["Tags"]}, schema)


def test_validate_config_accepts_included_only():
    schema = main.load_schema()
    main.validate_config({"source_files": ["a"], "included_fields": ["ResourceId"]}, schema)


def test_validate_config_rejects_both_included_and_excluded():
    schema = main.load_schema()
    with pytest.raises(jsonschema.ValidationError):
        main.validate_config(
            {"source_files": ["a"], "included_fields": ["x"], "excluded_fields": ["y"]},
            schema,
        )


def test_validate_config_requires_source_files():
    schema = main.load_schema()
    with pytest.raises(jsonschema.ValidationError):
        main.validate_config({}, schema)


def test_validate_config_rejects_empty_source_files():
    schema = main.load_schema()
    with pytest.raises(jsonschema.ValidationError):
        main.validate_config({"source_files": []}, schema)


# ----- load_parquet_files -----


def _write_parquet(path: Path, frame: pd.DataFrame) -> None:
    frame.to_parquet(path, index=False)


def test_load_parquet_files_merges_multiple(tmp_path: Path):
    a = tmp_path / "a.parquet"
    b = tmp_path / "b.parquet"
    _write_parquet(a, pd.DataFrame({"ResourceId": ["r1"], "BilledCost": [1.0]}))
    _write_parquet(b, pd.DataFrame({"ResourceId": ["r2"], "BilledCost": [2.0]}))
    rows = main.load_parquet_files([str(a), str(b)])
    assert len(rows) == 2
    assert {r["ResourceId"] for r in rows} == {"r1", "r2"}


def test_load_parquet_files_empty_list_returns_empty():
    assert main.load_parquet_files([]) == []


def test_load_parquet_files_missing_file_raises(tmp_path: Path):
    with pytest.raises(FileNotFoundError):
        main.load_parquet_files([str(tmp_path / "nope.parquet")])


# ----- search_rows -----


def test_search_rows_matches():
    rows = [
        {"ServiceCategory": "Networking", "BilledCost": 1.0},
        {"ServiceCategory": "Compute", "BilledCost": 2.0},
    ]
    assert main.search_rows(rows, "ServiceCategory", "Networking") == [rows[0]]


def test_search_rows_no_match():
    rows = [{"ServiceCategory": "Compute"}]
    assert main.search_rows(rows, "ServiceCategory", "Networking") == []


def test_search_rows_field_missing_in_row():
    rows = [{"OtherField": "x"}]
    assert main.search_rows(rows, "ServiceCategory", "Networking") == []


# ----- aggregate_by_resource_id -----


def test_aggregate_sums_numerics_and_keeps_first_string():
    rows = [
        {"ResourceId": "r1", "BilledCost": 1.0, "ServiceName": "EC2"},
        {"ResourceId": "r1", "BilledCost": 2.5, "ServiceName": "EC2"},
        {"ResourceId": "r2", "BilledCost": 3.0, "ServiceName": "S3"},
    ]
    result = main.aggregate_by_resource_id(rows)
    by_id = {r["ResourceId"]: r for r in result}
    assert by_id["r1"]["BilledCost"] == pytest.approx(3.5)
    assert by_id["r1"]["ServiceName"] == "EC2"
    assert by_id["r2"]["BilledCost"] == pytest.approx(3.0)


def test_aggregate_empty_returns_empty():
    assert main.aggregate_by_resource_id([]) == []


def test_aggregate_without_resource_id_passes_through():
    rows = [{"BilledCost": 1.0}, {"BilledCost": 2.0}]
    assert main.aggregate_by_resource_id(rows) == rows


# ----- ordering -----


def _price_rows():
    return [
        {"BilledCost": 3.0},
        {"BilledCost": 1.0},
        {"BilledCost": 2.0},
    ]


def test_order_by_price_asc():
    assert [r["BilledCost"] for r in main.order_by_price_asc(_price_rows())] == [1.0, 2.0, 3.0]


def test_order_by_price_asc_empty():
    assert main.order_by_price_asc([]) == []


def test_order_by_price_desc():
    assert [r["BilledCost"] for r in main.order_by_price_desc(_price_rows())] == [3.0, 2.0, 1.0]


def test_order_by_price_desc_treats_missing_as_zero():
    rows = [{"BilledCost": 1.0}, {}]
    assert main.order_by_price_desc(rows) == [{"BilledCost": 1.0}, {}]


def test_order_by_consumption_desc():
    rows = [
        {"ConsumedQuantity": 1.0},
        {"ConsumedQuantity": 3.0},
        {"ConsumedQuantity": 2.0},
    ]
    out = [r["ConsumedQuantity"] for r in main.order_by_consumption(rows)]
    assert out == [3.0, 2.0, 1.0]


def test_order_by_consumption_empty():
    assert main.order_by_consumption([]) == []


# ----- field scrubbing -----


def test_exclude_fields_drops_named_fields():
    rows = [{"a": 1, "b": 2, "c": 3}]
    assert main.exclude_fields(rows, ["a", "c"]) == [{"b": 2}]


def test_exclude_fields_empty_field_list_passes_through():
    rows = [{"a": 1}]
    assert main.exclude_fields(rows, []) == rows


def test_exclude_fields_unknown_field_is_noop():
    rows = [{"a": 1}]
    assert main.exclude_fields(rows, ["z"]) == rows


def test_include_fields_keeps_only_named_fields():
    rows = [{"a": 1, "b": 2, "c": 3}]
    assert main.include_fields(rows, ["a", "c"]) == [{"a": 1, "c": 3}]


def test_include_fields_empty_field_list_drops_everything():
    rows = [{"a": 1, "b": 2}]
    assert main.include_fields(rows, []) == [{}]


def test_include_fields_unknown_field_drops_all():
    rows = [{"a": 1}]
    assert main.include_fields(rows, ["z"]) == [{}]


# ----- pipeline -----


def test_build_pipeline_includes_steps_for_each_flag():
    steps = main.build_pipeline(
        search=("ServiceCategory", "Networking"),
        aggregate=True,
        order="price-asc",
        included=None,
        excluded=["Tags"],
    )
    assert len(steps) == 4


def test_build_pipeline_no_flags_is_empty():
    steps = main.build_pipeline(
        search=None, aggregate=False, order=None, included=None, excluded=None
    )
    assert steps == []


def test_build_pipeline_prefers_included_over_excluded():
    steps = main.build_pipeline(
        search=None,
        aggregate=False,
        order=None,
        included=["ResourceId"],
        excluded=["Tags"],
    )
    sample = [{"ResourceId": "r1", "Tags": "t", "Other": 1}]
    assert steps[0](sample) == [{"ResourceId": "r1"}]


def test_run_pipeline_applies_steps_in_order():
    rows = [
        {"ResourceId": "r1", "BilledCost": 1.0, "ServiceCategory": "X"},
        {"ResourceId": "r2", "BilledCost": 2.0, "ServiceCategory": "Y"},
    ]
    steps = main.build_pipeline(
        search=("ServiceCategory", "Y"),
        aggregate=False,
        order=None,
        included=["ResourceId"],
        excluded=None,
    )
    assert main.run_pipeline(rows, steps) == [{"ResourceId": "r2"}]


def test_run_pipeline_with_no_steps_returns_input():
    rows = [{"a": 1}]
    assert main.run_pipeline(rows, []) == rows


# ----- to_json -----


def test_to_json_renders_basic_records():
    payload = json.loads(main.to_json([{"a": 1, "b": "x"}]))
    assert payload == [{"a": 1, "b": "x"}]


def test_to_json_empty_returns_empty_array():
    assert main.to_json([]) == "[]"


def test_to_json_converts_nan_to_null():
    payload = json.loads(main.to_json([{"a": float("nan")}]))
    assert payload == [{"a": None}]


def test_to_json_handles_timestamps():
    ts = pd.Timestamp("2024-01-02T03:04:05Z")
    payload = json.loads(main.to_json([{"t": ts}]))
    assert payload[0]["t"].startswith("2024-01-02T03:04:05")


# ----- execute / end-to-end -----


def _aws_config(tmp_path: Path) -> Path:
    src = Path(__file__).parent / "aws.snappy.parquet"
    cfg = tmp_path / "config.yaml"
    cfg.write_text(
        yaml.safe_dump(
            {"source_files": [str(src)], "included_fields": ["ServiceCategory", "BilledCost"]}
        )
    )
    return cfg


def test_execute_with_real_parquet(tmp_path: Path):
    src = Path(__file__).parent / "aws.snappy.parquet"
    if not src.exists():
        pytest.skip("aws.snappy.parquet not present")
    out = main.execute(
        {"source_files": [str(src)], "included_fields": ["ServiceCategory"]},
        search=("ServiceCategory", "Networking"),
        aggregate=False,
        order=None,
    )
    assert out
    assert all(r == {"ServiceCategory": "Networking"} for r in out)


def test_cli_runs_end_to_end(tmp_path: Path):
    src = Path(__file__).parent / "aws.snappy.parquet"
    if not src.exists():
        pytest.skip("aws.snappy.parquet not present")
    cfg = _aws_config(tmp_path)
    runner = CliRunner()
    result = runner.invoke(
        main.cli,
        ["-f", str(cfg), "-s", "ServiceCategory", "Networking", "-o", "price-desc"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload
    assert all(r["ServiceCategory"] == "Networking" for r in payload)
    costs = [r["BilledCost"] for r in payload if r["BilledCost"] is not None]
    assert costs == sorted(costs, reverse=True)


def test_cli_rejects_invalid_config(tmp_path: Path):
    cfg = tmp_path / "bad.json"
    cfg.write_text(
        json.dumps({"source_files": ["a"], "included_fields": ["x"], "excluded_fields": ["y"]})
    )
    runner = CliRunner()
    result = runner.invoke(main.cli, ["-f", str(cfg)])
    assert result.exit_code != 0
