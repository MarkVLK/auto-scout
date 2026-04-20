"""Network and SSH validation helpers for Scout and companion roles."""

import ipaddress
import os
import re
import socket
from urllib.parse import urlparse

from auto_scout.command_runner import CommandRunner
from auto_scout.command_runner import DEFAULT_SSH_CONNECT_TIMEOUT
from auto_scout.site_config import normalize_ssh_auth_mode
from auto_scout.site_config import role_config


PLACEHOLDER_MARKER = ".invalid"
HOSTNAME_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


def is_placeholder(value):
    """Return whether a value still uses the generated placeholder marker."""
    return PLACEHOLDER_MARKER in str(value or "")


def validate_host_syntax(value):
    """Return ``None`` when the host/IP looks valid, else an error string."""
    host = str(value or "").strip()
    if not host:
        return "is empty"
    if is_placeholder(host):
        return "still uses the generated placeholder '{}'".format(host)

    try:
        ipaddress.ip_address(host)
        return None
    except ValueError:
        pass

    if host.endswith(".") or ".." in host or not HOSTNAME_PATTERN.match(host):
        return "is not a valid IP address or hostname: '{}'".format(host)
    return None


def _default_resolver(host):
    socket.getaddrinfo(host, None)


def _default_connector(host, port, timeout):
    handle = socket.create_connection((host, int(port)), timeout=timeout)
    handle.close()


def parse_ros_master_uri(value):
    """Return ``(parsed, error)`` for a ROS master URI."""
    uri = str(value or "").strip()
    if not uri:
        return None, "is empty"
    if is_placeholder(uri):
        return None, "still uses the generated placeholder '{}'".format(uri)

    parsed = urlparse(uri)
    if not parsed.scheme:
        return None, "must include a scheme such as http://"
    if not parsed.hostname:
        return None, "must include a hostname"
    try:
        port = parsed.port
    except ValueError as exc:
        return None, str(exc)

    if port is None:
        if parsed.scheme == "http":
            port = 11311
        elif parsed.scheme == "https":
            port = 443
        else:
            return None, "must include an explicit port for scheme '{}'".format(parsed.scheme)

    return {
        "uri": uri,
        "scheme": parsed.scheme,
        "host": parsed.hostname,
        "port": int(port),
    }, None


def role_needs_network_prompt(role_settings):
    """Return whether a role is missing required saved network settings."""
    ssh = role_settings.get("ssh", {})
    auth = ssh.get("auth", {})
    ros = role_settings.get("ros", {})
    required_values = [
        ssh.get("host"),
        ssh.get("user"),
        ros.get("master_uri"),
        ros.get("advertise_host"),
    ]
    if any(not str(value or "").strip() or is_placeholder(value) for value in required_values):
        return True
    if normalize_ssh_auth_mode(auth.get("mode")) == "key" and not str(auth.get("key_path") or "").strip():
        return True
    return False


