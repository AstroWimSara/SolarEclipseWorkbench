#!/usr/bin/env bash
#
# Install or upgrade Solar Eclipse Workbench on macOS and Linux.
#
#   curl -LsSf https://raw.githubusercontent.com/AstroWimSara/SolarEclipseWorkbench/main/scripts/install.sh | bash
#
# or download this file and run  bash install.sh .  Run it as your normal user:
# it asks for your password (sudo) only for the Linux system packages and groups.
#
# What it does:
#   - installs uv (https://docs.astral.sh/uv/) if needed, and with it Solar
#     Eclipse Workbench in its own environment, with its own Python.  The
#     packages from PyPI include libgphoto2, GDAL and Qt, so on most machines
#     nothing else has to be installed;
#   - Linux: installs the few system packages still needed (gstreamer for the
#     voice prompts, the Qt display libraries, the gphoto2 command line tool
#     and its camera permissions), adds you to the plugdev and dialout groups,
#     and stops the desktop from claiming the cameras (gvfs);
#   - macOS older than 14 (Apple Silicon) or 15 (Intel): installs gphoto2 with
#     Homebrew, because there is no prebuilt gphoto2 package for those;
#   - adds the application and the wizard to the applications menu (Linux) or
#     to ~/Applications (macOS).
#
# Run it again at any time to upgrade Solar Eclipse Workbench.
#
# Options:
#   -y, --yes        do not ask before starting
#   --no-shortcuts   do not add menu entries or applications
#   --dry-run        only print what would be done
#   --uninstall      remove Solar Eclipse Workbench and its shortcuts
#   -h, --help       show this help
#
# This script has to keep working with the bash 3.2 that macOS ships.

set -euo pipefail

PACKAGE="solareclipseworkbench"
PYTHON_VERSION="3.12"
APP_NAME="Solar Eclipse Workbench"
README_URL="https://github.com/AstroWimSara/SolarEclipseWorkbench#installation-instructions"

ASSUME_YES=0
DRY_RUN=0
UNINSTALL=0
SHORTCUTS=1

# ---------------------------------------------------------------------------
# Output and helpers
# ---------------------------------------------------------------------------

if [ -t 1 ]; then
    BOLD=$(printf '\033[1m'); CYAN=$(printf '\033[36m'); GREEN=$(printf '\033[32m')
    YELLOW=$(printf '\033[33m'); RED=$(printf '\033[31m'); RESET=$(printf '\033[0m')
else
    BOLD=""; CYAN=""; GREEN=""; YELLOW=""; RED=""; RESET=""
fi

step() { printf '\n%s==> %s%s\n' "$CYAN$BOLD" "$1" "$RESET"; }
ok()   { printf '    %s%s%s\n' "$GREEN" "$1" "$RESET"; }
note() { printf '    %s%s%s\n' "$YELLOW" "$1" "$RESET"; }
die()  {
    printf '\n%sERROR: %s%s\n' "$RED" "$1" "$RESET" >&2
    printf 'See %s for the manual installation steps.\n' "$README_URL" >&2
    exit 1
}

usage() {
    if [ -f "$0" ]; then
        sed -n '3,/^# This script/p' "$0" | sed -e '$d' -e 's/^# \{0,1\}//'
    else
        printf 'Options: -y/--yes, --no-shortcuts, --dry-run, --uninstall, -h/--help\n'
    fi
}

# Run a command that changes the system, or only print it with --dry-run.
run() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '    [dry-run]'
        printf ' %q' "$@"
        printf '\n'
    else
        "$@"
    fi
}

run_as_root() {
    if [ "$(id -u)" = 0 ]; then run "$@"; else run sudo "$@"; fi
}

# Write stdin to a file, or only say so with --dry-run.
write_file() {
    if [ "$DRY_RUN" = 1 ]; then
        printf '    [dry-run] write %s:\n' "$1"
        sed 's/^/        | /'
    else
        cat > "$1"
    fi
}

