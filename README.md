# Trellis Harness Overlay

> Development Distribution: this copy is being prepared for internal sharing. Stable business work remains on the separate `0.3.0` distribution.

Version `0.3.0` is an additive Harness Core for projects that already contain `.trellis/.version`. It never initializes or upgrades Trellis.

## Supported platforms

| Platform | Support | Command launcher |
| --- | --- | --- |
| Windows | Supported | `harness.cmd` |
| macOS 13+ | Supported on Intel and Apple Silicon | `harness` |
| Linux | Not currently supported | None |

## Prerequisites

- Git
- Python 3.9 or newer; Harness uses only the standard library
- Trellis CLI installed separately
- A Trellis project already initialized with `.trellis/.version`
- Codex opened on the project after installation so it can discover `.agents/skills/dev-*`

Harness does not install or initialize Trellis. Follow the official Trellis setup for the project first, then verify:

```powershell
Test-Path .trellis/.version
trellis --version
```

On macOS, run the equivalent checks in Terminal:

```sh
test -f .trellis/.version
trellis --version
```

The currently tested project versions are Trellis `0.6.12` and `0.6.15`; the currently tested CLI version is `0.6.15`.

## Windows: clone and register the command

After cloning this repository, run the following from the cloned directory:

```powershell
$harnessRoot = (Get-Location).Path

# Current PowerShell session only.
$env:Path = "$harnessRoot;$env:Path"

# Optional: persist the directory in the current user's PATH.
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Where-Object { $_ }
if ($userPath -notcontains $harnessRoot) {
  [Environment]::SetEnvironmentVariable('Path', (($userPath + $harnessRoot) -join ';'), 'User')
}
```

Open a new PowerShell window after persistent registration and verify:

```powershell
Get-Command harness
where.exe harness
```

To remove this clone from the current user's PATH:

```powershell
$harnessRoot = 'C:\path\to\trellis-harness'
$userPath = [Environment]::GetEnvironmentVariable('Path', 'User') -split ';' | Where-Object { $_ -and $_ -ne $harnessRoot }
[Environment]::SetEnvironmentVariable('Path', ($userPath -join ';'), 'User')
```

The Windows wrapper tries `python` first and `py` second. If neither is available, it exits with a clear prerequisite error. No PATH change is made automatically.

## macOS: clone and register the command

From the cloned directory:

```sh
chmod +x ./harness

# Current Terminal session only.
export PATH="$(pwd):$PATH"

command -v python3
command -v harness
```

If `python3` is not available, install Python 3.9 or newer using the approved Python installer or package manager for the Mac, then reopen Terminal. The launcher tries `python3` first and `python` second.

To persist the command for zsh, add the clone directory to `~/.zshrc` using its absolute path:

```sh
echo 'export PATH="/absolute/path/to/trellis-harness:$PATH"' >> ~/.zshrc
source ~/.zshrc
command -v harness
```

To remove it, delete that export line from `~/.zshrc` and run `source ~/.zshrc` again. No shell configuration is changed automatically.

You can also run the launcher without PATH registration:

```sh
./harness status --project /absolute/path/to/project
```

## Daily usage

```text
dev-grill "<new requirement>"
dev-grill resume <intake-path>
dev-start <requirement>
dev-verify fast
dev-checkpoint
dev-resume <task-path>
dev-review <task-path>
dev-verify full
```

`dev-grill` interviews one material product decision at a time and writes a
requirement intake. It stops after restoring or updating that intake; it does
not create a Task or execute implementation. When the intake says `READY`,
explicitly pass it to `dev-start <intake-path>` to create the formal Task.

## Distribution commands

Use the registered command, or call the platform launcher directly from this directory. The tool has no third-party dependencies.

```text
harness status --project <project>
harness install --project <project> --profile nextjs
harness sync --project <project>
harness status-all <workspace-root>
harness sync-all <workspace-root>
```

`install` requires an initialized Trellis project and a supported Trellis project version. A profile is copied only when explicitly selected and the project has no `.trellis/harness/quality-gates.json`. Profiles select deterministic quality gates plus the `dev-review` and `dev-grill` stack profiles. `sync` and `sync-all` update only the Core paths listed in `manifest.json`; they preserve profiles, Tasks, handoffs, intake/verification/review artifacts, Journal, runtime, business specs, and `.trellis/.template-hashes.json`. Existing custom profiles without `review.profile` or `grill.profile` remain untouched; the skills detect the supported stack from `package.json` when needed.

Locally modified Core files stop install/sync before writes. Use `--force` only to replace manifest-managed Core files; it never overwrites a profile or project data.

After install, reopen the project in Codex if the six `dev-*` Skills are not immediately visible. `harness status --project <project>` reports the installed Harness version, Trellis project version, profile, compatibility state, and managed Core state.

## Separate lifecycles

Official Trellis and this Overlay have independent versions and commands:

```text
trellis upgrade             # global official CLI
trellis update              # official files in one project
trellis update --migrate    # only when official Trellis requires migration
harness sync                # custom Harness Core only
```

Do not treat the Harness version as a Trellis version. Harness commands never invoke `trellis upgrade`, `trellis update`, or `trellis update --migrate`.
