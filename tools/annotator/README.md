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
- `deepseek-v4.json`: sample agent configuration.

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
including property order, because typed shapes are order-sensitive. Shape names
are only stable identifiers used by guards and bindings.

## Statistics

The stats file is written only after a successful agent run and includes:

- elapsed time
- token usage, cost, tool usage, and event summaries extracted by the selected SDK adapter