# Ask a yes/no question on the terminal (also when this script is piped into bash).
confirm() {
    local answer=""
    if [ "$ASSUME_YES" = 1 ]; then return 0; fi
    if ! (exec < /dev/tty) 2> /dev/null; then return 0; fi   # no terminal: go ahead
    printf '%s [Y/n] ' "$1"
    read -r answer < /dev/tty || answer=""
    case "$answer" in [nN]*) return 1 ;; *) return 0 ;; esac
}

# version_ge 2.39 2.34  ->  true.  Compares dotted numbers (sort -V is not on every macOS).
version_ge() {
    local IFS=.
    # shellcheck disable=SC2206  # word splitting on dots is the point
    local a=($1) b=($2)
    local i x y
    for i in 0 1 2; do
        x=${a[$i]:-0}; y=${b[$i]:-0}
        x=${x%%[!0-9]*}; y=${y%%[!0-9]*}
        x=${x:-0}; y=${y:-0}
        if [ "$x" -gt "$y" ]; then return 0; fi
        if [ "$x" -lt "$y" ]; then return 1; fi
    done
    return 0
}

while [ $# -gt 0 ]; do
    case "$1" in
        -y|--yes) ASSUME_YES=1 ;;
        --dry-run) DRY_RUN=1 ;;
        --uninstall) UNINSTALL=1 ;;
        --no-shortcuts) SHORTCUTS=0 ;;
        -h|--help) usage; exit 0 ;;
        *) printf 'Unknown option: %s\n\n' "$1" >&2; usage >&2; exit 2 ;;
    esac
    shift
done

OS=$(uname -s)
ARCH=$(uname -m)
UV=""

# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

check_user() {
    if [ "$(id -u)" = 0 ] && [ "$DRY_RUN" = 0 ]; then
        die "Run this script as your normal user, not with sudo: it installs Solar Eclipse Workbench in your home folder and asks for your password when it needs to."
    fi
}

is_wsl() {
    [ -n "${WSL_DISTRO_NAME:-}" ] || grep -qi microsoft /proc/sys/kernel/osrelease 2> /dev/null
}

# Qt (PyQt6) is only published for 64-bit Linux, and needs a recent C library.
check_linux() {
    local min glibc
    case "$ARCH" in
        x86_64|amd64) min="2.34" ;;     # Ubuntu 22.04, Debian 12, Fedora 35 and newer
        aarch64|arm64) min="2.39" ;;    # Ubuntu 24.04, Debian 13, Raspberry Pi OS Trixie and newer
        *) die "There are no prebuilt Qt packages for $ARCH.  On a Raspberry Pi, install the 64-bit Raspberry Pi OS." ;;
    esac
    glibc=$(getconf GNU_LIBC_VERSION 2> /dev/null | awk '{print $2}') || glibc=""
    if [ -z "$glibc" ]; then
        die "This Linux does not use the GNU C library (glibc), which the prebuilt Qt packages need."
    fi
    if ! version_ge "$glibc" "$min"; then
        die "This Linux has glibc $glibc; the Qt packages for $ARCH need $min or newer (for example Ubuntu 24.04, Debian 13 or Raspberry Pi OS Trixie).  Please upgrade the operating system."
    fi
    ok "Linux $ARCH with glibc $glibc."
    if is_wsl; then
        note "This is WSL.  To use cameras, share them from Windows: see scripts/windows/install-sew.ps1."
    fi
}

# Prebuilt gphoto2 packages exist for macOS 14+ on Apple Silicon and 15+ on
# Intel.  On older versions pip builds gphoto2, which needs libgphoto2 from
# Homebrew and the Xcode command line tools.
MAC_BUILD_GPHOTO2=0
check_macos() {
    local version min
    version=$(sw_vers -productVersion)
    case "$ARCH" in
        arm64) min="14" ;;
        *) min="15" ;;
    esac
    if version_ge "$version" "$min"; then
        ok "macOS $version on $ARCH."
        return
    fi
    if ! version_ge "$version" "11"; then
        die "macOS $version is too old: Qt needs macOS 11 or newer."
    fi
    MAC_BUILD_GPHOTO2=1
    note "macOS $version on $ARCH: gphoto2 has to be built, which needs Homebrew and the Xcode command line tools."
}

# ---------------------------------------------------------------------------
# System packages
# ---------------------------------------------------------------------------