def validate_role_connectivity(
    role_name,
    role_settings,
    runner=None,
    resolver=None,
    connector=None,
    validate_ssh_auth=True,
    connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT,
    interactive=None,
):
    """Return a structured connectivity result for a single role."""
    result = {
        "role": role_name,
        "ok": False,
        "errors": [],
    }
    runner = runner or CommandRunner()
    resolver = resolver or _default_resolver
    connector = connector or _default_connector

    ssh = role_settings.get("ssh", {})
    ros = role_settings.get("ros", {})
    ssh_host = ssh.get("host")
    ssh_user = str(ssh.get("user") or "").strip()
    ssh_port = ssh.get("port", 22)
    auth = ssh.get("auth", {})

    try:
        auth_mode = normalize_ssh_auth_mode(auth.get("mode"))
    except ValueError as exc:
        result["errors"].append("{} ssh.auth.mode {}".format(role_name, exc))
        auth_mode = None

    if not ssh_user:
        result["errors"].append("{} ssh.user is empty".format(role_name))

    host_error = validate_host_syntax(ssh_host)
    if host_error:
        result["errors"].append("{} ssh.host {}".format(role_name, host_error))

    try:
        ssh_port = int(ssh_port)
        if ssh_port <= 0 or ssh_port > 65535:
            raise ValueError()
    except (TypeError, ValueError):
        result["errors"].append("{} ssh.port must be an integer between 1 and 65535".format(role_name))
        ssh_port = None

    key_path = str(auth.get("key_path") or "").strip()
    if auth_mode == "key":
        if not key_path:
            result["errors"].append("{} ssh.auth.key_path is required when ssh.auth.mode is 'key'".format(role_name))
        elif not os.path.exists(os.path.expanduser(key_path)):
            result["errors"].append(
                "{} ssh.auth.key_path does not exist on this machine: {}".format(role_name, key_path)
            )

    advertise_host = ros.get("advertise_host")
    advertise_error = validate_host_syntax(advertise_host)
    if advertise_error:
        result["errors"].append("{} ros.advertise_host {}".format(role_name, advertise_error))

    parsed_master_uri, master_error = parse_ros_master_uri(ros.get("master_uri"))
    if master_error:
        result["errors"].append("{} ros.master_uri {}".format(role_name, master_error))

    if not host_error:
        try:
            resolver(ssh_host)
        except (OSError, socket.gaierror) as exc:
            result["errors"].append("{} ssh.host '{}' did not resolve: {}".format(role_name, ssh_host, exc))
        else:
            if ssh_port is not None:
                try:
                    connector(ssh_host, ssh_port, connect_timeout)
                except OSError as exc:
                    result["errors"].append(
                        "{} ssh endpoint {}:{} was unreachable: {}".format(role_name, ssh_host, ssh_port, exc)
                    )

    if not advertise_error:
        try:
            resolver(advertise_host)
        except (OSError, socket.gaierror) as exc:
            result["errors"].append(
                "{} ros.advertise_host '{}' did not resolve: {}".format(role_name, advertise_host, exc)
            )

    if parsed_master_uri:
        master_host = parsed_master_uri["host"]
        master_port = parsed_master_uri["port"]
        try:
            resolver(master_host)
        except (OSError, socket.gaierror) as exc:
            result["errors"].append(
                "{} ros.master_uri host '{}' did not resolve: {}".format(role_name, master_host, exc)
            )
        else:
            try:
                connector(master_host, master_port, connect_timeout)
            except OSError as exc:
                result["errors"].append(
                    "{} ros.master_uri endpoint {}:{} was unreachable: {}".format(
                        role_name,
                        master_host,
                        master_port,
                        exc,
                    )
                )

    if validate_ssh_auth and not result["errors"] and auth_mode is not None:
        if interactive is None:
            interactive = runner.tty_available()
        if auth_mode == "password" and not interactive:
            result["errors"].append(
                "{} SSH password auth requires an interactive terminal; rerun interactively or switch to key/agent auth.".format(
                    role_name
                )
            )
        else:
            ssh_result = runner.run(
                runner.build_ssh_command(
                    ssh,
                    "true",
                    batch_mode=(auth_mode != "password"),
                    connect_timeout=connect_timeout,
                ),
                check=False,
            )
            if not ssh_result.ok:
                stderr = ssh_result.stderr.strip() or ssh_result.stdout.strip() or "authentication failed"
                result["errors"].append("{} SSH auth check failed: {}".format(role_name, stderr))

    result["ok"] = not result["errors"]
    return result


def validate_site_connectivity(
    site_config,
    roles,
    runner=None,
    resolver=None,
    connector=None,
    validate_ssh_auth=True,
    connect_timeout=DEFAULT_SSH_CONNECT_TIMEOUT,
    interactive=None,
):
    """Return structured connectivity results for the requested roles."""
    payload = {
        "ok": True,
        "roles": {},
        "errors": [],
    }
    for role_name in roles:
        settings = role_config(site_config, role_name)
        result = validate_role_connectivity(
            role_name,
            settings,
            runner=runner,
            resolver=resolver,
            connector=connector,
            validate_ssh_auth=validate_ssh_auth,
            connect_timeout=connect_timeout,
            interactive=interactive,
        )
        payload["roles"][role_name] = result
        if not result["ok"]:
            payload["ok"] = False
            payload["errors"].extend(result["errors"])
    return payload
