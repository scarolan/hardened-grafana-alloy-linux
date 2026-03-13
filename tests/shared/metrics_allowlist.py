"""Parse the allow-list from config.alloy so tests stay in sync with the config."""

import re
from pathlib import Path

# Path to the production config — check multiple locations to work both
# locally (relative to repo root) and inside Docker containers.
_candidates = [
    Path(__file__).resolve().parents[2] / "config.alloy",  # repo root
    Path.cwd() / "config.alloy",                           # Docker /tests/config.alloy
]
CONFIG_PATH = next((p for p in _candidates if p.exists()), _candidates[0])


def parse_allowlist(config_path=CONFIG_PATH):
    """Extract the set of metric names from the Layer 1 allow-list in config.alloy."""
    text = config_path.read_text()

    # Find the join([...], "|") block in the first rule (Layer 1 keep rule)
    # We look for quoted strings inside the join() call
    # The block starts after 'regex = join([' and ends at '], "|")'
    match = re.search(
        r'regex\s*=\s*join\(\[\s*(.*?)\s*\],\s*"\|"\)',
        text,
        re.DOTALL,
    )
    if not match:
        raise ValueError("Could not find allow-list join() block in config.alloy")

    block = match.group(1)

    # Extract all quoted metric names (ignore comments)
    metrics = set()
    for line in block.split("\n"):
        line = line.strip()
        # Skip comment-only lines
        if line.startswith("//"):
            continue
        # Extract quoted strings
        for m in re.finditer(r'"([^"]+)"', line):
            name = m.group(1)
            # Skip anything that looks like a regex operator rather than a metric name
            if not re.match(r'^[a-zA-Z_][a-zA-Z0-9_]*$', name):
                continue
            metrics.add(name)

    return metrics


# Pre-parsed for import convenience
ALLOWLIST = parse_allowlist()

if __name__ == "__main__":
    print(f"Allow-list contains {len(ALLOWLIST)} metrics:")
    for m in sorted(ALLOWLIST):
        print(f"  {m}")