# gst-play-1.0 (gstreamer1.0-plugins-base-apps) plays the voice prompts; the gphoto2 package
# brings the udev rules that let the plugdev group use the cameras; the libxcb
# and GL libraries are what Qt needs to open windows, usually there already on a
# desktop.  exiftool reads the capture time of every raw format for sew_sort.
APT_PACKAGES="ca-certificates curl usbutils gphoto2 libimage-exiftool-perl \
gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-base-apps gstreamer1.0-plugins-good \
gstreamer1.0-pulseaudio \
libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 libxcb-randr0 \
libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 libgl1 libegl1 libfontconfig1 libdbus-1-3 \
fonts-noto-color-emoji"

install_linux_packages() {
    step "Installing the system packages"
    if ! command -v apt-get > /dev/null; then
        note "This is not a Debian, Ubuntu or Raspberry Pi OS system, so install these yourself:"
        note "  gphoto2, gstreamer with gst-play-1.0 and the good plugins, and the Qt xcb libraries"
        note "  (libxkbcommon-x11, xcb-util-cursor)."
        return
    fi
    run_as_root apt-get update
    # Package names change between releases; leave out the ones this release does not have.
    local pkg available=""
    for pkg in $APT_PACKAGES; do
        if apt-cache show "$pkg" > /dev/null 2>&1; then
            available="$available $pkg"
        else
            note "Skipping $pkg: not available in this release."
        fi
    done
    # shellcheck disable=SC2086  # one word per package
    run_as_root env DEBIAN_FRONTEND=noninteractive apt-get install -y $available
    ok "System packages installed."
}

NEEDS_RELOGIN=0
setup_linux_permissions() {
    step "Camera and GPS permissions"
    local group user
    user=$(id -un)
    # plugdev: the cameras without sudo; dialout: the USB GPS receiver.
    for group in plugdev dialout; do
        if ! getent group "$group" > /dev/null; then
            continue
        fi
        if id -nG "$user" | tr ' ' '\n' | grep -qx "$group"; then
            ok "You are in the $group group."
        else
            run_as_root usermod -aG "$group" "$user"
            ok "Added you to the $group group."
            NEEDS_RELOGIN=1
        fi
    done

    # The desktop's gvfs claims a camera as soon as it is connected, and then
    # gphoto2 cannot use it.  Masking the service stops it for good; do not
    # remove its execute bit instead, that makes the Files application hang.
    local unit="gvfs-gphoto2-volume-monitor.service"
    if ! command -v systemctl > /dev/null || ! systemctl --user list-unit-files "$unit" 2> /dev/null | grep -q "^$unit"; then
        return
    fi
    if [ "$(systemctl --user is-enabled "$unit" 2> /dev/null || true)" = "masked" ]; then
        ok "gvfs does not claim the cameras (already masked)."
    else
        run systemctl --user stop "$unit" || true
        if run systemctl --user mask "$unit"; then
            ok "gvfs no longer claims the cameras."
        else
            note "Could not mask $unit; run  systemctl --user mask $unit  yourself."
        fi
    fi
}

install_macos_prerequisites() {
    if [ "$MAC_BUILD_GPHOTO2" = 0 ]; then return; fi
    step "Installing gphoto2 with Homebrew"
    if ! xcode-select -p > /dev/null 2>&1; then
        run xcode-select --install || true
        die "Install the Xcode command line tools in the window that opened, then run this script again."
    fi
    local brew=""
    for brew in "$(command -v brew 2> /dev/null || true)" /opt/homebrew/bin/brew /usr/local/bin/brew; do
        if [ -n "$brew" ] && [ -x "$brew" ]; then break; fi
        brew=""
    done
    if [ -z "$brew" ]; then
        die "Homebrew is needed to build gphoto2 on this macOS version.  Install it from https://brew.sh and run this script again."
    fi
    run "$brew" install gphoto2 pkg-config
    # So that pip finds libgphoto2 when it builds gphoto2.
    export PATH="$(dirname "$brew"):$PATH"
    export PKG_CONFIG_PATH="$("$brew" --prefix)/lib/pkgconfig:${PKG_CONFIG_PATH:-}"
    ok "gphoto2 installed."
}

