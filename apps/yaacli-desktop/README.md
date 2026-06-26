# YAACLI Desktop

YAACLI Desktop is the macOS workspace interface for the local YAACLI runtime.
It uses Tauri for native integration, React for presentation, and a bundled
Python sidecar for agent execution.

## MVP Product Decisions

| Decision                 | MVP value                                                          |
| ------------------------ | ------------------------------------------------------------------ |
| Public name              | YAACLI Desktop                                                     |
| Bundle identifier        | `com.wh1isper.yaacli.desktop`                                      |
| Initial architecture     | Apple Silicon (`aarch64`)                                          |
| Minimum macOS version    | macOS 13                                                           |
| Release host             | GitHub Releases for `wh1isper/ya-mono`                             |
| Update channel           | `stable`                                                           |
| Closing the final window | Keep the app in the menu bar while a run is active; otherwise quit |

These values are release inputs rather than protocol behavior. Changing the
bundle identifier after public distribution requires an explicit migration for
Keychain access and updater identity.

## Development

Install workspace dependencies, then start the desktop application:

```bash
make desktop-install
make desktop-dev
```

Use `uv sync --package yaacli` when synchronizing the desktop runtime manually.
Running `uv sync --all-extras` at the workspace root targets only the root
project and removes dependencies needed by workspace packages. The YAACLI `rs`
extra is optional and is not required by the desktop runtime. Development
startup uses the already-synchronized `.venv` sidecar and never installs Python
packages while waiting for the protocol handshake.

Run focused checks:

```bash
make desktop-check
make desktop-rust-check
make desktop-test
make desktop-sidecar-build
make desktop-bundle
```

The frontend can be run without Tauri for layout work with
`corepack pnpm --dir apps/yaacli-desktop dev`. Runtime-dependent actions report
that the native bridge is unavailable in this mode.

The self-contained sidecar and bundle targets require Apple Silicon macOS.
`desktop-sidecar-build` performs a handshake smoke test with an empty environment;
`desktop-bundle` produces unsigned local `.app` and `.dmg` artifacts.

## Maintainer Documentation

- [Architecture and protocol](docs/architecture.md)
- [Security boundaries](docs/security.md)
- [Release, signing, notarization, and updates](docs/release.md)

## MVP Limitations

- Distribution targets Apple Silicon and macOS 13 or newer only.
- Only one workspace runtime and one active run are supervised per app process.
- The app uses the existing YAACLI transcript/config formats; there is no cloud sync.
- GitHub Releases is the only configured stable update channel.
- Public builds require repository-managed Apple and Tauri signing credentials.
