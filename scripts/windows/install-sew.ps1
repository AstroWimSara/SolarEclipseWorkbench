<#
.SYNOPSIS
    Installs Solar Eclipse Workbench on Windows (in WSL) and shares the cameras with it.

.DESCRIPTION
    Camera control uses gphoto2, which only runs on Linux and macOS, so on Windows
    Solar Eclipse Workbench runs inside WSL (Windows Subsystem for Linux).  This
    script does the whole setup:

      1. installs WSL and Ubuntu 24.04 (a restart may be needed half way; the
         script then continues by itself after you log in again),
      2. installs usbipd-win, which passes USB devices from Windows to WSL,
      3. installs the Linux packages and Solar Eclipse Workbench inside Ubuntu,
      4. adds Start menu shortcuts (and a desktop shortcut) for the application
         and the wizard,
      5. shares your cameras and USB GPS receiver with WSL.

    Run it again at any time: it skips what is already done and upgrades Solar
    Eclipse Workbench to the latest version.

    Run it as your normal user (not "Run as administrator").  Windows asks for
    permission (UAC) for the steps that need it.

.PARAMETER ShareDevices
    Only share USB devices (cameras, GPS receiver) with WSL.  Needed once per
    camera or GPS receiver; the Start menu has a shortcut for it.

.PARAMETER Update
    Upgrade Solar Eclipse Workbench and the Linux packages, without asking to
    share USB devices.

.PARAMETER Distro
    The WSL distribution to use.  Default: Ubuntu-24.04.

.EXAMPLE
    Double-click install-sew.cmd (next to this file, or on its own: it downloads
    this script), or run:
    powershell -ExecutionPolicy Bypass -File install-sew.ps1
#>

[CmdletBinding()]
param(
    [switch]$ShareDevices,
    [switch]$Update,
    [string]$Distro = "Ubuntu-24.04"
)

# Not "Stop": Windows PowerShell 5.1 turns every line a native program (wsl.exe,
# usbipd.exe) writes to stderr into an error, which would end the script.  Exit
# codes are checked instead.
$ErrorActionPreference = "Continue"
$ProgressPreference = "SilentlyContinue"

# wsl.exe writes UTF-16 by default, which PowerShell 5.1 reads as text with NUL
# characters in it.  This makes it write UTF-8.
$env:WSL_UTF8 = "1"

# wsl.exe switches the console to Linux newline handling (a line feed no longer
# returns to the start of the line) and leaves it like that, so everything
# printed afterwards runs diagonally across the window.  The console modes are
# saved here and restored after every wsl.exe call.
try {
    if (-not ("SolarEclipseWorkbench.ConsoleMode" -as [type])) {   # not when run twice in one window
        Add-Type -ErrorAction Stop -Namespace SolarEclipseWorkbench -Name ConsoleMode -MemberDefinition @'
[DllImport("kernel32.dll")] public static extern IntPtr GetStdHandle(int handle);
[DllImport("kernel32.dll")] public static extern bool GetConsoleMode(IntPtr handle, out uint mode);
[DllImport("kernel32.dll")] public static extern bool SetConsoleMode(IntPtr handle, uint mode);
'@
    }
    $script:ConsoleModes = @{}
    foreach ($std in -10, -11) {   # standard input, standard output
        $handle = [SolarEclipseWorkbench.ConsoleMode]::GetStdHandle($std)
        $mode = [uint32]0
        if ([SolarEclipseWorkbench.ConsoleMode]::GetConsoleMode($handle, [ref]$mode)) {
            $script:ConsoleModes[$std] = $mode
        }
    }
} catch {
    $script:ConsoleModes = @{}
}

function Restore-ConsoleMode {
    foreach ($std in $script:ConsoleModes.Keys) {
        try {
            $handle = [SolarEclipseWorkbench.ConsoleMode]::GetStdHandle($std)
            [SolarEclipseWorkbench.ConsoleMode]::SetConsoleMode($handle, $script:ConsoleModes[$std]) | Out-Null
        } catch { }
    }
}


$AppName = "Solar Eclipse Workbench"
$InstallDir = Join-Path $env:LOCALAPPDATA "SolarEclipseWorkbench"
$InstalledScript = Join-Path $InstallDir "install-sew.ps1"
$UsbipdExe = Join-Path $env:ProgramFiles "usbipd-win\usbipd.exe"
$ReadmeUrl = "https://github.com/AstroWimSara/SolarEclipseWorkbench#installation-on-windows-11"
$RunOnceKey = "HKCU:\Software\Microsoft\Windows\CurrentVersion\RunOnce"
$RunOnceName = "SolarEclipseWorkbenchSetup"

# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

function Write-Step([string]$Text) {
    Write-Host ""
    Write-Host "==> $Text" -ForegroundColor Cyan
}

function Write-Ok([string]$Text) { Write-Host "    $Text" -ForegroundColor Green }
function Write-Note([string]$Text) { Write-Host "    $Text" -ForegroundColor Yellow }

function Stop-WithError([string]$Text) {
    Write-Host ""
    Write-Host "ERROR: $Text" -ForegroundColor Red
    Write-Host "See $ReadmeUrl for the manual installation steps."
    Read-Host "Press Enter to close this window"
    exit 1
}

function Confirm-Choice([string]$Question, [bool]$Default = $true) {
    $hint = if ($Default) { "[Y/n]" } else { "[y/N]" }
    $answer = Read-Host "$Question $hint"
    if ([string]::IsNullOrWhiteSpace($answer)) { return $Default }
    return $answer.Trim().ToLower().StartsWith("y")
}

# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Assert-Preconditions {
    $build = [Environment]::OSVersion.Version.Build
    if ($build -lt 19044) {
        Stop-WithError ("Windows 10 version 21H2 (build 19044) or Windows 11 is needed to show " +
                        "Linux windows (WSLg).  This is build ${build}: please update Windows first.")
    }
    if (Test-IsAdministrator) {
        Write-Note "This window runs as administrator.  WSL installs Ubuntu for the account that runs"
        Write-Note "the script, so run it from a normal window if you log in with another account."
        if (-not (Confirm-Choice "Continue anyway?" $false)) { exit 1 }
    }
}

# Keep a copy of this script, for the Start menu shortcuts and for continuing
# after a restart.
function Save-ScriptCopy {
    New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
    if ($PSCommandPath -and ((Resolve-Path $PSCommandPath).Path -ne $InstalledScript)) {
        Copy-Item -Force $PSCommandPath $InstalledScript
    }
}

# ---------------------------------------------------------------------------
# WSL and Ubuntu
# ---------------------------------------------------------------------------

# True when the Microsoft Store version of WSL is installed and working.  The
# old inbox wsl.exe does not know --version.
function Test-Wsl {
    try {
        & wsl.exe --version *> $null
        Restore-ConsoleMode
        return ($LASTEXITCODE -eq 0)
    } catch {
        return $false
    }
}

function Get-WslDistros {
    $names = & wsl.exe --list --quiet 2>$null
    Restore-ConsoleMode
    if ($LASTEXITCODE -ne 0 -or -not $names) { return @() }
    return @($names | ForEach-Object { ($_ -replace "`0", "").Trim() } | Where-Object { $_ })
}

function Install-Wsl {
    Write-Step "Checking WSL"
    if (Test-Wsl) {
        Write-Ok "WSL is installed."
        return
    }

    Write-Note "Installing WSL.  Windows asks for permission; this can take a few minutes."
    & wsl.exe --install --no-distribution
    Restore-ConsoleMode
    if ($LASTEXITCODE -ne 0 -and -not (Test-Wsl)) {
        Stop-WithError "Installing WSL failed (see the messages above)."
    }

    # Enabling the Windows features (Virtual Machine Platform) needs a restart
    # before Linux can start, even when wsl.exe already answers.
    Write-Note "Windows has to restart to finish installing WSL."
    Write-Note "After you log in again, this installation continues by itself."
    if ($PSCommandPath) {
        $command = "powershell.exe -NoProfile -ExecutionPolicy Bypass -File `"$InstalledScript`""
        New-Item -Force -Path $RunOnceKey | Out-Null
        Set-ItemProperty -Path $RunOnceKey -Name $RunOnceName -Value $command
    } else {
        Write-Note "Run this script again after the restart."
    }
    if (Confirm-Choice "Restart now?") { Restart-Computer -Force }
    exit 0
}

function Install-Distro {
    Write-Step "Checking $Distro"
    if ((Get-WslDistros) -contains $Distro) {
        Write-Ok "$Distro is installed."
    } else {
        Write-Note "Installing $Distro.  When it is ready, Ubuntu asks for a new user name and password."
        Write-Note "These are for Linux only and do not have to be the same as your Windows account."
        Write-Note "Remember the password: the installation asks for it in a moment."
        Write-Note "When you see a Linux prompt (ending in `$), type  exit  and press Enter to continue."
        & wsl.exe --install --distribution $Distro
        Restore-ConsoleMode
        if ((Get-WslDistros) -notcontains $Distro) {
            Stop-WithError ("$Distro was not installed.  If the message above mentions virtualization, " +
                            "enable virtualization (Intel VT-x / AMD-V / SVM) in the BIOS or UEFI settings " +
                            "and run this script again.")
        }
    }

    $user = Get-LinuxUser
    if (-not $user -or $user -eq "root") {
        # Some WSL versions install without starting Ubuntu, so the user is not created yet.
        Write-Note "Starting $Distro to create your Linux user.  At the Linux prompt, type  exit  and press Enter."
        & wsl.exe --distribution $Distro
        Restore-ConsoleMode
        $user = Get-LinuxUser
    }
    if (-not $user -or $user -eq "root") {
        Stop-WithError ("$Distro has no Linux user of its own.  Start it once with " +
                        "'wsl -d $Distro', create a user when asked, and run this script again.")
    }
    Write-Ok "Linux user: $user"
    $script:LinuxUser = $user
}

