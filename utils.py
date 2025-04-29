#!/usr/bin/env python3

from pathlib import Path


def read_role(role_path: Path) -> str:
    role_content = "This is a list of the different files of the role."
    for entry in role_path.glob("**/*"):
        relative_path = entry.relative_to(role_path)
        if not entry.is_file():
            continue
        if str(relative_path).startswith("molecule"):
            continue
        if str(relative_path).startswith("test/"):
            continue
        if str(relative_path).startswith("tests/"):
            continue
        if str(relative_path).startswith("vars/"):
            continue
        if str(relative_path).startswith("."):
            continue
        if str(entry).startswith("."):
            continue
        if str(entry).endswith(".sh"):
            continue

        # Ignore the root directory
        if "/" not in str(relative_path):
            continue

        role_content += f"### File: {relative_path}\n\n"
        try:
            role_content += f"```\n{entry.read_text()}\n```\n"
        except UnicodeDecodeError:
            continue
    return role_content