# ---------------------------------------------------------------------------
# uv and the application
# ---------------------------------------------------------------------------

find_uv() {
    local candidate
    for candidate in "$(command -v uv 2> /dev/null || true)" "${XDG_BIN_HOME:-$HOME/.local/bin}/uv" "$HOME/.cargo/bin/uv"; do
        if [ -n "$candidate" ] && [ -x "$candidate" ]; then
            UV="$candidate"
            return 0
        fi
    done
    return 1
}

install_uv() {
    step "Checking uv"
    if find_uv; then
        ok "uv is installed: $UV"
        return
    fi
    note "Installing uv."
    if [ "$DRY_RUN" = 1 ]; then
        printf '    [dry-run] curl -LsSf https://astral.sh/uv/install.sh | sh\n'
        UV="${XDG_BIN_HOME:-$HOME/.local/bin}/uv"
        return
    fi
    if command -v curl > /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    elif command -v wget > /dev/null; then
        wget -qO- https://astral.sh/uv/install.sh | sh
    else
        die "curl or wget is needed to install uv."
    fi
    find_uv || die "uv was installed, but cannot be found."
    ok "uv is installed: $UV"
}

is_installed() {
    [ -n "$UV" ] && [ -x "$UV" ] && "$UV" tool list 2> /dev/null | grep -q "^$PACKAGE "
}

install_app() {
    if is_installed; then
        step "Upgrading $APP_NAME"
        run "$UV" tool upgrade "$PACKAGE"
    else
        step "Installing $APP_NAME (this takes a few minutes the first time)"
        run "$UV" tool install --python "$PYTHON_VERSION" "$PACKAGE"
    fi
    # Puts the folder with sew and sew_wizard on the PATH of new terminals.
    run "$UV" tool update-shell > /dev/null 2>&1 || true
    ok "$APP_NAME is installed."
}

bin_dir() {
    if [ -n "$UV" ] && [ -x "$UV" ]; then
        "$UV" tool dir --bin 2> /dev/null && return
    fi
    printf '%s\n' "${XDG_BIN_HOME:-$HOME/.local/bin}"
}

# Prints the path of a file in the package's img folder, if it is there.
package_image() {
    local tool_dir
    [ -n "$UV" ] && [ -x "$UV" ] || return 1
    tool_dir=$("$UV" tool dir 2> /dev/null) || return 1
    set -- "$tool_dir/$PACKAGE"/lib/python*/site-packages/"$PACKAGE"/img/"$1"
    [ -e "$1" ] && printf '%s\n' "$1"
}

# ---------------------------------------------------------------------------
# Shortcuts
# ---------------------------------------------------------------------------

LINUX_APPS="$HOME/.local/share/applications"
LINUX_ICON="$HOME/.local/share/icons/hicolor/256x256/apps/$PACKAGE.png"
# Releases up to 2.0.0 have no sew.png, only logo.jpg.  Icon themes only take
# PNG and SVG, so the JPEG is referred to by its full path instead.
LINUX_ICON_JPG="$HOME/.local/share/$PACKAGE/sew.jpg"
MAC_APPS="$HOME/Applications"

# Menus and Launchpad cut names off after about 15 characters, so the shortcuts
# have to differ at the start: "Solar Eclipse Workbench Wizard" would show up
# as "Solar Eclipse W..." just like the application.
WIZARD_NAME="Eclipse Wizard"
SIMULATION_NAME="Eclipse Simulation"

desktop_entry() {   # name, command line (executable quoted), comment, icon
    cat << EOF
[Desktop Entry]
Type=Application
Version=1.0
Name=$1
Comment=$3
Exec=$2
Icon=$4
Terminal=false
Categories=Science;Astronomy;
Keywords=eclipse;sun;camera;gphoto2;astronomy;
EOF
}

