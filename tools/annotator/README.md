# Agent Annotator

Generate Hermes typed-shape annotation JSON with Claude Code or Codex.

```sh
uv run annotator input.js \
  --config agent-config.json \
  -o input.annotations.json
```

Run commands from this directory (`tools/annotator`). The project uses a
local uv environment and exposes the `annotator` console script. The
module entry point is also available:

```sh
uv run python -m annotator input.js \
  --config agent-config.json \
  -o input.annotations.json
```

The tool runs the selected agent in a temporary attempt directory. The agent
writes `annotation.json` there, then this wrapper copies it to `--output` when
the agent run succeeds. A run record (`<output>.run.json`) — raw agent messages
plus metadata — is always written, even on failure; statistics are recomputed
from it offline by `python -m annotator.postprocess`.

## Code Layout

- `pyproject.toml`: uv/Python project metadata and the `annotator`
  console script.
- `src/annotator/annotate.py`: thin CLI entry point.
- `src/annotator/config.py`: CLI/config-file parsing and per-agent
  runtime settings.
- `src/annotator/prompt.py`: annotation prompt and supported schema values.
- `src/annotator/pipeline.py`: attempt directory setup, output copying, stats
  JSON, and terminal reporting.
- `src/annotator/metrics.py`: token, cost, event, and tool-use metrics.
- `src/annotator/agents/`: runner interface/factory plus separate Claude and
  Codex SDK adapters.
- `tests/`: unit tests for CLI behavior, stats, and config handling.
- `naive.json`: sample agent configuration.

## Jelly static-analysis tools (call graph, heat, data flow)

