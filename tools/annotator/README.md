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
maintains the annotation set **in memory** through the mandatory `annotations`
MCP tools (`list_annotations` / `add_annotation` / `delete_annotation`) — it
never writes a file. When the agent run succeeds, the worker flushes the
in-memory document to `.annotations.json`, this wrapper validates it and copies
it to `--output`. A run record (`<output>.run.json`) — raw agent messages plus
metadata — is always written, even on failure; statistics are recomputed from
it offline by `python -m annotator.postprocess`.

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
├── df.<req_id>.json # data-flow report for one keyed source/direction request
├── req.json      # reanalyze: agent → host (call-edge override rules)
├── prior.json    # reanalyze: host → jelly (--call-edge-priors input)
├── res.json      # reanalyze: host → agent (ok / stderr)
├── df_req.json   # dataflow: agent → host (source file:line:col)
└── df_res.json   # dataflow: host → agent (ok / stderr)
```

Loading and re-analysis are AUTOMATIC — there is no load or re-run tool. Query
tools auto-load `.jelly/cg.json` on first use; if background prewarm has not
published one yet they reply `not yet ready` (not an error) and the agent can
retry after a few seconds.

`jelly` server (call graph + heat):

- `view_callgraph`, `get_callers`, `get_callees`, `list_call_edge_overrides`
- `add_call_edges`, `delete_call_edges`, `clear_call_edge_overrides` — edit
  edges; updates the view immediately AND triggers an async host re-run (below)
  so the change reaches points-to
- `view_hot_value`, `set_hot_value`, `set_exec_expt`, `set_target_prob` — heat;
  `set_target_prob` with prob 0 also triggers the async re-run (== delete edge)

`jelly-dataflow` server:

- `query_dataflow` with `source` = `startLine:startCol:endLine:endCol` — traces
  where the source expression's value may flow. The host re-runs Jelly for that
  keyed source/direction request and publishes `.jelly/df.<req_id>.json`; the
  tool returns the source-level points reached (variable / return / this /
  arguments). Abstract object and internal nodes are hidden.

Loop depth for heat is parsed in-process with tree-sitter-javascript from the
source tree under `root` (defaults to the workdir).

### Non-blocking Jelly prewarm and refresh (host)

When `jelly_bin` is configured, the Claude host starts a background call-graph
prewarm while the agent starts. Queries never wait for Jelly: before the first
successful graph is published they return `not yet ready`; during a re-analysis
they return the last completed graph, marked stale and with the local override
overlay, and ask the agent to retry after a few seconds. Callgraph artifacts
and both request/response IPC pairs are atomically published, so either side
never observes a partial JSON file.

`add_call_edges` / `delete_call_edges` / `clear_call_edge_overrides` /
`set_target_prob(..., 0)` return immediately and trigger an asynchronous host
refresh using `--call-edge-priors`. Mutations arriving during a refresh are
coalesced into one follow-up run rather than overwriting the in-flight request.
On successful completion the next query loads the new graph (revision bump) and
clears the override overlay. `force_exclude` drops edges throughout analysis
(including finalization backfill); `force_include` injects callees and propagates
args/this/return. require/import/interop/native-invoke force-include is not
supported (no call-site callee variable).

`query_dataflow` follows the same non-blocking contract, but caches results by
exact `(source range, direction)`: its first request queues host work and
returns `not yet ready`; a later query reads that key's completed report and
marks it stale only when that key is refreshing.

## Options

- `--config PATH` loads agent/model/environment configuration from JSON.
- `--agent-timeout SEC` limits each agent attempt. Default: `600`.
- `--verbose-agent-logs` enables selected SDK messages in the logger.
- `--keep-workdir` preserves prompts and temporary annotations for debugging.
- `--append-prompt TEXT` appends extra text after the built prompt for this run only.

## Annotation tools (mandatory, in-process MCP)

The agent does NOT write `annotation.json`. It builds the annotation set through
three in-process MCP tools that own a single in-memory document for the run:

- `list_annotations(kinds?, shape?, from_line?, to_line?)` — list current
  annotations, optionally filtered by kind (`static_shape` / `shape_binding` /
  `shape_guard` / `type_guard`), by shape name, or by a 1-based inclusive line
  window (`from_line` and `to_line` together, or neither). Each row carries a
  short-lived `id` (`kind:index:revision`) for `delete_annotation`. Static
  shapes have no source range, so a line filter hides them.
- `add_annotation(kind, annotation, shape?)` — append one annotation (a shape,
  binding, guard, or type guard). Duplicates and references to unknown shapes
  are rejected; add a static shape before any guard/binding that names it.
- `delete_annotation(id)` — remove one annotation by a fresh `id` from
  `list_annotations`. The id embeds the document revision; after any mutation
  an older id is stale and rejected. A static shape still used by a
  guard/binding cannot be deleted.

The `annotations` server is **always enabled** — it is not part of
`enabled_tools` and cannot be turned off. The five-stage `chunk`, `comments`,
and `coverage` servers are likewise always enabled; `enabled_tools` controls
only additional capabilities. When `dryrun` is also enabled, the
two share the same in-memory document: `dryrun_annotation` compiles against
the current snapshot (flushed per request to `.feedback/annotation.json` for
the host `annotation-dryrun` binary) rather than a file the agent wrote.

When the agent finishes, `annotator.agent_worker` flushes the document to
`.annotations.json` and `annotator.pipeline` validates it before promoting it
to `--output`.

## Five-stage runtime contract

Each attempt stages `.about_annotations.md` in its work directory, which the
Claude container mounts at `/work`. The orchestrating agent and all
fresh-context subagents explicitly read this same file; it is the authoritative
explanation of annotation meaning, compiler/runtime mechanisms, costs, schema,
and examples.

The workflow is:

1. `understand-chunk` subagents write phase1 general semantic, callgraph, heat,
   and chunk input/output comments.
2. `shape-facts-chunk` subagents consume all relevant phase1 comments and write
   phase2 creation, shape-certainty, hot-use, and frequent-write evidence.
3. One global `shape-review` subagent reconciles that evidence, adds canonical
   `static_shape` annotations, and writes phase3 accept/merge/weaken/reject
   decisions.
4. `annotate-chunk` subagents list those shapes first, consume phases 1–3, add
   bindings/guards/type guards or explicit skips, and write phase4 evidence.
5. The same global `shape-review` subagent uses coverage and available dryrun
   feedback to correct the document and writes a phase5 cost/benefit review
   comment for **every final annotation**.

All handoffs use one `.chunks/comments.json` stream. Each comment has a
`phase`, line range, text, and (for phases 1, 2, and 4) a `chunk_id`; the MCP
server validates that chunk-produced comments remain inside their owner chunk.
It takes a cross-process file lock for every mutation and atomically replaces
the sidecar, so parallel workers cannot lose notes or reuse ids. Do not edit the
sidecar directly. `list_comments` can filter by phase, chunk, and/or line range;
a stage may read all completed earlier phases, not merely its immediate
predecessor. The annotation document remains in memory and has no sidecar merge
phase.

## Temporary Model Configuration

Use `--config` for agent selection and model/provider setup. The config file is
the single source of truth for agent configuration. The agent SDK environment
inherits only system proxy variables, then applies `env` from this file. The
wrapper leaves the global shell and CLI config untouched.

```json
{
  "agent": "claude",
  "model": "claude-sonnet-5",
  "env": {
    "ANTHROPIC_API_KEY": "..."
  },
  "enabled_tools": ["source-fold", "source-locate", "dryrun"]
}
```

`agent` must be `claude` — the annotation set is maintained through the
in-process `annotations` MCP, which only the Claude backend provides, so
`codex` is refused. `claude_settings` is passed to the Claude Agent Python SDK.
The Claude backend runs the agent inside a Docker container (see *Container
mode* below) with `permission_mode = bypassPermissions` and no in-process
sandbox — the container is the isolation boundary. `claude_sandbox` in the
config is accepted but is a no-op. The optional `docker_image` field overrides
the default image tag (`annotator-agent:latest`). `enabled_tools` lists the
OPTIONAL in-process MCP servers (the `annotations` server is always on); names
not in the registry are ignored.

## Container mode (claude backend)

The claude backend no longer runs `claude` directly on the host. Per attempt it
launches the `annotator-agent` Docker image: the attempt directory is
bind-mounted at `/work`, the prompt + non-secret config are dropped there, and
the API-key/proxy env is passed via an out-of-volume `--env-file` (so secrets
never land in a `--keep-workdir` directory). Inside, `annotator.agent_worker`
runs claude with `bypassPermissions`, the full built-in tool set, and the
mandatory `annotations` MCP (plus any enabled `fold`/`locate`/`dryrun` tools),
then flushes the in-memory annotation document to `.annotations.json` and
writes messages/errors back to the volume.

Build the image once (requires Docker on the host):

```sh
cd tools/annotator
docker build -t annotator-agent:latest .
```

The image is based on `python:3.13-slim`, installs `nodejs` (an extra
interpreter for the agent), and `pip install`s this package — which pulls
`claude-agent-sdk` (it bundles its own native `claude` binary, so no Node is
needed to run the CLI), `tree-sitter`, and `tree-sitter-javascript`. Only the
claude backend is supported (see *Temporary Model Configuration*).

## Tests

```sh
uv run python -m pytest tests
```

`tests/test_integration.py` exercises the Jelly tools end to end and needs the
Jelly binary on the host; the rest are pure unit/handler tests.

## Annotation Format

The flushed document (the agent builds it via `add_annotation`) follows the
schema loaded by `AnnotationLoader`:

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

A run record (`<output>.run.json` — raw agent messages plus metadata) is always
written, even on failure. Statistics (elapsed time, token usage, cost, tool
usage, event summaries) are recomputed offline from it by
`python -m annotator.postprocess`, not written inline by the run.
