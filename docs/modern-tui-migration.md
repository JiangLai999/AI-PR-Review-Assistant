# AI PR Review Assistant — Modern OpenTUI Migration Plan

> Supersedes the previous Rich-panel / split Chat-vs-config visual plan.
> Approved direction: the CLI should open a full-screen, MiMoCode-style TUI by default.

Date: 2026-09-22

## 1. Product decision

`pr-review chat` will become a full-screen OpenTUI application modeled on the observed MiMoCode home screen:

- centered brand/logo area;
- one dominant prompt card;
- current agent / model / reasoning status directly below the prompt;
- keyboard shortcut hints;
- command palette invoked by `/`;
- persistent footer with workspace and version;
- no separate legacy rounded Chat workspace as the primary design;
- no separate Rich pixel configuration wizard as the primary interaction model.

The previous design rules that required separate rounded Chat boxes and separate `╔` configuration panels are retired. The new TUI owns both Chat and configuration through dialogs/routes.

## 2. Architecture

```text
pr-review CLI entry (Python)
        |
        +-- legacy/headless commands: review, demo, benchmark, config test
        |
        +-- `chat` launcher
                |
                +-- OpenTUI + Solid frontend (TypeScript/Bun)
                |
                +-- stdio JSONL protocol
                |
                +-- Python application backend
                        +-- Session / turn orchestration
                        +-- Command registry
                        +-- AppConfig / runtime profiles
                        +-- Agent / tool execution
                        +-- PR review orchestration
                        +-- providers / Ollama / remote APIs
                        +-- history / results / evidence
```

OpenTUI is a presentation/runtime layer, not a replacement for the Python review domain.

## 3. Frontend layout contract

The first screen must match the observed MiMoCode composition rather than the old wizard:

```text
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                         Xiaomi                              │
│                       MIMO CODE                             │
│                                                             │
│       ┌─────────────────────────────────────────────┐       │
│       │ 输入消息...(输入 / 唤起命令)                 │       │
│       └─────────────────────────────────────────────┘       │
│         Build · provider/model · reasoning                   │
│       tab 模式  ctrl+p 设置  @ 文件  $ 子智能体  / 命令      │
│                                                             │
│                         status                              │
│                                                             │
│  workspace                                      version     │
└─────────────────────────────────────────────────────────────┘
```

The visual system will use OpenTUI layout primitives, not Rich panels. The existing `╔` renderer becomes a compatibility renderer for non-TUI/headless output only.

## 4. Frontend modules

Initial scaffold:

```text
frontend/tui/
├── package.json
├── tsconfig.json
└── src/
    ├── main.tsx
    └── app.tsx
```

Next modules:

```text
src/
├── protocol.ts       JSONL request/event types
├── backend.ts        stdio process client
├── state/
│   ├── session.ts
│   ├── config.ts
│   ├── runtime.ts
│   └── task.ts
├── components/
│   ├── home.tsx
│   ├── prompt.tsx
│   ├── command-palette.tsx
│   ├── dialog-select.tsx
│   ├── status-line.tsx
│   ├── transcript.tsx
│   ├── task-panel.tsx
│   └── footer.tsx
├── routes/
│   ├── home.tsx
│   ├── session.tsx
│   └── setup.tsx
└── theme/
    ├── colors.ts
    └── theme.ts
```

## 5. Backend protocol

The backend will communicate through newline-delimited JSON. No secrets are sent to the frontend unless explicitly needed for display, and secrets remain masked.

Requests:

```json
{"id":"1","method":"session.create","params":{}}
{"id":"2","method":"chat.send","params":{"session_id":"...","text":"..."}}
{"id":"3","method":"command.execute","params":{"name":"status","args":[]}}
{"id":"4","method":"config.open","params":{"section":"runtime"}}
{"id":"5","method":"config.apply","params":{"section":"runtime","value":"cloud"}}
{"id":"6","method":"session.cancel","params":{"session_id":"..."}}
```

Events:

```text
session.ready
session.status
user.message
assistant.started
assistant.delta
assistant.finished
command.started
command.finished
tool.started
tool.progress
tool.finished
config.changed
review.stage
error
```

## 6. Runtime profiles

The frontend must expose these as first-class profiles:

- `cloud`: remote API Chat and review;
- `local`: Ollama Chat and review;
- `hybrid`: explicit local/remote routing;
- `offline`: deterministic analysis/demo only.

Chat model binding and Review model binding are separate. `/model` never silently changes provider.

## 7. Migration phases

### Phase A — current turn (started)

- add OpenTUI frontend workspace;
- reproduce the MiMoCode-style home surface;
- preserve existing Python backend and tests;
- document the new architecture;
- do not delete old code yet.

### Phase B — protocol and backend adapter

- add `src/ai_pr_review/backend/jsonl_server.py`;
- add typed protocol/event definitions;
- expose health, config snapshot, session create, chat send, and cancel;
- add contract tests using subprocess pipes.

### Phase C — real Chat integration

