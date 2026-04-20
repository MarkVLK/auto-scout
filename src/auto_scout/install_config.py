"""Interactive and flag-driven helpers for install/deploy configuration."""

from copy import deepcopy
import sys

from auto_scout.site_config import (
    companion_storage_paths,
    companion_storage_root,
    companion_workspace_for_user,
    normalize_drive_model,
    role_config,
    scout_workspace_for_user,
)


def prompts_enabled(force_prompt=False, non_interactive=False):
    """Return whether interactive prompts should be used."""
    if non_interactive:
        return False
    return force_prompt or sys.stdin.isatty()


def _prompt(label, default):
    suffix = " [{}]".format(default) if default not in [None, ""] else ""
    value = input("{}{}: ".format(label, suffix)).strip()
    return value or default


def _prompt_int(label, default):
    while True:
        value = _prompt(label, default)
        try:
            return int(value)
        except (TypeError, ValueError):
            print("Please enter an integer value.")


def _prompt_choice(label, default, choices):
    normalized_choices = [str(item).lower() for item in choices]
    while True:
        value = str(_prompt(label, default)).strip().lower()
        if value in normalized_choices:
            return value
        print("Please choose one of: {}.".format(", ".join(normalized_choices)))


def _maybe_prompt(label, default, prompt=False, cast=None):
    if not prompt:
        return default
    value = _prompt(label, default)
    if cast is None:
        return value
    return cast(value)


def _default_workspace(role, existing_workspace, old_user, new_user):
    if role == "scout":
        previous_default = scout_workspace_for_user(old_user)
        if not existing_workspace or existing_workspace == previous_default:
            return scout_workspace_for_user(new_user)
        return existing_workspace

    previous_default = companion_workspace_for_user(old_user)
    if not existing_workspace or existing_workspace == previous_default:
        return companion_workspace_for_user(new_user)
    return existing_workspace


def configure_role(site_config, role, args, prompt=False):
    """Return an updated site config for the selected role."""
    config = deepcopy(site_config)
    role_settings = role_config(config, role)
    ssh_settings = role_settings.setdefault("ssh", {})

    role_settings["hostname"] = args.hostname or _maybe_prompt(
        "{} hostname label".format(role.capitalize()),
        role_settings.get("hostname"),
        prompt=prompt,
    )
    ssh_settings["host"] = args.ssh_host or _maybe_prompt(
        "{} SSH host".format(role.capitalize()),
        ssh_settings.get("host"),
        prompt=prompt,
    )

    old_user = ssh_settings.get("user")
    ssh_user = args.ssh_user or _maybe_prompt(
        "{} SSH user".format(role.capitalize()),
        old_user,
        prompt=prompt,
    )
    ssh_settings["user"] = ssh_user

    ssh_settings["port"] = (
        args.ssh_port
        if args.ssh_port is not None
        else _prompt_int("{} SSH port".format(role.capitalize()), ssh_settings.get("port", 22))
        if prompt
        else ssh_settings.get("port", 22)
    )

    workspace_default = _default_workspace(
        role,
        role_settings.get("workspace_dir"),
        old_user,
        ssh_user,
    )
    role_settings["workspace_dir"] = args.workspace_dir or _maybe_prompt(
        "{} workspace directory".format(role.capitalize()),
        workspace_default,
        prompt=prompt,
    )

    ros_settings = role_settings.setdefault("ros", {})
    ros_settings["master_uri"] = args.ros_master_uri or _maybe_prompt(
        "{} ROS master URI".format(role.capitalize()),
        ros_settings.get("master_uri"),
        prompt=prompt,
    )
    ros_settings["advertise_host"] = args.advertise_host or _maybe_prompt(
        "{} ROS advertised host".format(role.capitalize()),
        ros_settings.get("advertise_host"),
        prompt=prompt,
    )

    service_user_default = role_settings.get("service_user") or ssh_user
    role_settings["service_user"] = args.service_user or _maybe_prompt(
        "{} service user".format(role.capitalize()),
        service_user_default,
        prompt=prompt,
    )

    service_group_default = role_settings.get("service_group") or role_settings["service_user"]
    role_settings["service_group"] = args.service_group or _maybe_prompt(
        "{} service group".format(role.capitalize()),
        service_group_default,
        prompt=prompt,
    )

    if role == "companion":
        storage_root_default = companion_storage_root(role_settings)
        storage_root = args.storage_root or _maybe_prompt(
            "Companion storage root",
            storage_root_default,
            prompt=prompt,
        )
        role_settings["storage"] = companion_storage_paths(storage_root)
    else:
        devices = role_settings.setdefault("devices", {})
        motion = role_settings.setdefault("motion", {})
        devices["camera"] = args.camera_device or _maybe_prompt(
            "Scout camera device",
            devices.get("camera", "/dev/video0"),
            prompt=prompt,
        )
        devices["lidar"] = args.lidar_device or _maybe_prompt(
            "Scout lidar device",
            devices.get("lidar", "/dev/ttyS4"),
            prompt=prompt,
        )
        if args.drive_model:
            motion["drive_model"] = normalize_drive_model(args.drive_model)
        elif prompt:
            motion["drive_model"] = _prompt_choice(
                "Scout drive model (diff or omni)",
                motion.get("drive_model", "diff"),
                ["diff", "omni"],
            )
        else:
            motion["drive_model"] = normalize_drive_model(motion.get("drive_model"))

    return config
