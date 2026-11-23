#!/usr/bin/env bash
# Install / refresh the Wi-Fi fallback hotspot service (ops/netwatch.py):
# when this box cannot reach any network it opens an open "ScenePlay-XXXX"
# hotspot, and a phone joining it is sent to /setup/wifi to pick the real Wi-Fi.
#
# Raspberry Pi only by default (same rule as the watchdog: a desktop/dev box
# must not grow a hotspot when its Wi-Fi drops). --force installs it on any
# Linux box. Needs NetworkManager (Raspberry Pi OS Bookworm or newer); older
# dhcpcd images are skipped with a message. Idempotent — safe to re-run.
#
# Usage: sudo bash supportFiles/setupNetwatch.sh [--force]
set -u

REPO="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
FORCE=0
[[ "${1:-}" == "--force" ]] && FORCE=1

if [[ $EUID -ne 0 ]]; then
    echo "Run as root: sudo bash $0 $*" >&2
    exit 1
fi

is_raspberry_pi() {
    [[ -e /proc/cpuinfo ]] || return 1
    case "$(uname -m)" in
        armv6l|armv7l|aarch64) return 0 ;;
        *) return 1 ;;
    esac
}

if [[ $FORCE -eq 0 ]] && ! is_raspberry_pi; then
    echo "Not a Raspberry Pi — skipping the Wi-Fi fallback hotspot (use --force to install it anyway)."
    exit 0
fi
if ! systemctl is-active --quiet NetworkManager; then
    echo "NetworkManager is not running (older OS such as Bullseye?) — skipping the Wi-Fi fallback hotspot."
    echo "  It needs Raspberry Pi OS Bookworm or newer."
    exit 0
fi
if ! nmcli -t -f TYPE device 2>/dev/null | grep -qx wifi; then
    echo "No Wi-Fi adapter found — skipping the Wi-Fi fallback hotspot."
    exit 0
fi

# NetworkManager's hotspot ("shared" IPv4) runs its own dnsmasq from
# dnsmasq-base (NOT the dnsmasq service package); iw counts connected phones.
for pkg in dnsmasq-base iw; do
    dpkg -s "$pkg" >/dev/null 2>&1 || apt-get -y install "$pkg" >/dev/null 2>&1 \
        || echo "WARNING: could not install $pkg"
done

# Captive DNS: only the hotspot's dnsmasq reads dnsmasq-shared.d.
mkdir -p /etc/NetworkManager/dnsmasq-shared.d
cat > /etc/NetworkManager/dnsmasq-shared.d/sceneplay-captive.conf <<'CONF'
# ScenePlay fallback hotspot (supportFiles/setupNetwatch.sh): every name
# resolves to this box so a phone's connectivity probe opens /setup/wifi.
address=/#/10.42.0.1
CONF

# nginx: the probe redirects. The include is a glob, so the ScenePlay site
# still loads on boxes where this snippet was never installed.
if [[ -d /etc/nginx ]]; then
    mkdir -p /etc/nginx/snippets
    cp "$REPO/supportFiles/sceneplay-captive.conf" /etc/nginx/snippets/sceneplay-captive.conf
    CONF=/etc/nginx/sites-available/default
    if [[ -f "$CONF" ]] && head -1 "$CONF" | grep -q '^#ScenePlay' && ! grep -q 'sceneplay-captive' "$CONF"; then
        cp "$CONF" "$CONF.bak.$(date +%s)"
        sed -i '0,/server {/s//server {\n\t# Wi-Fi fallback hotspot: phone connectivity probes -> \/setup\/wifi\n\tinclude snippets\/sceneplay-captive*.conf;/' "$CONF"
    fi
    if nginx -t >/dev/null 2>&1; then
        systemctl reload nginx 2>/dev/null || true
    else
        echo "WARNING: nginx -t failed after adding the captive snippet — check $CONF"
    fi
fi

UNIT=/etc/systemd/system/sceneplay_netwatch.service
sed -e "s|@REPO@|$REPO|g" "$REPO/supportFiles/sceneplay_netwatch.service" > "$UNIT"
systemctl daemon-reload
systemctl enable sceneplay_netwatch.service >/dev/null 2>&1
systemctl restart sceneplay_netwatch.service
echo "Wi-Fi fallback hotspot installed (sceneplay_netwatch.service)."
