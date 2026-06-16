---
title: So for the demo, we've asked an agent to build a CLI tool from a single one-shot prompt
---

# The setup

<!-- pause -->

- `fcb` — browse cloud costs in FOCUS-schema parquet exports
- reads a config file
- merges parquet files
- runs a small query pipeline
- prints JSON

<!-- pause -->

Let's create a config file then and try it:

```json
{
  "source_files": ["aws.snappy.parquet", "aws2.snappy.parquet"],
  "included_fields": ["ResourceId", "BilledCost"]
}
```

<!-- end_slide -->

# It runs

```bash +exec
uv run python wrong_example.py -f config.json -o price-asc -a | jq '.[:2]'
```

<!-- pause -->

The flags work. The JSON comes out.
So we're done... right?

<!-- end_slide -->

# The prompt that produced it

```markdown +line_numbers
# Implementation details

Let's create a single file CLI tool in @main.py for browsing cloud cost in FOCUS schema exports.

- the root command accepts the following flags:
  - `-s` or `--search` that accepts two arguments a field name and a field value, for example: `fcb -s ServiceCategory Networking`
  - `-f` or a `--file` flag for that should point to a config file
  - `-o` or `--order` flag that accepts the followin values `price-asc`, `price-desc`, `consumption`
  - `-a` or `--aggregate` flag that is a boolean flag
- read the config file
- read all the scrubbing info from the config file
- read and merge the content of all the parquet files that are defined in the config file
- create a function to orchestrate a read pipeline like implementation on the merged cloud cost data
- create a function to aggregate the responses by `ResourceID` and summarize all the values
- create functions to order the data in the pipeline `price-asc` or `price-desc` or `consumption`
- create a function that receives a set of field names and scrubs those from the rows for example `["ServiceName"]"` will output every field but ServiceName
- create a function that receives a set of field names and scrubs every not included fields from the rows, for example `["ResourceId"]` will only include the resource id in the response
- create a main function that picks the necessary pipeline functions based on the command line args, orchestrates them and returns the output
- the output format must be json

# Configuration File

- config file can be either json or yaml file, both are valid configuration files
- config file is an object with the following object shape:
  - `source_files` an array of file paths pointing to the parquet files
  - `excluded_fields` slice of field names that must be omitted ("scrubbed") from the response, mutually exclusive with `included_fields`
  - `included_fields` slice of field names that must be included in the response, every other fields are omitted, mutually exclusive with `excluded_fields`
```

<!-- pause -->

This isn't the prompt isn't what most pepole would write, yet the outcome is still iffy...

<!-- end_slide -->

# Let's look at a few of these functions

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

```python
def order_price_asc(frame):
    return _order_by(
        frame, PRICE_FIELD,
        ascending=False,
    )


def order_price_desc(frame):
    return _order_by(
        frame, PRICE_FIELD,
        ascending=False,
    )
```

<!-- column: 1 -->

```python
def run_pipeline(frame, ...):
    if frame.empty:
        return []
    # search / aggregate
    # order / scrub
    return frame


def load_config(path):
    ext = Path(path).suffix
    ...
    raise ValueError(
        "bad ext: %s" % ext
    )
```

<!-- reset_layout -->

<!-- pause -->

Read them slowly. They're syntactically perfect. They type-check fine.

**What's up with them?**

<!-- speaker_note: "order_price_asc sorts ascending=False; run_pipeline returns [] on empty; load_config uses %-formatting + trailing whitespace" -->

<!-- end_slide -->

# Four bugs hiding in plain sight

<!-- incremental_lists: true -->

<!-- pause -->

None of these are typos. None are crashes immediately. The code is "correct" to every reader who trusts it.

- **style** — `load_config` builds `"%s" % ext` (pre-`UP` formatting) with trailing whitespace
- **type** — `run_pipeline` returns `[]` on empty input; every other branch returns a `DataFrame`, so `to_dict()` would explode
- **behavior** — `order_price_asc` passes `ascending=False`: "cheapest first" returns the _most_ expensive
- **contract** — `load_config` validates nothing: `included_fields` + `excluded_fields` both set, unknown keys — all silently accepted

<!-- end_slide -->

# Four nets, left to right

We'll add tooling in the order a problem should be caught — earliest and cheapest first.

<!-- pause -->

| Solution        | Fixes                                              |
| --------------- | -------------------------------------------------- |
| **ruff**        | style, dead code, unsafe patterns                  |
| **ty**          | type errors, bad signatures                        |
| **pytest**      | **wrong behavior** - the logical flips             |
| **JSON Schema** | **wrong contract** - config issues, IDE completion |

<!-- pause -->

Then we make all four a **hard requirement** of the agent loop. That's the punchline.

<!-- end_slide -->

# Let's extend our prompt first, to fix the schema!

```markdown
## Config Validation

For config file validation use json schema as a single source of truth, implemented the following way:

- create a new json schema `fcb.schema.json` that defines the schema of our configuration, with examples and descriptions
- add `jsonschema` as dependency and import the json schema as json so our bundler bundles it into the release file
- validate the json schema to our @fcb.schema.json using jsconschema after reading it in
- ignore `$schema` tags in case of json files, they are only there for better IDE support
```

<!-- pause -->

```markdown
# Testing

For testing make sure every function is unit testable.