function Get-LinuxUser {
    $user = & wsl.exe --distribution $Distro -- whoami 2>$null
    Restore-ConsoleMode
    if ($LASTEXITCODE -ne 0 -or -not $user) { return $null }
    return ($user | Select-Object -First 1).Trim()
}

# ---------------------------------------------------------------------------
# Linux side
# ---------------------------------------------------------------------------

# Run by the root user ("root <linux user>") and then by the Linux user ("user").
$LinuxSetup = @'
#!/bin/bash
set -euo pipefail

if [ "$1" = "root" ]; then
    linux_user="$2"
    export DEBIAN_FRONTEND=noninteractive
    apt-get update
    # gphoto2 (and its udev rules) for the cameras, gstreamer for the voice
    # prompts, usbutils for lsusb, the libraries the Qt windows need, and an
    # emoji font for the symbols on some buttons.
    apt-get install -y \
        ca-certificates curl usbutils gphoto2 \
        gstreamer1.0-tools gstreamer1.0-plugins-base gstreamer1.0-plugins-good \
        gstreamer1.0-pulseaudio alsa-utils pulseaudio-utils \
        libxkbcommon-x11-0 libxcb-cursor0 libxcb-icccm4 libxcb-image0 libxcb-keysyms1 \
        libxcb-randr0 libxcb-render-util0 libxcb-shape0 libxcb-xinerama0 libxcb-xkb1 \
        libgl1 libegl1 libfontconfig1 libdbus-1-3 fonts-dejavu-core fonts-noto-color-emoji

    # plugdev: use the cameras without sudo; dialout: the USB GPS receiver.
    usermod -aG plugdev,dialout "$linux_user"

    # udev applies the camera permissions, and it only runs under systemd.
    if [ "$(ps -p 1 -o comm=)" != "systemd" ]; then
        touch /etc/wsl.conf
        if grep -q '^\[boot\]' /etc/wsl.conf; then
            sed -i '/^\[boot\]/a systemd=true' /etc/wsl.conf
        else
            printf '\n[boot]\nsystemd=true\n' >> /etc/wsl.conf
        fi
        echo "systemd enabled in /etc/wsl.conf"
    fi
    exit 0
fi

if [ "$1" = "user" ]; then
    export PATH="$HOME/.local/bin:$PATH"
    if ! command -v uv > /dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    if uv tool list 2> /dev/null | grep -q '^solareclipseworkbench '; then
        uv tool upgrade solareclipseworkbench
    else
        uv tool install solareclipseworkbench
    fi
    # Copy the icon for the Windows shortcuts.  Versions up to 2.0.0 have no
    # sew.ico; the logo is copied then, and the Windows side makes an icon of it.
    img=$(ls -d "$(uv tool dir)"/solareclipseworkbench/lib/python3*/site-packages/solareclipseworkbench/img 2> /dev/null | head -n 1 || true)
    if [ -n "$img" ] && [ -n "${2:-}" ]; then
        if [ -f "$img/sew.ico" ]; then
            cp "$img/sew.ico" "$2/sew.ico" || echo "Could not copy the icon; the shortcuts use the WSL icon."
        elif [ -f "$img/logo.jpg" ]; then
            cp "$img/logo.jpg" "$2/logo.jpg" || echo "Could not copy the logo; the shortcuts use the WSL icon."
        fi
    fi
    exit 0
