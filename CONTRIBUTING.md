# Contributing to Auto-Scout

Auto-Scout is maintained around a companion-first ROS1 architecture. Contributions should reinforce that shape rather than reintroduce older assumptions about a full Noetic-era autonomy stack running directly on the Scout.

## Development Setup

### Baseline assumptions
- Any Unix-like machine with `python3` and `git` is enough for repo validation work.
- The target companion runtime is still Ubuntu 18.04 + ROS Melodic.
- Ubuntu 16.04 + ROS Kinetic is an acceptable fallback for older ROS1 environments.
- Do not assume ROS Noetic or a Scout-only deployment path unless you are explicitly updating the documented architecture.

### Local setup
```bash
git clone <repository-url>
cd auto-scout
python3 -m pip install -r requirements.txt
```

If you want a catkin workspace for launch-file testing:

```bash
mkdir -p ~/catkin_ws/src
ln -s "$(pwd)" ~/catkin_ws/src/auto-scout
cd ~/catkin_ws
catkin_make
source devel/setup.bash
```

## Supported Interfaces

These are the public entrypoints we actively support:

- `python3 check_scout_compatibility.py --mode {repo|runtime|all}`
- `./tools/deploy.sh <scout-ip> <user>`
- `config/scout_config.yaml`

Please avoid adding replacement wrappers, duplicate config templates, or one-off deployment helpers unless there is a clear long-term need.

## Testing

Run the lightweight checks first:

```bash
python3 check_scout_compatibility.py --mode repo
python3 -m pytest tests/test_validation_cli.py
python3 -m py_compile $(find src tests tools -name '*.py')
```

Notes:

- `tests/test_validation_cli.py` is the canonical regression suite for the validator.
- The repo does not currently maintain broad local unit coverage for ROS runtime behavior.
- Hardware or ROS-graph verification should be treated as manual validation unless you are adding a durable automated test path.

## Code Guidelines

- Follow normal Python style and keep code readable without depending on framework magic.
- Prefer small, explicit modules over broad convenience layers.
- Keep configuration in `config/scout_config.yaml` rather than scattering parallel defaults across docs, scripts, and examples.
- When adding ROS launch or runtime behavior, keep Scout-side work lightweight and put heavier autonomy assumptions on the companion side.
- Remove dead code and outdated docs when they stop matching the supported architecture.

## Documentation

- Update `README.md` when the supported architecture or entrypoints change.
- Keep operational details in `docs/`.
- Do not add milestone reports or “complete” status writeups as permanent repo docs; git history is enough for that.

## Pull Requests

- Keep each PR focused on one cleanup, behavior change, or validation improvement.
- Include the exact commands you ran to verify the change.
- Call out any remaining manual or hardware-dependent verification gaps.
- Prefer updating existing docs and scripts over creating parallel alternatives.

## Help

- Open an issue for bugs or architecture mismatches.
- Open a PR directly for straightforward cleanup or documentation fixes.