- install `pytest` as a dev dependency for tests
- create unit tests for each individual functions, with at least one positive and one negative test case
```

<!-- end_slide -->

# The shift: move the nets into the loop

The agent is fast. Left alone, it's also confidently wrong.

<!-- pause -->

The agent literally **cannot finish** until format, lint, types, and tests all pass.

```json
{
  "hooks": {
    "Stop": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "test \"$(cat | jq -r \".stop_hook_active // false\")\" = true && exit 0; mise lint && mise test >&2 || exit 2",
            "timeout": 60,
            "statusMessage": "Running lint & typecheck & tests..."
          }
        ]
      }
    ]
  }
}
```

<!-- end_slide -->

# Rules? Rules. Rules!

```toml
[tool.ruff]
line-length = 100
target-version = "py314"

[tool.ruff.lint]
select = [
    "E",   # pycodestyle errors (style: indentation, whitespace, statements)
    "W",   # pycodestyle warnings (deprecations, trailing whitespace)
    "F",   # pyflakes (logical errors: unused imports/vars, undefined names)
    "I",   # isort
    "N",   # pep8-naming
    "UP",  # pyupgrade
    "B",   # flake8-bugbear (common bugs)
    "A",   # builtins shadowing
    "C4",  # comprehensions
    "SIM", # flake8-simplify
    "RET", # return statements
    "ARG", # unused arguments
    "PTH", # use pathlib
    "ERA", # no commented-out code
    "RUF", # ruff-specific
    "D",   # pydocstyle — require docstrings
    "ANN", # type annotations
    "S",   # bandit (security)
    "TRY", # tryceratops (exception handling)
]

[tool.ruff.lint.pydocstyle]
convention = "google"
```

# Same speed, now with a floor under it

<!-- incremental_lists: true -->

- Correctness checks ran **once, at the end** → now they run **every iteration**
- The correctness checks are now **deterministic**
- The agent self-corrects against real and dense information, instead of multiple iterations

<!-- end_slide -->

# The result — the same prompt, the right tooling

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Code**

```python
def order_price_asc(
    frame: pd.DataFrame,
) -> pd.DataFrame:
    """Order rows by BilledCost,
    cheapest first."""
    return _order_by(
        frame, PRICE_FIELD,
        ascending=True,    # correct
    )
```

- typed, documented, **correct**

<!-- column: 1 -->

**Coden't**

```python
def order_price_asc(frame):
    return _order_by(
        frame, PRICE_FIELD,
        ascending=False,   # bug
    )
```

- no types
- no docs
- silent logical flips

<!-- reset_layout -->

![image:width:30%](dogo.png)

<!-- end_slide -->

# The result — the type bug

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Code**

```python
def run_pipeline(
    frame: pd.DataFrame,
    ...,
) -> pd.DataFrame:
    ...
    return frame
```

- one return type, **enforced by ty**
- empty frame just flows through

<!-- column: 1 -->

**Coden't**

```python
def run_pipeline(frame, ...):
    if frame.empty:
        return []
    ...
    return frame
```

- two return types
- `list` has no `.to_dict`
- explodes on empty input

<!-- reset_layout -->

![image:width:30%](dogo.png)

<!-- end_slide -->

# The result — the style bug

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Code**

```python
def load_config(
    path: str,
) -> dict[str, Any]:
    ext = Path(path).suffix.lower()
    ...
    msg = f"bad ext: {ext}"
    raise ValueError(msg)
```

- f-string, clean — **ruff auto-fixes**

<!-- column: 1 -->

**Coden't**

```python
def load_config(path):
    ext = Path(path).suffix
    ...
    raise ValueError(
        "bad ext: %s" % ext
    )
```

- printf `%` formatting
- trailing whitespace

<!-- reset_layout -->

![image:width:30%](dogo.png)

<!-- end_slide -->

# The result — the contract

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**Code**

```python
config.pop("$schema", None)
validate(
    instance=config,
    schema=load_schema(),
)
```

- one source of truth: `fcb.schema.json`
- mutual exclusivity **enforced**
- `$schema` → IDE completion

<!-- column: 1 -->

**Coden't**

```python
config = json.loads(text)
# anything goes:
#   unknown keys
#   both field sets
#   typos
# ...all accepted
```

- no validation, silent drift

<!-- reset_layout -->

![image:width:30%](dogo.png)

<!-- end_slide -->

# Same prompt, same edge cases — run them

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

**`correct_example.py`**

```bash +exec
C=correct_example.py
echo "▶ price-asc → cheapest first?"
uv run python $C -f config.json -o price-asc -a | jq 'first.BilledCost'
echo "▶ empty input"
uv run python $C -f edge-empty.json
echo "▶ unknown config key"
uv run python $C -f edge-unknown.json 2>&1 | grep -o "Additional.*"
```

<!-- column: 1 -->

**`wrong_example.py`**

```bash +exec
W=wrong_example.py
echo "▶ price-asc → cheapest first?"
uv run python $W -f config.json -o price-asc -a | jq 'first.BilledCost'
echo "▶ empty input"
uv run python $W -f edge-empty.json 2>&1 | tail -1
echo "▶ unknown config key"
uv run python $W -f edge-unknown.json | jq length
```

<!-- reset_layout -->

![image:width:30%](dogo.png)

<!-- end_slide -->

# Takeaways

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

<!-- jump_to_middle -->

1. **uv** makes checking free — so you can afford to check constantly
2. **ruff + ty** catch structure; **pytest** catches behavior — you need all of it
3. The win isn't the tools, it's **moving them left into the agent's loop as a hard gate**

<!-- column: 1 -->

<!-- jump_to_middle -->

![image](stonks.png)

<!-- end_slide -->

# Thank you

<!-- column_layout: [1, 1] -->

<!-- column: 0 -->

<!-- jump_to_middle -->

Back to Aamna!

<!-- column: 1 -->

![image](back.png)