fi

echo "usage: $0 root <linux user> | user <install dir>" >&2
exit 2
'@

function ConvertTo-LinuxPath([string]$WindowsPath) {
    $path = (& wsl.exe --distribution $Distro -- wslpath -a -u ($WindowsPath -replace "\\", "/") | Select-Object -First 1).Trim()
    Restore-ConsoleMode
    return $path
}

function Invoke-LinuxSetup([string]$LinuxUser) {
    $scriptPath = Join-Path $InstallDir "setup-wsl.sh"
    # bash needs LF line endings and no byte order mark.
    $text = $LinuxSetup -replace "`r`n", "`n"
    [IO.File]::WriteAllText($scriptPath, $text, (New-Object Text.UTF8Encoding($false)))
    $linuxPath = ConvertTo-LinuxPath $scriptPath
    $linuxInstallDir = ConvertTo-LinuxPath $InstallDir

    Write-Step "Installing the Linux packages (this takes a few minutes the first time)"
    & wsl.exe --distribution $Distro --user root -- bash $linuxPath root $LinuxUser
    Restore-ConsoleMode
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Installing the Linux packages failed (see the messages above)." }

    Write-Step "Installing $AppName"
    & wsl.exe --distribution $Distro -- bash $linuxPath user $linuxInstallDir
    Restore-ConsoleMode
    if ($LASTEXITCODE -ne 0) { Stop-WithError "Installing $AppName failed (see the messages above)." }

    # Restart the distribution so new sessions get the new groups (and systemd).
    & wsl.exe --terminate $Distro *> $null
    Restore-ConsoleMode
    Write-Ok "$AppName is installed in $Distro."
}

# ---------------------------------------------------------------------------
# Shortcuts
# ---------------------------------------------------------------------------

function Get-IconPath {
    $iconPath = Join-Path $InstallDir "sew.ico"
    if (Test-Path $iconPath) { return $iconPath }
    $logoPath = Join-Path $InstallDir "logo.jpg"
    if ((Test-Path $logoPath) -and (New-IconFromImage $logoPath $iconPath)) { return $iconPath }
    return $null
}

# Writes a 256 x 256 icon (one PNG image in an .ico file, which Windows scales
# down for the smaller sizes) of the image, centred on a transparent square.
function New-IconFromImage([string]$ImagePath, [string]$IconPath) {
    try {
        Add-Type -AssemblyName System.Drawing
        $size = 256
        $source = [System.Drawing.Image]::FromFile($ImagePath)
        try {
            $scale = [Math]::Min($size / $source.Width, $size / $source.Height)
            $width = [int]($source.Width * $scale)
            $height = [int]($source.Height * $scale)
            $bitmap = New-Object System.Drawing.Bitmap $size, $size
            $graphics = [System.Drawing.Graphics]::FromImage($bitmap)
            $graphics.InterpolationMode = [System.Drawing.Drawing2D.InterpolationMode]::HighQualityBicubic
            $graphics.DrawImage($source, [int](($size - $width) / 2), [int](($size - $height) / 2), $width, $height)
            $graphics.Dispose()
            $png = New-Object System.IO.MemoryStream
            $bitmap.Save($png, [System.Drawing.Imaging.ImageFormat]::Png)
            $bitmap.Dispose()
        } finally {
            $source.Dispose()
        }
        $image = $png.ToArray()
        $ico = New-Object System.IO.MemoryStream
        $writer = New-Object System.IO.BinaryWriter $ico
        $writer.Write([uint16]0)               # reserved
        $writer.Write([uint16]1)               # type: icon
        $writer.Write([uint16]1)               # number of images
        $writer.Write([byte]0)                 # width 256
        $writer.Write([byte]0)                 # height 256
        $writer.Write([byte]0)                 # no palette
        $writer.Write([byte]0)                 # reserved
        $writer.Write([uint16]1)               # colour planes
        $writer.Write([uint16]32)              # bits per pixel
        $writer.Write([uint32]$image.Length)   # size of the image
        $writer.Write([uint32]22)              # offset of the image (6 + 16)
        $writer.Write($image)
        $writer.Flush()
        [System.IO.File]::WriteAllBytes($IconPath, $ico.ToArray())
        return $true
    } catch {
        Write-Note "Could not make an icon of the logo; the shortcuts use the WSL icon."
        return $false
    }
}

