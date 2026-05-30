# OpenTAKServer Windows Installer
# Drone Defense TAK Server – Windows Setup
# Requires: Run as Administrator in PowerShell

param(
    [switch]$SkipPython,
    [switch]$SkipRabbitMQ,
    [switch]$SkipMediaMTX,
    [switch]$SkipService,
    [string]$InstallPath = "$env:ProgramFiles\OpenTAKServer",
    [string]$DataPath = "$env:ProgramData\OpenTAKServer",
    [string]$ConfigSource = "..\config\config.yml"
)

$ErrorActionPreference = "Stop"
Set-StrictMode -Version Latest

Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host "  OpenTAKServer – Drone Defense TAK Server Installation" -ForegroundColor Cyan
Write-Host "======================================================================" -ForegroundColor Cyan
Write-Host ""

function Write-Step { param([string]$Message) Write-Host "[ ] $Message" -ForegroundColor Yellow }
function Write-Ok { param([string]$Message) Write-Host "[+] $Message" -ForegroundColor Green }
function Write-Err { param([string]$Message) Write-Host "[-] $Message" -ForegroundColor Red; exit 1 }

function Test-Admin {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    if (-not $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)) {
        Write-Err "Please run this script as Administrator (right-click -> Run as Administrator)"
    }
    Write-Ok "Running with Administrator privileges"
}

function Install-Python {
    if ($SkipPython) { Write-Ok "Skipping Python (--SkipPython)"; return }
    Write-Step "Checking Python installation..."

    try {
        $pyVersion = & python --version 2>&1
        Write-Ok "Found: $pyVersion"
    }
    catch {
        Write-Err "Python 3.8+ not found. Please install from https://www.python.org/downloads/ and re-run this script."
    }

    $versionMatch = $pyVersion -match '(\d+)\.(\d+)'
    if ($versionMatch) {
        $major = [int]$Matches[1]
        $minor = [int]$Matches[2]
        if ($major -lt 3 -or ($major -eq 3 -and $minor -lt 8)) {
            Write-Err "Python 3.8+ required. Found $pyVersion"
        }
    }
    Write-Ok "Python version OK"
}

function Install-OpenTAKServer {
    Write-Step "Installing OpenTAKServer via pip..."

    & python -m pip install --upgrade pip --quiet
    if ($LASTEXITCODE -ne 0) { Write-Err "Failed to upgrade pip" }

    $reqFile = Join-Path $PSScriptRoot "..\requirements.txt"
    if (Test-Path $reqFile) {
        & python -m pip install -r $reqFile --quiet
        if ($LASTEXITCODE -ne 0) { Write-Err "Failed to install dependencies" }
    }
    else {
        & python -m pip install opentakserver --quiet
        if ($LASTEXITCODE -ne 0) { Write-Err "Failed to install OpenTAKServer" }
    }
    Write-Ok "OpenTAKServer installed successfully"
}

