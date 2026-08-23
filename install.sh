#!/bin/sh
# Novin CLI — local install on THIS machine.
#   curl -fsSL https://raw.githubusercontent.com/oherbert346-create/novin-cli/main/install.sh | sh
set -eu

REPO="${NOVIN_CLI_REPO:-oherbert346-create/novin-cli}"
BRANCH="${NOVIN_CLI_BRANCH:-main}"
NOVIN_HOME="${NOVIN_HOME:-$HOME/.novin}"
BIN_DIR="${NOVIN_BIN:-$HOME/.local/bin}"

echo
echo "Novin CLI"
echo "  Local terminal on this machine. Not a web console."
echo "  After install, run:  novin"
echo

if ! command -v python3 >/dev/null 2>&1; then
  echo "Python 3.9+ is required. Install python3, then run this again." >&2
  exit 1
fi

PY_OK="$(python3 -c 'import sys; print(int(sys.version_info >= (3, 9)))')"
if [ "$PY_OK" != "1" ]; then
  echo "Python 3.9+ is required." >&2
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl is required." >&2
  exit 1
fi

mkdir -p "$NOVIN_HOME" "$BIN_DIR"
VENV="$NOVIN_HOME/venv"

if [ ! -x "$VENV/bin/python" ]; then
  echo "Creating local venv at ${VENV}"
  python3 -m venv "$VENV"
fi

echo "Installing Novin into the local venv..."
"$VENV/bin/python" -m pip install -q --upgrade pip

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
curl -fsSL "https://codeload.github.com/${REPO}/tar.gz/refs/heads/${BRANCH}" -o "$TMP/novin.tar.gz"
tar -xzf "$TMP/novin.tar.gz" -C "$TMP"
SRC="$(find "$TMP" -maxdepth 1 -type d -name 'novin-cli-*' | head -n 1)"
if [ -z "$SRC" ] || [ ! -f "$SRC/pyproject.toml" ]; then
  echo "Could not unpack the Novin CLI package." >&2
  exit 1
fi
"$VENV/bin/python" -m pip install -q "$SRC"

cat > "$BIN_DIR/novin" <<EOF
#!/bin/sh
# Local Novin terminal. Does not start a server.
exec "${VENV}/bin/novin" "\$@"
EOF
chmod +x "$BIN_DIR/novin"

echo
echo "Installed: ${BIN_DIR}/novin"
case ":$PATH:" in
  *":${BIN_DIR}:"*) ;;
  *)
    echo "Add this to your shell profile if 'novin' is not found:"
    echo "  export PATH=\"${BIN_DIR}:\$PATH\""
    ;;
esac
echo
echo "Run:  novin"
echo