function New-Shortcut([string]$Path, [string]$Target, [string]$Arguments, [string]$Description,
                      [string]$Icon, [int]$WindowStyle = 1) {
    $shell = New-Object -ComObject WScript.Shell
    $link = $shell.CreateShortcut($Path)
    $link.TargetPath = $Target
    $link.Arguments = $Arguments
    $link.Description = $Description
    $link.WorkingDirectory = $env:USERPROFILE
    $link.WindowStyle = $WindowStyle   # 1 = normal, 7 = minimised
    if ($Icon) { $link.IconLocation = $Icon }
    $link.Save()
}

function Install-Shortcuts {
    Write-Step "Adding shortcuts"
    $wsl = Join-Path $env:WINDIR "System32\wsl.exe"
    $powershell = Join-Path $env:WINDIR "System32\WindowsPowerShell\v1.0\powershell.exe"
    $icon = Get-IconPath
    $menu = Join-Path ([Environment]::GetFolderPath("Programs")) $AppName
    New-Item -ItemType Directory -Force -Path $menu | Out-Null

    # The console window shows the log; it starts minimised.
    $sewArgs = "--distribution $Distro --cd ~ -- bash -lc `"exec ~/.local/bin/sew`""
    $wizardArgs = "--distribution $Distro --cd ~ -- bash -lc `"exec ~/.local/bin/sew_wizard`""
    $simulationArgs = "--distribution $Distro --cd ~ -- bash -lc `"exec ~/.local/bin/sew --sim`""
    $scriptArgs = "-NoProfile -ExecutionPolicy Bypass -File `"$InstalledScript`""

    New-Shortcut (Join-Path $menu "$AppName.lnk") $wsl $sewArgs "Plan and photograph solar eclipses" $icon 7
    New-Shortcut (Join-Path $menu "$AppName Wizard.lnk") $wsl $wizardArgs "Write a photography script" $icon 7
    New-Shortcut (Join-Path $menu "$AppName (simulation).lnk") $wsl $simulationArgs `
        "Rehearse a script in simulation mode" $icon 7
    New-Shortcut (Join-Path $menu "Share cameras with $AppName.lnk") $powershell "$scriptArgs -ShareDevices" `
        "Share a new camera or USB GPS receiver with WSL (once per device)" $icon
    New-Shortcut (Join-Path $menu "Update $AppName.lnk") $powershell "$scriptArgs -Update" `
        "Upgrade Solar Eclipse Workbench to the latest version" $icon
    New-Shortcut (Join-Path ([Environment]::GetFolderPath("Desktop")) "$AppName.lnk") $wsl $sewArgs `
        "Plan and photograph solar eclipses" $icon 7
    Write-Ok "Start menu: $AppName (application, wizard, simulation, share cameras, update), and a desktop shortcut."
}

# ---------------------------------------------------------------------------
# usbipd-win and sharing USB devices
# ---------------------------------------------------------------------------

function Get-UsbipdMajorVersion {
    try {
        $version = (& $UsbipdExe --version 2>$null | Select-Object -First 1)
        if ($version -match "^(\d+)\.") { return [int]$Matches[1] }
    } catch { }
    return 0
}

function Install-Usbipd {
    Write-Step "Checking usbipd-win (passes USB devices from Windows to WSL)"
    $winget = Get-Command winget.exe -ErrorAction SilentlyContinue
    if (Test-Path $UsbipdExe) {
        # Version 4 is needed: attaching without administrator rights, and "usbipd state".
        if ((Get-UsbipdMajorVersion) -ge 4) {
            Write-Ok "usbipd-win is installed."
            return
        }
        if ($winget) {
            Write-Note "Upgrading usbipd-win.  Windows asks for permission."
            & winget.exe upgrade --exact --id dorssel.usbipd-win --accept-package-agreements --accept-source-agreements
        }
    } elseif ($winget) {
        Write-Note "Installing usbipd-win.  Windows asks for permission."
        & winget.exe install --exact --id dorssel.usbipd-win --accept-package-agreements --accept-source-agreements
    }

    if (-not (Test-Path $UsbipdExe) -or (Get-UsbipdMajorVersion) -lt 4) {
        Stop-WithError ("usbipd-win 4 or newer is needed.  Install it from " +
                        "https://github.com/dorssel/usbipd-win/releases and run this script again.")
    }
    Write-Ok "usbipd-win is installed."
}

