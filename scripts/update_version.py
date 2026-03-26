import re
import sys
from pathlib import Path


def update_version(file_path_str, new_version):
    file_path = Path(file_path_str)
    if not file_path.is_file():
        print(f"❌ Error: File not found at {file_path}")
        return False

    try:
        content = file_path.read_text(encoding="utf-8")
        # Matches version = "x.y.z" or "x.y.z-dev.1"
        version_pattern = r'(version\s*=\s*["\'])([^"\']+)(["\'])'
        new_content, num_replacements = re.subn(
            version_pattern, rf"\g<1>{new_version}\g<3>", content, count=1
        )

        if num_replacements == 0:
            for section in ["[tool.poetry]", "[project]"]:
                if section in content:
                    new_content = content.replace(
                        section, f'{section}\nversion = "{new_version}"'
                    )
                    file_path.write_text(new_content, encoding="utf-8")
                    return True
            return False

        file_path.write_text(new_content, encoding="utf-8")
        print(f"✅ Patched {file_path.name} -> {new_version}")
        return True
    except Exception as e:
        print(f"❌ Error: {e}")
        return False


if __name__ == "__main__":
    if len(sys.argv) < 3:
        sys.exit(1)
    new_ver, files = sys.argv[1], sys.argv[2:]
    sys.exit(0 if all(update_version(f, v) for v in [new_ver] for f in files) else 1)
