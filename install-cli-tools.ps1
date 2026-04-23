[CmdletBinding()]
param(
    [switch]$SkipElevationCheck,
    [switch]$SkipChocolateyBootstrap,
    [switch]$NoOp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$packages = @(
    @{ Id = 'git'; DisplayName = 'Git'; VerifyCommand = 'git'; VerifyArgs = @('--version') },
    @{ Id = 'ripgrep'; DisplayName = 'ripgrep'; VerifyCommand = 'rg'; VerifyArgs = @('--version') },
    @{ Id = 'fd'; DisplayName = 'fd'; VerifyCommand = 'fd'; VerifyArgs = @('--version') },
    @{ Id = 'bat'; DisplayName = 'bat'; VerifyCommand = 'bat'; VerifyArgs = @('--version') },
    @{ Id = 'fzf'; DisplayName = 'fzf'; VerifyCommand = 'fzf'; VerifyArgs = @('--version') },
    @{ Id = 'zoxide'; DisplayName = 'zoxide'; VerifyCommand = 'zoxide'; VerifyArgs = @('--version') },
    @{ Id = 'jq'; DisplayName = 'jq'; VerifyCommand = 'jq'; VerifyArgs = @('--version') },
    @{ Id = 'delta'; DisplayName = 'delta'; VerifyCommand = 'delta'; VerifyArgs = @('--version') },
    @{ Id = 'hyperfine'; DisplayName = 'hyperfine'; VerifyCommand = 'hyperfine'; VerifyArgs = @('--version') },
    @{ Id = 'yq'; DisplayName = 'yq'; VerifyCommand = 'yq'; VerifyArgs = @('--version') },
    @{ Id = 'sd'; DisplayName = 'sd'; VerifyCommand = 'sd'; VerifyArgs = @('--version') },
    @{ Id = 'gh'; DisplayName = 'GitHub CLI'; VerifyCommand = 'gh'; VerifyArgs = @('--version') },
    @{ Id = '7zip'; DisplayName = '7-Zip'; VerifyCommand = '7z'; VerifyArgs = @() },
    @{ Id = 'uv'; DisplayName = 'uv'; VerifyCommand = 'uv'; VerifyArgs = @('--version') },
    @{ Id = 'xh'; DisplayName = 'xh'; VerifyCommand = 'xh'; VerifyArgs = @('--version') }
)

function Write-Section {
    param([Parameter(Mandatory = $true)][string]$Message)

    Write-Host "==> $Message" -ForegroundColor Cyan
}

function Test-IsAdministrator {
    $identity = [Security.Principal.WindowsIdentity]::GetCurrent()
    $principal = New-Object Security.Principal.WindowsPrincipal($identity)
    return $principal.IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
}

function Refresh-ProcessPath {
    $machinePath = [Environment]::GetEnvironmentVariable('Path', 'Machine')
    $userPath = [Environment]::GetEnvironmentVariable('Path', 'User')
    $env:Path = (@($machinePath, $userPath) | Where-Object { $_ }) -join ';'
}

function Ensure-Elevated {
    if ($SkipElevationCheck) {
        return
    }

    if (Test-IsAdministrator) {
        return
    }

    if (-not $PSCommandPath) {
        throw '请用管理员身份打开 PowerShell 7 后再执行此脚本。'
    }

    $pwsh = (Get-Command pwsh -ErrorAction SilentlyContinue).Source
    if (-not $pwsh) {
        $candidate = Join-Path $PSHOME 'pwsh.exe'
        if (Test-Path $candidate) {
            $pwsh = $candidate
        } else {
            $pwsh = 'powershell.exe'
        }
    }

    Write-Section '当前不是管理员会话，正在请求 UAC 提权'
    Start-Process -FilePath $pwsh -Verb RunAs -ArgumentList @(
        '-NoProfile',
        '-ExecutionPolicy',
        'Bypass',
        '-File',
        "`"$PSCommandPath`""
    ) | Out-Null
    exit
}

function Ensure-Chocolatey {
    if (Get-Command choco -ErrorAction SilentlyContinue) {
        return
    }

    if ($SkipChocolateyBootstrap) {
        throw '未检测到 Chocolatey，且已显式禁止自动安装。'
    }

    Write-Section '未检测到 Chocolatey，按官方方式开始安装'
    Set-ExecutionPolicy Bypass -Scope Process -Force
    [System.Net.ServicePointManager]::SecurityProtocol = `
        [System.Net.ServicePointManager]::SecurityProtocol -bor 3072
    Invoke-Expression ((New-Object System.Net.WebClient).DownloadString('https://community.chocolatey.org/install.ps1'))
    Refresh-ProcessPath

    if (-not (Get-Command choco -ErrorAction SilentlyContinue)) {
        throw 'Chocolatey 安装完成后仍未能在当前会话解析 choco。'
    }
}

function Get-InstalledPackageVersion {
    param([Parameter(Mandatory = $true)][string]$PackageId)

    $line = choco list $PackageId --exact --limit-output --no-progress 2>$null | Select-Object -First 1
    if (-not $line) {
        return $null
    }

    $parts = $line -split '\|', 2
    if ($parts.Count -lt 2) {
        return $null
    }

    return $parts[1]
}

function Get-OutdatedPackageMap {
    $outdated = @{}
    $lines = choco outdated --limit-output --ignore-pinned --no-progress 2>$null

    foreach ($line in $lines) {
        if (-not $line) {
            continue
        }

        $parts = $line -split '\|'
        if ($parts.Count -lt 3) {
            continue
        }

        $outdated[$parts[0].ToLowerInvariant()] = [pscustomobject]@{
            Current   = $parts[1]
            Available = $parts[2]
            Pinned    = if ($parts.Count -ge 4) { $parts[3] } else { 'false' }
        }
    }

    return $outdated
}

function Install-OrUpgradePackage {
    param(
        [Parameter(Mandatory = $true)][hashtable]$Package,
        [Parameter(Mandatory = $true)][hashtable]$OutdatedMap
    )

    $packageId = $Package.Id
    $installedVersion = Get-InstalledPackageVersion -PackageId $packageId
    $outdatedInfo = $OutdatedMap[$packageId.ToLowerInvariant()]

    if (-not $installedVersion) {
        Write-Section "安装 $packageId"
        $arguments = @('install', $packageId, '-y', '--no-progress')
        if ($NoOp) {
            $arguments += '--noop'
        }

        & choco @arguments
        Refresh-ProcessPath
        return
    }

    if ($outdatedInfo) {
        Write-Section "升级 $packageId ($installedVersion -> $($outdatedInfo.Available))"
        $arguments = @('upgrade', $packageId, '-y', '--no-progress')
        if ($NoOp) {
            $arguments += '--noop'
        }

        & choco @arguments
        Refresh-ProcessPath
        return
    }

    Write-Host "跳过 $packageId，已是最新版本 ($installedVersion)" -ForegroundColor DarkGray
}

function Set-DeltaGitConfig {
    if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
        Write-Warning '未检测到 git，跳过 delta 的 Git 全局配置。'
        return
    }

    if (-not (Get-Command delta -ErrorAction SilentlyContinue)) {
        Write-Warning '未检测到 delta，跳过 Git delta 配置。'
        return
    }

    if ($NoOp) {
        Write-Section 'NoOp: 跳过写入 delta 的 Git 全局配置'
        Write-Host 'git config --global core.pager delta'
        Write-Host 'git config --global interactive.diffFilter "delta --color-only"'
        Write-Host 'git config --global delta.navigate true'
        Write-Host 'git config --global merge.conflictStyle zdiff3'
        return
    }

    Write-Section '写入 delta 的 Git 全局配置'
    & git config --global core.pager delta
    & git config --global interactive.diffFilter 'delta --color-only'
    & git config --global delta.navigate true
    & git config --global merge.conflictStyle zdiff3
}

function Get-VersionSummaryLine {
    param([Parameter(Mandatory = $true)][hashtable]$Package)

    $verifyCommand = $Package.VerifyCommand
    if (-not $verifyCommand) {
        return "$($Package.DisplayName): 已安装"
    }

    if (-not (Get-Command $verifyCommand -ErrorAction SilentlyContinue)) {
        $installedVersion = Get-InstalledPackageVersion -PackageId $Package.Id
        if ($installedVersion) {
            return "$($Package.DisplayName): 已安装（Chocolatey $installedVersion），但当前会话尚未解析到命令 $verifyCommand"
        }

        return "$($Package.DisplayName): 未检测到命令 $verifyCommand"
    }

    try {
        if ($Package.VerifyArgs.Count -gt 0) {
            $versionOutput = & $verifyCommand @($Package.VerifyArgs) 2>$null | Select-Object -First 1
        } else {
            $versionOutput = & $verifyCommand 2>$null | Select-Object -First 1
        }
    } catch {
        $versionOutput = $null
    }

    if ($versionOutput) {
        return "$($Package.DisplayName): $versionOutput"
    }

    $installedVersion = Get-InstalledPackageVersion -PackageId $Package.Id
    if ($installedVersion) {
        return "$($Package.DisplayName): Chocolatey $installedVersion"
    }

    return "$($Package.DisplayName): 已安装"
}

Ensure-Elevated
Refresh-ProcessPath
Ensure-Chocolatey
Refresh-ProcessPath

Write-Section '收集已安装版本与可升级信息'
$outdatedMap = Get-OutdatedPackageMap

foreach ($package in $packages) {
    Install-OrUpgradePackage -Package $package -OutdatedMap $outdatedMap
}

Refresh-ProcessPath
Set-DeltaGitConfig

Write-Section '版本摘要'
foreach ($package in $packages) {
    Write-Host "- $(Get-VersionSummaryLine -Package $package)"
}

Write-Section '完成'
Write-Host '命令行工具已安装/更新完成，delta 的 Git 全局配置已写入当前用户。' -ForegroundColor Green
