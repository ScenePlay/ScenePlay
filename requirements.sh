#!/bin/bash
#if xhost >& /dev/null ; then echo "Display exists"
sudo apt-get update
sudo apt-get -y upgrade
sudo apt-get -y install mpg123
sudo apt-get -y install python3-pip
sudo apt-get -y install python3-venv
sudo apt-get -y install mpv
# ffmpeg: yt-dlp extract/merge + relay_audio_stream encoding (ws.py warns at
# boot if it's missing; mpv does NOT provide the ffmpeg CLI)
sudo apt-get -y install ffmpeg
sudo apt-get -y install sqlite3
# socat is no longer needed (mpv IPC is written by Python since 2.0)
# pactl: relay_audio_stream's pulse backend (works against pipewire-pulse too;
# desktop images ship it, Lite/server images don't)
sudo apt-get -y install pulseaudio-utils
# requests for SYSTEM python3: sceneplay_watchdog_service.py runs outside the
# venv (systemd user service), and Lite images don't ship python3-requests
sudo apt-get -y install python3-requests

# Password-less sudo for the account that runs ScenePlay. The app calls sudo
# from a background service with no terminal (LED worker start/stop, Restart
# Computer, cron reboot, the nginx upload-size fix in Update): a password
# prompt there just fails silently and the LED strip never starts. One
# drop-in file, validated by visudo and removed again if it does not parse.
SUDOERS_FILE=/etc/sudoers.d/010_sceneplay
if [ ! -f "$SUDOERS_FILE" ]; then
    printf "Granting %s password-less sudo (%s)\n" "$USER" "$SUDOERS_FILE"
    echo "$USER ALL=(ALL) NOPASSWD:ALL" | sudo tee "$SUDOERS_FILE" >/dev/null
    sudo chmod 440 "$SUDOERS_FILE"
    if ! sudo visudo -c -f "$SUDOERS_FILE" >/dev/null; then
        sudo rm -f "$SUDOERS_FILE"
        printf "WARNING: sudoers rule rejected and removed — LED support needs password-less sudo (see README Step 2)\n"
    fi
fi

is_raspberry_pi() {
    local CPUINFO_PATH="/proc/cpuinfo"
    if [[ ! -e "$CPUINFO_PATH" ]]; then
        return 1
    fi
    # The Raspberry Pi's architecture is armv6l or aarch64 (for newer models).
    # The uname -m command returns the architecture of the system.
    # The case statement checks if the result is either armv6l or aarch64.
    # If it is, the function returns 0 (true), meaning this is a Raspberry Pi.
    # If it is not, the function returns 1 (false), meaning this is not a Raspberry Pi.
    case "$(uname -m)" in
        armv6l|aarch64) return 0 ;;
        *) return 1 ;;
    esac
}

python3 -m venv ~/ScenePlay
source ~/ScenePlay/bin/activate
BREAK_SYSTEM_PACKAGES=""
if is_raspberry_pi; then
    BREAK_SYSTEM_PACKAGES="--break-system-packages"
fi
pip3 install -r ~/ScenePlay/requirements.txt $BREAK_SYSTEM_PACKAGES

# LED support: led_Run.py runs via `sudo python3` (system Python, not the
# venv), so its libraries must be installed with sudo — but only on a Pi.
if is_raspberry_pi; then
    # The Pi LED stack pulls in lgpio. Newer Pi OS / Python releases have no prebuilt
    # wheel for it, so pip compiles it from source — which needs swig, the
    # lgpio headers and the Python headers ("command 'swig' failed: No such
    # file or directory" otherwise). python3-lgpio gives system Python a
    # ready-made copy so pip usually doesn't have to build it at all.
    sudo apt-get -y install swig liblgpio-dev python3-dev python3-lgpio
    # Plain install, never --force-reinstall: with --break-system-packages
    # that made pip tear out apt-managed modules (lgpio, RPi.GPIO, pyserial,
    # typing_extensions ...) and die half-way with "uninstall-no-record-file".
    sudo pip3 install rpi_ws281x adafruit-circuitpython-neopixel adafruit-blinka $BREAK_SYSTEM_PACKAGES
fi
deactivate

# Every shell script the app or the DM runs — git on Windows/exFAT checkouts
# and the zip download drop the executable bit. media/mpv.sh is the video
# player: without +x the video worker cannot start mpv at all.
chmod +x ~/ScenePlay/*.sh ~/ScenePlay/media/*.sh ~/ScenePlay/ops/*.sh ~/ScenePlay/scripts/*.sh \
         ~/ScenePlay/supportFiles/*.sh ~/ScenePlay/processMedia/*.sh 2>/dev/null

printf "Setup AutoStart\n"
cd ~/ScenePlay/supportFiles
source ~/ScenePlay/supportFiles/setupAutoStart.sh