install_linux_shortcuts() {
    step "Adding $APP_NAME to the applications menu"
    local bin icon icon_ref="$PACKAGE"
    bin=$(bin_dir)
    run mkdir -p "$LINUX_APPS" "$(dirname "$LINUX_ICON")"
    if icon=$(package_image sew.png); then
        run cp "$icon" "$LINUX_ICON"
        if [ -e "$LINUX_ICON_JPG" ]; then run rm -f "$LINUX_ICON_JPG"; fi
    elif icon=$(package_image logo.jpg); then
        run mkdir -p "$(dirname "$LINUX_ICON_JPG")"
        run cp "$icon" "$LINUX_ICON_JPG"
        icon_ref="$LINUX_ICON_JPG"
    else
        note "No icon found in the package; the menu entries get a generic icon."
    fi
    desktop_entry "$APP_NAME" "\"$bin/sew\"" "Plan and photograph solar eclipses" "$icon_ref" \
        | write_file "$LINUX_APPS/$PACKAGE.desktop"
    desktop_entry "$WIZARD_NAME" "\"$bin/sew_wizard\"" \
        "Solar Eclipse Workbench wizard: write a photography script" "$icon_ref" \
        | write_file "$LINUX_APPS/$PACKAGE-wizard.desktop"
    desktop_entry "$SIMULATION_NAME" "\"$bin/sew\" --sim" \
        "Solar Eclipse Workbench in simulation mode: rehearse a script at any time" "$icon_ref" \
        | write_file "$LINUX_APPS/$PACKAGE-simulation.desktop"
    if command -v update-desktop-database > /dev/null; then
        run update-desktop-database "$LINUX_APPS" > /dev/null 2>&1 || true
    fi
    if command -v gtk-update-icon-cache > /dev/null; then
        run gtk-update-icon-cache -q -t "$HOME/.local/share/icons/hicolor" > /dev/null 2>&1 || true
    fi
    ok "Added '$APP_NAME', '$WIZARD_NAME' and '$SIMULATION_NAME'."
}

info_plist() {   # name, identifier
    cat << EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>CFBundleName</key><string>$1</string>
    <key>CFBundleDisplayName</key><string>$1</string>
    <key>CFBundleIdentifier</key><string>$2</string>
    <key>CFBundleExecutable</key><string>launcher</string>
    <key>CFBundleIconFile</key><string>sew.icns</string>
    <key>CFBundlePackageType</key><string>APPL</string>
    <key>CFBundleVersion</key><string>1</string>
    <key>NSHighResolutionCapable</key><true/>
</dict>
</plist>
EOF
}

# Releases up to 2.0.0 have no sew.icns: build it from logo.jpg with the tools
# macOS ships (sips scales and converts, iconutil packs the sizes).
make_icns() {   # source image, destination .icns
    local tmp set size
    if [ "$DRY_RUN" = 1 ]; then
        printf '    [dry-run] make %s from %s\n' "$2" "$1"
        return 0
    fi
    tmp=$(mktemp -d) || return 1
    set="$tmp/sew.iconset"
    mkdir "$set"
    for size in 16 32 128 256; do
        sips -s format png -z "$size" "$size" "$1" --out "$set/icon_${size}x${size}.png" > /dev/null || return 1
        sips -s format png -z $((size * 2)) $((size * 2)) "$1" --out "$set/icon_${size}x${size}@2x.png" > /dev/null || return 1
    done
    iconutil -c icns "$set" -o "$2" || return 1
    rm -rf "$tmp"
}

# A small .app that starts the command, so it can go in the Dock and Launchpad.
mac_app() {   # name, identifier, executable, [option]
    local app="$MAC_APPS/$1.app" icon option="${4:+ $4}"
    run mkdir -p "$app/Contents/MacOS" "$app/Contents/Resources"
    info_plist "$1" "$2" | write_file "$app/Contents/Info.plist"
    # Apps started from the Finder get a minimal PATH; add Homebrew's for
    # 'command' lines in scripts.
    cat << EOF | write_file "$app/Contents/MacOS/launcher"
#!/bin/bash
export PATH="/opt/homebrew/bin:/usr/local/bin:\$PATH"
exec "$3"$option "\$@"
EOF
    run chmod +x "$app/Contents/MacOS/launcher"
    if icon=$(package_image sew.icns); then
        run cp "$icon" "$app/Contents/Resources/sew.icns"
    elif icon=$(package_image logo.jpg); then
        make_icns "$icon" "$app/Contents/Resources/sew.icns" \
            || note "Could not make the application icon; the Finder shows a generic one."
    fi
    run touch "$app"   # makes the Finder pick up the icon
}

