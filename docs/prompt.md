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

## Config Validation

For config file validation use json schema as a single source of truth, implemented the following way:

- create a new json schema `fcb.schema.json` that defines the schema of our configuration, with examples and descriptions
- add `jsonschema` as dependency and import the json schema as json so our bundler bundles it into the release file
- validate the json schema to our @fcb.schema.json using jsconschema after reading it in
- ignore `$schema` tags in case of json files, they are only there for better IDE support

# Testing

For testing make sure every function is unit testable.

- install `pytest` as a dev dependency for tests
- create unit tests for each individual functions, with at least one positive and one negative test case
