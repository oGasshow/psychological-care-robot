#!/usr/bin/env bash
set -euo pipefail
if [ "$(id -u)" -ne 0 ]; then echo 'Run with sudo.'; exit 1; fi
if [ "$(uname -m)" != 'aarch64' ]; then echo 'Requires 64-bit ARM Raspberry Pi OS.'; exit 1; fi
BUNDLE="$(cd "$(dirname "$0")/../.." && pwd)"
APP=/opt/robot-care-edge
CONF=/etc/robot-care-edge
apt-get update -qq
apt-get install -y ca-certificates curl xz-utils openssh-client libpq5
id careedge >/dev/null 2>&1 || useradd --system --create-home --home-dir "$APP" --shell /usr/sbin/nologin careedge
install -d -m 0755 "$APP"
cp -a "$BUNDLE/backend" "$BUNDLE/frontend" "$BUNDLE/deploy" "$APP/"
install -d -m 0700 -o careedge -g careedge "$CONF"
for name in edge.env edge_ed25519 known_hosts connection.env; do
  install -m 0600 -o careedge -g careedge "$BUNDLE/private/$name" "$CONF/$name"
done
export UV_UNMANAGED_INSTALL="$APP/.tools/bin"
export UV_PYTHON_INSTALL_DIR="$APP/python"
curl -fsSL https://astral.sh/uv/install.sh -o "$APP/install-uv.sh"
sh "$APP/install-uv.sh"
"$APP/.tools/bin/uv" python install 3.13
"$APP/.tools/bin/uv" venv "$APP/.venv" --python 3.13
"$APP/.tools/bin/uv" pip sync "$BUNDLE/requirements-server.txt" --python "$APP/.venv/bin/python"
if ! command -v node >/dev/null || [ "$(node -p 'Number(process.versions.node.split(".")[0])')" -lt 22 ]; then
  curl -fsSL https://nodejs.org/dist/v22.14.0/node-v22.14.0-linux-arm64.tar.xz -o "$APP/node.tar.xz"
  curl -fsSL https://nodejs.org/dist/v22.14.0/SHASUMS256.txt -o "$APP/node-sha.txt"
  (cd "$APP"; EXPECTED="$(awk '$2=="node-v22.14.0-linux-arm64.tar.xz" {print $1}' node-sha.txt)"; test -n "$EXPECTED"; printf '%s  node.tar.xz\n' "$EXPECTED" | sha256sum -c -)
  tar -xJf "$APP/node.tar.xz" -C "$APP"
  ln -sfn "$APP/node-v22.14.0-linux-arm64" "$APP/node"
else
  install -d "$APP/node/bin"
  ln -sfn "$(command -v node)" "$APP/node/bin/node"
  ln -sfn "$(command -v npm)" "$APP/node/bin/npm"
fi
export PATH="$APP/node/bin:$PATH"
chown -R careedge:careedge "$APP"
cd "$APP/frontend"
runuser -u careedge -- env PATH="$PATH" npm ci --no-audit --no-fund
runuser -u careedge -- env PATH="$PATH" BACKEND_URL=http://127.0.0.1:8000 NEXT_TELEMETRY_DISABLED=1 npm run build
for part in tunnel api worker web; do install -m 0644 "$APP/deploy/edge/robot-care-edge-$part.service" /etc/systemd/system/; done
systemctl daemon-reload
systemctl enable --now robot-care-edge-tunnel robot-care-edge-api robot-care-edge-worker robot-care-edge-web
printf '%s\n' 'Open http://127.0.0.1:3000/login in the Raspberry Pi browser.'
printf '%s\n' 'Authorize the microphone and verify microphone/speaker on this device.'