install_macos_shortcuts() {
    step "Adding $APP_NAME to ~/Applications"
    local bin
    bin=$(bin_dir)
    mac_app "$APP_NAME" "com.github.astrowimsara.sew" "$bin/sew"
    mac_app "$WIZARD_NAME" "com.github.astrowimsara.sew-wizard" "$bin/sew_wizard"
    mac_app "$SIMULATION_NAME" "com.github.astrowimsara.sew-simulation" "$bin/sew" "--sim"
    # The name of the wizard before the shortcuts got distinct names.
    if [ -e "$MAC_APPS/$APP_NAME Wizard.app" ]; then run rm -rf "$MAC_APPS/$APP_NAME Wizard.app"; fi
    ok "Added '$APP_NAME', '$WIZARD_NAME' and '$SIMULATION_NAME' to $MAC_APPS."
}

# ---------------------------------------------------------------------------
# Uninstall
# ---------------------------------------------------------------------------

uninstall() {
    step "Removing $APP_NAME"
    find_uv || true
    if is_installed; then
        run "$UV" tool uninstall "$PACKAGE"
    else
        note "$APP_NAME is not installed with uv."
    fi
    local f
    for f in "$LINUX_APPS/$PACKAGE.desktop" "$LINUX_APPS/$PACKAGE-wizard.desktop" \
             "$LINUX_APPS/$PACKAGE-simulation.desktop" "$LINUX_ICON" "$(dirname "$LINUX_ICON_JPG")" \
             "$MAC_APPS/$APP_NAME.app" "$MAC_APPS/$WIZARD_NAME.app" "$MAC_APPS/$SIMULATION_NAME.app" \
             "$MAC_APPS/$APP_NAME Wizard.app"; do
        if [ -e "$f" ]; then run rm -rf "$f"; fi
    done
    ok "Removed.  Your settings, saved locations and logs in your home folder are kept,"
    ok "and so are uv and the system packages."
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

printf '%s%s for macOS and Linux%s\n' "$BOLD" "$APP_NAME" "$RESET"
if [ "$DRY_RUN" = 1 ]; then note "Dry run: nothing is changed."; fi

if [ "$UNINSTALL" = 1 ]; then
    uninstall
    exit 0
fi

check_user
step "Checking this computer"
case "$OS" in
    Linux) check_linux ;;
    Darwin) check_macos ;;
    *) die "This script is for macOS and Linux.  On Windows, use scripts/windows/install-sew.ps1." ;;
esac

if ! confirm "Install or upgrade $APP_NAME now?"; then
    exit 0
fi

if [ "$OS" = Linux ]; then
    install_linux_packages
    setup_linux_permissions
else
    install_macos_prerequisites
fi
install_uv
install_app

if [ "$SHORTCUTS" = 1 ]; then
    if [ "$OS" = Linux ]; then install_linux_shortcuts; else install_macos_shortcuts; fi
fi

BIN=$(bin_dir)
step "Done"
if [ "$OS" = Linux ]; then
    ok "Start $APP_NAME from the applications menu, or with  sew  (the wizard:  sew_wizard)."
else
    ok "Start $APP_NAME from ~/Applications or Launchpad, or with  sew  (the wizard:  sew_wizard)."
fi
case ":$PATH:" in
    *":$BIN:"*) ;;
    *) note "Open a new terminal first to have sew on your PATH (it is in $BIN)." ;;
esac
if [ "$NEEDS_RELOGIN" = 1 ]; then
    note "Log out and back in (or restart) once, so the new group membership lets you use the cameras."
fi
if [ -x "$HOME/solareclipseworkbench/bin/sew" ]; then
    note "The environment in ~/solareclipseworkbench from an earlier installation is no longer used."
    note "Keep any scripts you saved in it, and remove the rest when you like."
fi
ok "Run this script again at any time to upgrade."