function Install-RabbitMQ {
    if ($SkipRabbitMQ) { Write-Ok "Skipping RabbitMQ (--SkipRabbitMQ)"; return }
    Write-Step "Installing RabbitMQ..."

    $rabbitPath = "$env:ProgramFiles\RabbitMQ Server\rabbitmq_server-*\sbin"
    $found = Get-ChildItem -Path $rabbitPath -ErrorAction SilentlyContinue

    if ($found) {
        Write-Ok "RabbitMQ already installed"
    }
    else {
        Write-Step "Downloading RabbitMQ installer..."
        $installerUrl = "https://github.com/rabbitmq/rabbitmq-server/releases/download/v3.13.1/rabbitmq-server-3.13.1.exe"
        $installerPath = "$env:TEMP\rabbitmq-installer.exe"

        [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
        Invoke-WebRequest -Uri $installerUrl -OutFile $installerPath -UseBasicParsing

        Write-Step "Running RabbitMQ installer..."
        Start-Process -FilePath $installerPath -ArgumentList "/S" -Wait -NoNewWindow
        Remove-Item $installerPath -Force
        Write-Ok "RabbitMQ installed"
    }

    Write-Step "Starting RabbitMQ service..."
    $service = Get-Service -Name "RabbitMQ" -ErrorAction SilentlyContinue
    if ($service) {
        if ($service.Status -ne 'Running') {
            Start-Service -Name "RabbitMQ"
        }
        Set-Service -Name "RabbitMQ" -StartupType Automatic
        Write-Ok "RabbitMQ service running"
    }

    Write-Step "Enabling RabbitMQ management plugin..."
    $rabbitSbin = (Get-ChildItem -Path "$env:ProgramFiles\RabbitMQ Server\rabbitmq_server-*\sbin" -Directory | Select-Object -First 1).FullName
    if ($rabbitSbin) {
        & "$rabbitSbin\rabbitmq-plugins.bat" enable rabbitmq_management --quiet 2>&1 | Out-Null
        Write-Ok "RabbitMQ management plugin enabled"
    }
}

function Install-MediaMTX {
    if ($SkipMediaMTX) { Write-Ok "Skipping MediaMTX (--SkipMediaMTX)"; return }
    Write-Step "Installing MediaMTX..."

    $mtxPath = "$InstallPath\mediamtx"
    if (Test-Path "$mtxPath\mediamtx.exe") {
        Write-Ok "MediaMTX already installed"
        return
    }

    New-Item -ItemType Directory -Path $mtxPath -Force | Out-Null

    Write-Step "Downloading MediaMTX..."
    $mtxUrl = "https://github.com/bluenviron/mediamtx/releases/download/v1.8.5/mediamtx_v1.8.5_windows_amd64.zip"
    $mtxZip = "$env:TEMP\mediamtx.zip"

    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    Invoke-WebRequest -Uri $mtxUrl -OutFile $mtxZip -UseBasicParsing

    Expand-Archive -Path $mtxZip -DestinationPath $mtxPath -Force
    Remove-Item $mtxZip -Force
    Write-Ok "MediaMTX installed at $mtxPath"
}

function Copy-Config {
    Write-Step "Copying configuration..."

    New-Item -ItemType Directory -Path $DataPath -Force | Out-Null

    $configDest = Join-Path $DataPath "config.yml"
    $configSrc = Join-Path $PSScriptRoot $ConfigSource
    if (-not (Test-Path $configSrc)) {
        Write-Err "Config file not found: $configSrc"
    }
    Copy-Item -Path $configSrc -Destination $configDest -Force
    Write-Ok "Configuration copied to $configDest"
}

function New-WindowsService {
    if ($SkipService) { Write-Ok "Skipping Windows Service (--SkipService)"; return }
    Write-Step "Setting up Windows Service..."

    $serviceName = "OpenTAKServer"
    $existing = Get-Service -Name $serviceName -ErrorAction SilentlyContinue
    if ($existing) {
        Write-Ok "Service $serviceName already exists"
        return
    }

    New-Service -Name $serviceName `
        -BinaryPathName "$(Get-Command python).Source -m opentakserver --config `"$DataPath\config.yml`"" `
        -DisplayName "OpenTAKServer – Drone Defense TAK Server" `
        -Description "Tactical Assault Kit server for drone defense operations" `
        -StartupType Automatic

    Write-Step "Configuring service recovery options..."
    sc.exe failure $serviceName reset=86400 actions=restart/5000/restart/10000/restart/30000
    Write-Ok "Windows Service configured"
}

function Set-FirewallRules {
    Write-Step "Configuring Windows Firewall..."

    $rules = @(
        @{Name="OpenTAKServer-CoA"; Port=8089; Protocol="TCP"},
        @{Name="OpenTAKServer-SSL"; Port=8443; Protocol="TCP"},
        @{Name="OpenTAKServer-RTSP"; Port=8554; Protocol="TCP"},
        @{Name="OpenTAKServer-MediaMTX"; Port=8889; Protocol="TCP"}
    )

    foreach ($rule in $rules) {
        $existing = netsh advfirewall firewall show rule name="$($rule.Name)" 2>&1
        if ($existing -match "No rules match") {
            netsh advfirewall firewall add rule name="$($rule.Name)" dir=in action=allow `
                protocol=$($rule.Protocol) localport=$($rule.Port) | Out-Null
            Write-Ok "Firewall rule added: $($rule.Name) ($($rule.Protocol):$($rule.Port))"
        }
        else {
            Write-Ok "Firewall rule already exists: $($rule.Name)"
        }
    }
}

function Start-Server {
    Write-Step "Starting OpenTAKServer..."
    $serviceName = "OpenTAKServer"
    $service = Get-Service -Name $serviceName -ErrorAction SilentlyContinue

    if ($service) {
        Start-Service -Name $serviceName
        Write-Ok "Service started"
    }
    else {
        Write-Step "Starting in foreground mode..."
        Write-Host "  Run: python -m opentakserver --config `"$DataPath\config.yml`"" -ForegroundColor White
    }

    Write-Host ""
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host "  OpenTAKServer Installation Complete" -ForegroundColor Green
    Write-Host "======================================================================" -ForegroundColor Cyan
    Write-Host ""
    Write-Host "  Web UI:     http://localhost:8089" -ForegroundColor White
    Write-Host "  SSL Port:   8443" -ForegroundColor White
    Write-Host "  RTSP:       8554 (MediaMTX)" -ForegroundColor White
    Write-Host "  Config:     $DataPath\config.yml" -ForegroundColor White
    Write-Host ""
}

function Main {
    Test-Admin
    Install-Python
    Install-OpenTAKServer
    Install-RabbitMQ
    Install-MediaMTX
    Copy-Config
    New-WindowsService
    Set-FirewallRules
    Start-Server
}

Main
