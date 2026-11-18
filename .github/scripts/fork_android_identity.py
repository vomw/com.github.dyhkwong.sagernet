#!/usr/bin/env python3

import argparse
import re
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PACKAGE_PROPERTIES = ROOT / "version.properties"
APP_SOURCE = ROOT / "app" / "src" / "main"
RESOURCE_DIRECTORY = APP_SOURCE / "res"
APP_GRADLE_FILE = ROOT / "app" / "build.gradle.kts"
MANIFEST_FILE = APP_SOURCE / "AndroidManifest.xml"
TEXT_EXTENSIONS = {".java", ".kt", ".xml"}


def fail(message: str) -> None:
    raise SystemExit(message)


def replace_file(path: Path, content: str, dry_run: bool) -> None:
    if not dry_run:
        path.write_text(content, encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--suffix", required=True)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    suffix = args.suffix
    if not re.fullmatch(r"(?:\.[a-z][a-z0-9_]*)+", suffix):
        fail(f"invalid Android package suffix: {suffix}")

    package_properties = PACKAGE_PROPERTIES.read_text(encoding="utf-8")
    package_match = re.search(r"^PACKAGE_NAME=([A-Za-z][A-Za-z0-9_.]*)$", package_properties, re.MULTILINE)
    if package_match is None:
        fail("version.properties must contain exactly one PACKAGE_NAME entry")

    original_package = package_match.group(1)
    base_package = original_package.removesuffix(suffix)
    if base_package == original_package:
        fork_package = f"{original_package}{suffix}"
    else:
        fork_package = original_package
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+", fork_package):
        fail(f"invalid Android application ID: {fork_package}")

    namespace_match = re.search(r"^\s*namespace\s*=\s*\"([^\"]+)\"", APP_GRADLE_FILE.read_text(encoding="utf-8"), re.MULTILINE)
    if namespace_match is None:
        fail("unable to find the Android namespace")
    namespace = namespace_match.group(1)

    updated_properties, property_replacements = re.subn(
        r"^PACKAGE_NAME=[A-Za-z][A-Za-z0-9_.]*$",
        f"PACKAGE_NAME={fork_package}",
        package_properties,
        flags=re.MULTILINE,
    )
    if property_replacements != 1:
        fail("version.properties must contain exactly one PACKAGE_NAME entry")
    replace_file(PACKAGE_PROPERTIES, updated_properties, args.dry_run)

    hard_coded_replacements = 0
    for path in APP_SOURCE.rglob("*"):
        if not path.is_file() or path.suffix not in TEXT_EXTENSIONS:
            continue
        content = path.read_text(encoding="utf-8")
        updated_content, replacements = re.subn(
            rf"(?<![A-Za-z0-9_.]){re.escape(base_package)}(?![A-Za-z0-9_.])",
            fork_package,
            content,
        )
        if replacements:
            hard_coded_replacements += replacements
            replace_file(path, updated_content, args.dry_run)
    if not args.dry_run:
        original_package_pattern = re.compile(
            rf"(?<![A-Za-z0-9_.]){re.escape(base_package)}(?![A-Za-z0-9_.])"
        )
        for path in APP_SOURCE.rglob("*"):
            if path.is_file() and path.suffix in TEXT_EXTENSIONS:
                if original_package_pattern.search(path.read_text(encoding="utf-8")):
                    fail(f"unsuffixed application ID remains in {path.relative_to(ROOT)}")

    labels_changed = 0
    labels_found = 0
    default_label_found = False
    for path in RESOURCE_DIRECTORY.glob("values*/strings.xml"):
        content = path.read_text(encoding="utf-8")

        def replace_label(match: re.Match[str]) -> str:
            nonlocal labels_changed, labels_found, default_label_found
            if path.parent.name == "values":
                default_label_found = True
            labels_found += 1
            label = match.group(2).strip()
            if not label.endswith(suffix):
                label = f"{label}{suffix}"
                labels_changed += 1
            return f"{match.group(1)}{label}{match.group(3)}"

        updated_content = re.sub(
            r"(<string\s+name=\"app_name\"[^>]*>)(.*?)(</string>)",
            replace_label,
            content,
            flags=re.DOTALL,
        )
        replace_file(path, updated_content, args.dry_run)

    if not default_label_found:
        fail("default app_name resource not found")
    if labels_found == 0:
        fail("app_name resource not found")

    manifest = MANIFEST_FILE.read_text(encoding="utf-8")
    for required_value in ("${applicationId}.SERVICE", "${applicationId}.cache", "${applicationId}.androidx-startup", '@string/app_name'):
        if required_value not in manifest:
            fail(f"manifest is missing required package-scoped value: {required_value}")
    if namespace == fork_package:
        fail("Android namespace must remain distinct from the fork application ID")

    print(f"Fork application ID: {fork_package}")
    print(f"Fork label suffix: {suffix}")
    print(f"Hard-coded package references updated: {hard_coded_replacements}")


if __name__ == "__main__":
    main()