- move Chat turn orchestration behind the backend protocol;
- stream assistant events;
- render transcript and task status in OpenTUI;
- add command palette and history.

### Phase D — integrated setup dialogs

- runtime profile dialog;
- provider dialog;
- model dialog;
- GitHub credential dialog;
- preferences dialog;
- config summary and validation route;
- no external extra Enter prompts.

### Phase E — review workspace

- PR URL input;
- review stage/task tree;
- findings pane;
- evidence and diff pane;
- cancel/resume/retry;
- result persistence.

### Phase F — packaging and compatibility

- `pr-review chat` launches OpenTUI by default;
- `pr-review chat --plain` remains available for CI/fallback;
- package frontend runtime for Windows;
- verify CMD, PowerShell, Windows Terminal, VS Code terminal and narrow terminals.

## 8. Retired decisions

The following previous decisions are explicitly superseded:

- do not keep the old Rich rounded Chat workspace as the primary UI;
- do not make the `╔` configuration wizard the primary interactive route;
- do not grow `cli.py` with more visual branches;
- do not model the main Chat screen as a sequence of printed panels.

Rich remains allowed for reports and headless fallback, but not as the default interactive application shell.

## 9. Acceptance criteria

- typing `pr-review chat` opens the OpenTUI home screen;
- layout matches the observed MiMoCode composition at 80/120/160 columns;
- multiline input, Tab mode switching and the `/` command palette are functional; `@` file attachment and `$` subagents are not advertised until implemented;
- configuration is performed through in-app dialogs/routes;
- Chat and Review can use different model bindings;
- Python review tests remain green;
- frontend protocol tests cover every request/event pair;
- graceful fallback exists when OpenTUI cannot initialize.

## 10. Chat workspace correction (2026-09-23, first slice)

- Replaced the single-line `<input>` inside a fixed-height box with a wrapping OpenTUI `<textarea>` (one to six lines). Enter submits and Shift+Enter inserts a newline. The live editor buffer is read at submission time, including for fast paste/IME updates.
- Slash commands now have a small typed registry and a bounded, selectable menu (arrows, Tab completion, Enter execution, Esc dismissal). Enter resolves the selected command in the submit path to avoid a keydown/onSubmit race. Only implemented commands appear in the menu.
- The home quick-start section gives way while editing; the first turn switches to a compact session header. Transcript and review cards share a growing scroll region, while the Composer and footer remain outside it.
- Verified in a PTY that `/he` + Enter invokes `/help` (not an unsupported `/he`), `/` displays the menu, Up/Down+Tab completes `/status`, and a modified Return inserts a second textarea line.
- **Remaining after the first slice:** provider-native token streaming, durable session recovery, installed/pipx frontend packaging, and complete visual acceptance at multiple Windows Terminal sizes.

## 11. Native Chat streaming (2026-09-23, second slice)

- OpenAI-compatible providers (including DeepSeek and the local Ollama adapter) now request `stream: true` and parse SSE `data:` frames as they arrive. User-visible `delta.content` is sent immediately to the JSONL event sink; model reasoning text is not exposed as Chat content. Anthropic uses an explicit complete-response fallback until its own streaming adapter is added.
- `assistant.started/delta/finished/failed/cancelled` include request and session identifiers. The TUI drops stale events from old sessions/turns and can cancel an in-flight Chat request via Esc or Ctrl+C. Cancelled turns do not enter the stored conversation history.
- Real local smoke test: `python scripts/verify_tui_stream.py --model qwen3.5:4b`. The test keeps the backend stdin pipe open and verifies multiple deltas arrive before the final JSONL response and concatenate to the saved answer. Qwen's thinking may delay the first user-visible content; no hidden reasoning is shown.
- **Still pending:** native Anthropic streaming, stronger HTTP socket abort guarantees, durable session recovery after backend restart, installed/pipx packaging, and multi-size terminal visual QA.

## 12. Backend restart and provider-route recovery (2026-09-23)

- The Bun backend client now tracks subprocess generations and rejects pending requests when the stream closes or a process exits. A later request launches one replacement process; an old reader can no longer clear the replacement's state.
- The TUI binds one Chat session to each backend generation. Before dispatching another turn or review it checks the process generation, reloads the backend's runtime snapshot and model status, creates a fresh session, clears non-restorable review state, and explicitly warns that old in-memory conversation context was lost.
- Only a definitive `not_found` session response is automatically retried, once, after a new session is created. A transport timeout or uncertain error is **not** replayed: the user keeps the draft and can choose whether to resend.
- The active provider determines the actual AI client and API key. A cloud key is not copied into Ollama on a Local/Offline switch. Offline selects a local provider rather than merely changing a strategy label. An explicit provider environment override rebuilds its endpoint and default model, avoiding the old `local` badge / DeepSeek route mismatch.
- Verified: Python full suite, Bun subprocess-kill/restart test, one-shot recovery/ambiguous-error tests, and TypeScript typecheck. Durable transcript restoration and an in-app cloud-provider configuration flow remain separate work.
