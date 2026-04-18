#!/usr/bin/env python3
"""
Small YAML fallback for Scout deployments where PyYAML is unavailable.

This parser intentionally supports only the subset of YAML used in this repo:

- dictionaries with indentation-based nesting
- lists introduced with `-`
- list items that are scalars or dictionaries
- quoted strings
- booleans, nulls, integers, floats
- inline lists like `[a, b, c]`

It is not a general YAML implementation, but it is strong enough for
`config/scout_config.yaml` and the deployment helpers that depend on it.
"""

import json


class YAMLFallback:
    """Basic YAML parser fallback for simple repository configs."""

    @staticmethod
    def _strip_comments(line):
        """Remove trailing comments when they are not inside quotes."""
        in_single = False
        in_double = False

        for index, char in enumerate(line):
            if char == "'" and not in_double:
                in_single = not in_single
            elif char == '"' and not in_single:
                in_double = not in_double
            elif char == "#" and not in_single and not in_double:
                return line[:index].rstrip()

        return line.rstrip()

    @staticmethod
    def _preprocess(file_content):
        """Return significant `(indent, text)` tuples."""
        if hasattr(file_content, "read"):
            raw_lines = file_content.read().splitlines()
        else:
            raw_lines = str(file_content).splitlines()

        result = []
        for raw_line in raw_lines:
            if not raw_line.strip():
                continue

            cleaned = YAMLFallback._strip_comments(raw_line)
            if not cleaned.strip():
                continue

            indent = len(cleaned) - len(cleaned.lstrip(" "))
            text = cleaned.strip()
            result.append((indent, text))
        return result

    @staticmethod
    def _parse_scalar(value):
        """Parse a scalar value into a Python object."""
        if value == "":
            return ""

        lowered = value.lower()
        if lowered == "true":
            return True
        if lowered == "false":
            return False
        if lowered in ["null", "none", "~"]:
            return None

        if value.startswith('"') and value.endswith('"'):
            return value[1:-1]
        if value.startswith("'") and value.endswith("'"):
            return value[1:-1]

        if value.startswith("[") and value.endswith("]"):
            inner = value[1:-1].strip()
            if not inner:
                return []
            return [YAMLFallback._parse_scalar(item.strip()) for item in inner.split(",")]

        try:
            if value.startswith("0") and value not in ["0", "0.0"] and not value.startswith("0."):
                raise ValueError
            return int(value)
        except ValueError:
            pass

        try:
            return float(value)
        except ValueError:
            pass

        return value

    @staticmethod
    def _parse_block(lines, index, indent):
        """Parse either a mapping or a sequence at a given indentation level."""
        if index >= len(lines):
            return None, index

        current_indent, current_text = lines[index]
        if current_indent < indent:
            return None, index
        if current_indent > indent:
            indent = current_indent

        if current_text.startswith("- "):
            return YAMLFallback._parse_sequence(lines, index, indent)
        return YAMLFallback._parse_mapping(lines, index, indent)

    @staticmethod
    def _parse_mapping(lines, index, indent):
        """Parse a YAML mapping."""
        mapping = {}

        while index < len(lines):
            current_indent, current_text = lines[index]
            if current_indent < indent:
                break
            if current_indent > indent:
                break
            if current_text.startswith("- "):
                break
            if ":" not in current_text:
                index += 1
                continue

            key, value = current_text.split(":", 1)
            key = key.strip()
            value = value.strip()

            if value == "":
                index += 1
                if index < len(lines) and lines[index][0] > current_indent:
                    child, index = YAMLFallback._parse_block(lines, index, lines[index][0])
                    mapping[key] = child
                else:
                    mapping[key] = {}
            else:
                mapping[key] = YAMLFallback._parse_scalar(value)
                index += 1

        return mapping, index

    @staticmethod
    def _parse_sequence(lines, index, indent):
        """Parse a YAML sequence."""
        sequence = []

        while index < len(lines):
            current_indent, current_text = lines[index]
            if current_indent < indent:
                break
            if current_indent != indent or not current_text.startswith("- "):
                break

            item_text = current_text[2:].strip()
            index += 1

            if item_text == "":
                if index < len(lines) and lines[index][0] > current_indent:
                    child, index = YAMLFallback._parse_block(lines, index, lines[index][0])
                    sequence.append(child)
                else:
                    sequence.append(None)
                continue

            if ":" in item_text:
                key, value = item_text.split(":", 1)
                key = key.strip()
                value = value.strip()
                item = {key: YAMLFallback._parse_scalar(value) if value else None}

                if index < len(lines) and lines[index][0] > current_indent:
                    child, index = YAMLFallback._parse_block(lines, index, lines[index][0])
                    if isinstance(child, dict):
                        if item[key] is None:
                            item[key] = {}
                        if isinstance(item[key], dict):
                            item[key].update(child)
                        else:
                            item.update(child)
                    else:
                        item[key] = child

                sequence.append(item)
                continue

            sequence.append(YAMLFallback._parse_scalar(item_text))

        return sequence, index

    @staticmethod
    def load(file_content):
        """Parse supported YAML content into Python objects."""
        lines = YAMLFallback._preprocess(file_content)
        if not lines:
            return {}

        parsed, _ = YAMLFallback._parse_block(lines, 0, lines[0][0])
        return parsed

    @staticmethod
    def safe_load(file_content):
        """Alias for `load()` to match the PyYAML API."""
        return YAMLFallback.load(file_content)


def load_config_fallback(config_path):
    """Load Scout configuration with PyYAML when present, otherwise fallback."""
    try:
        import yaml

        with open(config_path, "r", encoding="utf-8") as handle:
            return yaml.safe_load(handle)
    except ImportError:
        with open(config_path, "r", encoding="utf-8") as handle:
            return YAMLFallback.safe_load(handle)
    except Exception:
        return None


if __name__ == "__main__":
    sample_yaml = """
    scout:
      name: "Scout Robot"
      enabled: true

    camera:
      device: "/dev/video0"
      width: 640
      height: 480
      fps: 30

    schedules:
      - name: morning_patrol
        active: false
      - name: evening_patrol
        active: true
    """

    print(json.dumps(YAMLFallback.safe_load(sample_yaml), indent=2, sort_keys=True))