function Get-UsbDevices {
    try {
        $state = (& $UsbipdExe state) | Out-String | ConvertFrom-Json -ErrorAction Stop
    } catch {
        Write-Note "Could not read the USB devices from usbipd-win: $_"
        return @()
    }
    return @($state.Devices | Where-Object { $_.BusId })
}

function Show-UsbDevices($Devices) {
    Write-Host ""
    Write-Host ("    {0,3}  {1,-8} {2,-12} {3}" -f "#", "Bus id", "Status", "Device")
    for ($i = 0; $i -lt $Devices.Count; $i++) {
        $d = $Devices[$i]
        $status = "not shared"
        if ($d.PersistedGuid) { $status = "shared" }
        if ($d.ClientIPAddress) { $status = "attached" }
        Write-Host ("    {0,3}  {1,-8} {2,-12} {3}" -f ($i + 1), $d.BusId, $status, $d.Description)
    }
    Write-Host ""
}

function Share-UsbDevices {
    Write-Step "Sharing cameras and GPS receivers with WSL"
    Write-Host "    A device only has to be shared once.  After that, $AppName attaches it"
    Write-Host "    by itself every time it looks for cameras or a GPS receiver."
    Write-Host ""
    Read-Host "    Connect your cameras (switched on) and USB GPS receiver, then press Enter"

    $devices = @(Get-UsbDevices)
    if ($devices.Count -eq 0) {
        Write-Note "usbipd-win does not see any USB devices."
        return
    }
    Show-UsbDevices $devices
    Write-Host "    Cameras are listed with their model name, or as 'MTP USB Device' or 'PTP'."
    Write-Host "    Do not share your keyboard, mouse or other devices Windows still needs."
    $answer = Read-Host "    Numbers of the devices to share, separated by commas (Enter to skip)"
    if ([string]::IsNullOrWhiteSpace($answer)) { return }

    $selected = @()
    foreach ($part in ($answer -split "[,\s]+" | Where-Object { $_ })) {
        $n = 0
        if ([int]::TryParse($part, [ref]$n) -and $n -ge 1 -and $n -le $devices.Count) {
            $selected += $devices[$n - 1]
        } else {
            Write-Note "Ignoring '$part': not a number from the list."
        }
    }
    $selected = @($selected | Where-Object { -not $_.PersistedGuid })
    if ($selected.Count -eq 0) {
        Write-Ok "Nothing new to share."
        return
    }

    # One elevated PowerShell shares all of them, so there is only one UAC prompt.
    # It is passed encoded, so the path with spaces survives the command line.
    $commands = ($selected | ForEach-Object { "& '$UsbipdExe' bind --busid $($_.BusId)" }) -join "; "
    $encoded = [Convert]::ToBase64String([Text.Encoding]::Unicode.GetBytes($commands))
    Write-Note "Sharing needs administrator rights: Windows asks for permission."
    Start-Process -FilePath "powershell.exe" -Verb RunAs -Wait -WindowStyle Hidden `
        -ArgumentList "-NoProfile -EncodedCommand $encoded"

    $shared = @(Get-UsbDevices | Where-Object { $_.PersistedGuid } | ForEach-Object { $_.BusId })
    foreach ($d in $selected) {
        if ($shared -contains $d.BusId) {
            Write-Ok "Shared: $($d.Description) ($($d.BusId))"
        } else {
            Write-Note "Not shared: $($d.Description) ($($d.BusId))"
        }
    }
    Write-Host ""
    Write-Host "    If $AppName later reports 'Could not claim the USB device' (error -53) for a"
    Write-Host "    camera, Windows' own camera driver still holds it.  Replace that driver with"
    Write-Host "    WinUSB once, using Zadig: see 'Replace the Windows USB driver with WinUSB' in"
    Write-Host "    $ReadmeUrl"
}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

Write-Host "$AppName for Windows" -ForegroundColor Cyan
Remove-ItemProperty -Path $RunOnceKey -Name $RunOnceName -ErrorAction SilentlyContinue
Save-ScriptCopy

if ($ShareDevices) {
    Install-Usbipd
    Share-UsbDevices
    Read-Host "Done.  Press Enter to close this window"
    exit 0
}

Assert-Preconditions
Install-Wsl
Install-Distro
Install-Usbipd
Invoke-LinuxSetup $script:LinuxUser
Install-Shortcuts
if (-not $Update) { Share-UsbDevices }

Write-Host ""
Write-Host "$AppName is ready.  Start it from the Start menu or the desktop shortcut." -ForegroundColor Green
Read-Host "Press Enter to close this window"