The agent can optionally use call-graph, heat-estimation and data-flow
information produced by [Jelly](https://github.com/cs-au-dk/jelly), exposed as
two in-process MCP servers (`jelly`, `jelly-dataflow`) alongside `fold` /
`locate` / `dryrun`. They are not built from the source file: the host must run
Jelly and drop its output into the attempt workdir first.

Host setup (per target), from a Jelly checkout:

```sh
mkdir -p .jelly
jelly -b <project-root> -j .jelly/cg.json <entry-files...>          # call graph
jelly -b <project-root> --dataflow-json .jelly/df.json \
      --dataflow-source <rel-file>:<line>:<col> <entry-files...>   # data flow
```

All Jelly artifacts live under a single `.jelly/` directory in the attempt
workdir (just like `.feedback/`):

```
.jelly/
├── cg.json       # call graph (host pre-gen + priors_service regen)
├── df.json       # data-flow report (host gen per query_dataflow source)
├── req.json      # reanalyze: agent → host (call-edge override rules)
├── prior.json    # reanalyze: host → jelly (--call-edge-priors input)
├── res.json      # reanalyze: host → agent (ok / stderr)
├── df_req.json   # dataflow: agent → host (source file:line:col)
└── df_res.json   # dataflow: host → agent (ok / stderr)
```

Loading and re-analysis are AUTOMATIC — there is no load or re-run tool. Query
tools auto-load `.jelly/cg.json` on first use; if it is absent they reply
"暂无调用图" (not an error) and the agent proceeds without.

`jelly` server (call graph + heat):

- `view_callgraph`, `get_callers`, `get_callees`, `list_call_edge_overrides`
- `add_call_edges`, `delete_call_edges`, `clear_call_edge_overrides` — edit
  edges; updates the view immediately AND triggers an async host re-run (below)
  so the change reaches points-to
- `view_hot_value`, `set_hot_value`, `set_exec_expt`, `set_target_prob` — heat;
  `set_target_prob` with prob 0 also triggers the async re-run (== delete edge)

`jelly-dataflow` server:

- `query_dataflow` with `source` = `file:line:col` (1-based column) — traces
  where the source expression's value may flow. The host re-runs Jelly for that
  source (`--dataflow-json .jelly/df.json --dataflow-source <source>`); the tool
  returns the source-level points reached (variable / return / this / arguments).
  Abstract object and internal nodes are hidden.

Loop depth for heat is parsed in-process with tree-sitter-javascript from the
source tree under `root` (defaults to the workdir).

### Async re-analysis with call-edge priors (host)

`add_call_edges` / `delete_call_edges` / `clear_call_edge_overrides` /
`set_target_prob(..., 0)` write the session overrides to `.jelly/req.json` and
return immediately. A host `priors_service` re-runs Jelly with
`--call-edge-priors` to regenerate `.jelly/cg.json`. While that is in flight,
queries return "分析未完成,稍后再查"; on completion the tool reloads the new
graph (revision bump) and clears the session overrides (the host has applied
them). Set `jelly_bin` (path to the Jelly executable) in the agent config to
enable the host service (claude backend); a `dataflow_service` runs alongside it
for `query_dataflow`. `force_exclude` drops edges throughout analysis (including
finalization backfill); `force_include` injects callees and propagates
args/this/return. require/import/interop/native-invoke force-include is not
supported (no call-site callee variable).

## Options

- `--config PATH` loads agent/model/environment configuration from JSON.
- `--agent-timeout SEC` limits each agent attempt. Default: `600`.
- `--verbose-agent-logs` enables selected SDK messages in the logger.
- `--keep-workdir` preserves prompts and temporary annotations for debugging.
- `--append-prompt TEXT` appends extra text after the built prompt for this run only.

## Temporary Model Configuration

Use `--config` for agent selection and model/provider setup. The config file is
the single source of truth for agent configuration. The agent SDK environment
inherits only system proxy variables, then applies `env` from this file. The
wrapper leaves the global shell and CLI config untouched.

```json
{
  "agent": "codex",
  "model": "gpt-5",
  "env": {
    "OPENAI_API_KEY": "..."
  },
  "codex_config": {
    "model_provider": "openai"
  }
}
```

`agent` must be either `codex` or `claude`. `codex_config` entries are passed
to the Codex SDK thread start configuration. For Claude, `claude_settings` is
passed to the Claude Agent Python SDK. The Claude backend runs the agent inside
a Docker container (see *Container mode* below) with
`permission_mode = bypassPermissions` and no in-process sandbox — the container
is the isolation boundary. `claude_sandbox` in the config is accepted but is now
a no-op. The optional `docker_image` field overrides the default image tag
(`annotator-agent:latest`).

## Container mode (claude backend)

The claude backend no longer runs `claude` directly on the host. Per attempt it
launches the `annotator-agent` Docker image: the attempt directory is
bind-mounted at `/work`, the prompt + non-secret config are dropped there, and
the API-key/proxy env is passed via an out-of-volume `--env-file` (so secrets
never land in a `--keep-workdir` directory). Inside, `annotator.agent_worker`
runs claude with `bypassPermissions`, the full built-in tool set, and the
`fold`/`locate` MCP tools, then writes messages/errors back to the volume.

Build the image once (requires Docker on the host):

```sh
cd tools/annotator
docker build -t annotator-agent:latest .
```

The image is based on `python:3.13-slim`, installs `nodejs` (an extra
interpreter for the agent), and `pip install`s this package — which pulls
`claude-agent-sdk` (it bundles its own native `claude` binary, so no Node is
needed to run the CLI), `tree-sitter`, and `tree-sitter-javascript`. The codex
backend is unchanged and does not use Docker.

## Tests

```sh
uv run python -m unittest discover -s tests
```

## Annotation Format

The generated JSON must follow the schema loaded by `AnnotationLoader`:

- top-level object: `"static shapes"`, mapping shape names to shape definitions
- top-level arrays: `"shape guards"`, `"shape bindings"`
- optional top-level array: `"type guards"`
- supported property/type-guard types:
  `number`, `string`, `boolean`, `null`, `undefined`, or `any` for anything
  else (e.g. object, bigint, symbol)
- ranges use 1-based line and column numbers

The prompt asks the agent to optimize hot code first: loops, nested loops,
frequently called functions, core data structure accesses, and repeated
property reads/writes. Shape definitions must exactly match object construction,
including property order and JS descriptor flags, because typed shapes are
order-sensitive. Property `type` defaults to `any`, `kind` defaults to `data`,
and descriptor flags default to on; list disabled descriptor flags with
`"flags off"` (allowed: `writable`, `enumerable`, `configurable`). Shape names
are only stable identifiers used by guards and bindings.

## Statistics

The stats file is written only after a successful agent run and includes:

- elapsed time
- token usage, cost, tool usage, and event summaries extracted by the selected SDK adapter
