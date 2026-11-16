[CmdletBinding()]
param(
    [Parameter(Mandatory = $true)]
    [ValidateSet("Setup", "Verify", "Start", "Cleanup")]
    [string]$Action,

    [string]$Python = "",

    [switch]$InstallAiTools,

    [switch]$ConfirmCleanup
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$WorkspaceRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$AppRoot = Join-Path $WorkspaceRoot "app"
$RuntimeRoot = Join-Path $WorkspaceRoot "runtime"
$WindowsRuntimeRoot = Join-Path $RuntimeRoot "windows-demo"
$SeedDatabasePath = Join-Path $RuntimeRoot "demo.sqlite3"
$DatabasePath = Join-Path $WindowsRuntimeRoot "demo.sqlite3"
$DatasetId = "synthetic_demo_v1"
$DatasetRoot = Join-Path $WorkspaceRoot ("datasets\" + $DatasetId)
$DatasetManifestPath = Join-Path $DatasetRoot "manifest.json"
$ManifestPath = Join-Path $WorkspaceRoot "MANIFEST.json"
$VenvRoot = Join-Path $WorkspaceRoot ".venv-windows-demo"
$VenvPython = Join-Path $VenvRoot "Scripts\python.exe"
$ManagePy = Join-Path $AppRoot "manage.py"
$PyprojectPath = Join-Path $AppRoot "pyproject.toml"
$RuntimeOwnershipMarker = Join-Path $WorkspaceRoot ".templedb-windows-demo-runtime-owner.json"
$VenvOwnershipMarker = Join-Path $WorkspaceRoot ".templedb-windows-demo-venv-owner.json"
$OperationLockPath = Join-Path $WorkspaceRoot ".templedb-windows-demo-operation.lock"
$RuntimeOwnershipSentinel = Join-Path $WindowsRuntimeRoot ".templedb-windows-demo-owner.json"
$VenvOwnershipSentinel = Join-Path $VenvRoot ".templedb-windows-demo-owner.json"
$ServerGuardPath = Join-Path $WindowsRuntimeRoot "server-guard.json"
$PipFreezePath = Join-Path $WindowsRuntimeRoot "pip-freeze.txt"
$RequirementsPath = Join-Path $WindowsRuntimeRoot "windows-requirements.txt"
$EnvironmentLogPath = Join-Path $WindowsRuntimeRoot "environment-changes.md"
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Stop-TempleDbWindowsDemo {
    param([string]$Message)

    throw (New-Object System.InvalidOperationException -ArgumentList $Message)
}

function Assert-NoWorkspaceReparsePoint {
    param(
        [string]$Path,
        [string]$Label
    )

    $fullPath = [System.IO.Path]::GetFullPath($Path)
    $rootPath = [System.IO.Path]::GetFullPath($WorkspaceRoot)
    $rootPrefix = $rootPath.TrimEnd([System.IO.Path]::DirectorySeparatorChar) + [System.IO.Path]::DirectorySeparatorChar
    if (
        -not $fullPath.Equals($rootPath, [System.StringComparison]::OrdinalIgnoreCase) -and
        -not $fullPath.StartsWith($rootPrefix, [System.StringComparison]::OrdinalIgnoreCase)
    ) {
        Stop-TempleDbWindowsDemo "$Label must stay inside the starter workspace: $Path"
    }

    $currentPath = $fullPath
    while ($true) {
        if (Test-Path -LiteralPath $currentPath) {
            $item = Get-Item -LiteralPath $currentPath -Force
            if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
                Stop-TempleDbWindowsDemo "$Label must not pass through a symbolic link or junction: $currentPath"
            }
        }
        if ($currentPath.Equals($rootPath, [System.StringComparison]::OrdinalIgnoreCase)) {
            break
        }
        $parent = [System.IO.Directory]::GetParent($currentPath)
        if ($null -eq $parent) {
            Stop-TempleDbWindowsDemo "$Label could not be resolved inside the starter workspace: $Path"
        }
        $currentPath = $parent.FullName
    }
}

function Assert-RegularPath {
    param(
        [string]$Path,
        [string]$Label,
        [switch]$Directory,
        [switch]$AllowOutsideWorkspace
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        Stop-TempleDbWindowsDemo "$Label was not found: $Path"
    }
    if (-not $AllowOutsideWorkspace) {
        Assert-NoWorkspaceReparsePoint -Path $Path -Label $Label
    }
    $item = Get-Item -LiteralPath $Path -Force
    if (($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) {
        Stop-TempleDbWindowsDemo "$Label must not be a symbolic link or junction: $Path"
    }
    if ($Directory -and -not $item.PSIsContainer) {
        Stop-TempleDbWindowsDemo "$Label must be a directory: $Path"
    }
    if (-not $Directory -and $item.PSIsContainer) {
        Stop-TempleDbWindowsDemo "$Label must be a regular file: $Path"
    }
}

function Read-JsonObject {
    param(
        [string]$Path,
        [string]$Label
    )

    Assert-RegularPath -Path $Path -Label $Label
    try {
        $rawJson = Get-Content -LiteralPath $Path -Raw -Encoding UTF8
        return $rawJson | ConvertFrom-Json
    }
    catch {
        Stop-TempleDbWindowsDemo "$Label is not valid UTF-8 JSON: $Path"
    }
}

function Read-JsonObjectFromOpenStream {
    param(
        [System.IO.FileStream]$Stream,
        [string]$Label
    )

    $Stream.Position = 0
    $reader = [System.IO.StreamReader]::new(
        $Stream,
        [System.Text.Encoding]::UTF8,
        $true,
        1024,
        $true
    )
    try {
        $rawJson = $reader.ReadToEnd()
    }
    finally {
        $reader.Dispose()
    }
    try {
        return $rawJson | ConvertFrom-Json
    }
    catch {
        Stop-TempleDbWindowsDemo "$Label is not valid UTF-8 JSON."
    }
}

function Write-JsonObjectCreateNew {
    param(
        [string]$Path,
        [object]$Payload
    )

    $temporaryPath = $Path + "." + [Guid]::NewGuid().ToString("N") + ".tmp"
    try {
        $json = ($Payload | ConvertTo-Json -Depth 4) + [Environment]::NewLine
        $bytes = $Utf8NoBom.GetBytes($json)
        $stream = [System.IO.FileStream]::new(
            $temporaryPath,
            [System.IO.FileMode]::CreateNew,
            [System.IO.FileAccess]::Write,
            [System.IO.FileShare]::None
        )
        try {
            $stream.Write($bytes, 0, $bytes.Length)
            $stream.Flush($true)
        }
        finally {
            $stream.Dispose()
        }
        try {
            [System.IO.File]::Move($temporaryPath, $Path)
        }
        catch [System.IO.IOException] {
            Stop-TempleDbWindowsDemo "A Windows demo owned file already exists: $Path"
        }
    }
    finally {
        if (Test-Path -LiteralPath $temporaryPath) {
            Remove-Item -LiteralPath $temporaryPath -Force
        }
    }
}

function Assert-OwnedMarker {
    param(
        [string]$Path,
        [string]$ExpectedKind,
        [string]$Label
    )

    $payload = Read-JsonObject -Path $Path -Label $Label
    if (
        -not ($payload.PSObject.Properties.Name -contains "package_kind") -or
        [string]$payload.package_kind -ne $ExpectedKind
    ) {
        Stop-TempleDbWindowsDemo "$Label does not belong to this Windows demo workflow: $Path"
    }
    return $payload
}

function Remove-OwnedJsonMarkerIfToken {
    param(
        [string]$Path,
        [string]$ExpectedKind,
        [string]$OwnershipToken
    )

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }
    try {
        $payload = Read-JsonObject -Path $Path -Label "Windows demo owned marker"
    }
    catch {
        return
    }
    if (
        ($payload.PSObject.Properties.Name -contains "package_kind") -and
        ($payload.PSObject.Properties.Name -contains "ownership_token") -and
        [string]$payload.package_kind -eq $ExpectedKind -and
        [string]$payload.ownership_token -eq $OwnershipToken
    ) {
        Remove-Item -LiteralPath $Path -Force
    }
}

function Assert-ExternalOwnershipMarker {
    param(
        [string]$Path,
        [string]$ExpectedKind,
        [string]$ExpectedTargetPath,
        [string]$Label
    )

    $payload = Assert-OwnedMarker -Path $Path -ExpectedKind $ExpectedKind -Label $Label
    foreach ($name in @(
        "marker_scope",
        "ownership_token",
        "target_path",
        "directory_creation_ticks"
    )) {
        if (-not ($payload.PSObject.Properties.Name -contains $name)) {
            Stop-TempleDbWindowsDemo "$Label is incomplete: $Path"
        }
    }
    if ([string]$payload.marker_scope -ne "external") {
        Stop-TempleDbWindowsDemo "$Label has an unexpected scope: $Path"
    }
    if ([string]$payload.ownership_token -notmatch '^[0-9a-f]{32}$') {
        Stop-TempleDbWindowsDemo "$Label has an invalid ownership token: $Path"
    }
    $normalizedTargetPath = [System.IO.Path]::GetFullPath($ExpectedTargetPath)
    if (-not [string]::Equals(
        [string]$payload.target_path,
        $normalizedTargetPath,
        [System.StringComparison]::OrdinalIgnoreCase
    )) {
        Stop-TempleDbWindowsDemo "$Label points to an unexpected directory: $Path"
    }
    if ([string]$payload.directory_creation_ticks -notmatch '^[0-9]+$') {
        Stop-TempleDbWindowsDemo "$Label has an invalid directory identity: $Path"
    }
    return $payload
}

function Assert-OwnedDirectory {
    param(
        [string]$Path,
        [string]$ExternalMarkerPath,
        [string]$SentinelPath,
        [string]$ExpectedKind,
        [string]$Label,
        [switch]$AllowMissingSentinel
    )

    Assert-RegularPath -Path $Path -Label $Label -Directory
    $external = Assert-ExternalOwnershipMarker -Path $ExternalMarkerPath -ExpectedKind $ExpectedKind -ExpectedTargetPath $Path -Label ($Label + " external ownership marker")
    $directory = Get-Item -LiteralPath $Path -Force
    $actualCreationTicks = [string]$directory.CreationTimeUtc.Ticks
    if ([string]$external.directory_creation_ticks -ne $actualCreationTicks) {
        Stop-TempleDbWindowsDemo "$Label no longer matches its external ownership marker."
    }

    if (-not (Test-Path -LiteralPath $SentinelPath)) {
        if ($AllowMissingSentinel) {
            $unexpectedEntry = Get-ChildItem -LiteralPath $Path -Force | Select-Object -First 1
            if ($null -ne $unexpectedEntry) {
                Stop-TempleDbWindowsDemo "$Label has content but its ownership sentinel is missing."
            }
            return $external
        }
        Stop-TempleDbWindowsDemo "$Label ownership sentinel is missing: $SentinelPath"
    }

    $sentinel = Assert-OwnedMarker -Path $SentinelPath -ExpectedKind $ExpectedKind -Label ($Label + " ownership sentinel")
    foreach ($name in @(
        "marker_scope",
        "ownership_token",
        "target_path",
        "directory_creation_ticks"
    )) {
        if (-not ($sentinel.PSObject.Properties.Name -contains $name)) {
            Stop-TempleDbWindowsDemo "$Label ownership sentinel is incomplete."
        }
    }
    if (
        [string]$sentinel.marker_scope -ne "directory" -or
        [string]$sentinel.ownership_token -ne [string]$external.ownership_token -or
        [string]$sentinel.target_path -ne [string]$external.target_path -or
        [string]$sentinel.directory_creation_ticks -ne $actualCreationTicks
    ) {
        Stop-TempleDbWindowsDemo "$Label ownership records do not match."
    }
    return $external
}

function Remove-OwnedDirectorySafely {
    param(
        [string]$Path,
        [string]$ExternalMarkerPath,
        [string]$SentinelPath,
        [string]$ExpectedKind,
        [string]$Label
    )

    $external = Assert-OwnedDirectory -Path $Path -ExternalMarkerPath $ExternalMarkerPath -SentinelPath $SentinelPath -ExpectedKind $ExpectedKind -Label $Label -AllowMissingSentinel
    if (-not (Test-Path -LiteralPath $SentinelPath)) {
        [System.IO.Directory]::Delete($Path, $false)
        Remove-OwnedJsonMarkerIfToken -Path $ExternalMarkerPath -ExpectedKind $ExpectedKind -OwnershipToken ([string]$external.ownership_token)
        return
    }
    $sentinel = Read-JsonObject -Path $SentinelPath -Label ($Label + " ownership sentinel")
    $normalizedSentinelPath = [System.IO.Path]::GetFullPath($SentinelPath)

    foreach ($entry in Get-ChildItem -LiteralPath $Path -Force) {
        $entryPath = [System.IO.Path]::GetFullPath($entry.FullName)
        if ([string]::Equals(
            $entryPath,
            $normalizedSentinelPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )) {
            continue
        }
        Remove-Item -LiteralPath $entry.FullName -Recurse -Force
    }

    $remainingEntries = @(Get-ChildItem -LiteralPath $Path -Force)
    if (
        $remainingEntries.Count -ne 1 -or
        -not [string]::Equals(
            [System.IO.Path]::GetFullPath($remainingEntries[0].FullName),
            $normalizedSentinelPath,
            [System.StringComparison]::OrdinalIgnoreCase
        )
    ) {
        Stop-TempleDbWindowsDemo "$Label changed while cleanup was running; its ownership sentinel was preserved."
    }

    Remove-Item -LiteralPath $SentinelPath -Force
    try {
        [System.IO.Directory]::Delete($Path, $false)
    }
    catch {
        if (
            (Test-Path -LiteralPath $Path) -and
            -not (Test-Path -LiteralPath $SentinelPath)
        ) {
            try {
                Write-JsonObjectCreateNew -Path $SentinelPath -Payload $sentinel
            }
            catch {
                [Console]::Error.WriteLine(
                    "$Label could not restore its ownership sentinel after cleanup failed. Stop and inspect this workspace before retrying."
                )
            }
        }
        throw
    }

    Remove-OwnedJsonMarkerIfToken -Path $ExternalMarkerPath -ExpectedKind $ExpectedKind -OwnershipToken ([string]$external.ownership_token)
}

function New-OwnedDirectory {
    param(
        [string]$Path,
        [string]$ExternalMarkerPath,
        [string]$SentinelPath,
        [string]$ExpectedKind,
        [string]$Label
    )

    $ownershipToken = [Guid]::NewGuid().ToString("N")
    $externalMarkerCreated = $false
    New-Item -ItemType Directory -Path $Path | Out-Null
    try {
        Assert-RegularPath -Path $Path -Label $Label -Directory
        $directory = Get-Item -LiteralPath $Path -Force
        $externalPayload = [ordered]@{
            package_kind = $ExpectedKind
            marker_scope = "external"
            ownership_token = $ownershipToken
            target_path = [System.IO.Path]::GetFullPath($Path)
            directory_creation_ticks = [string]$directory.CreationTimeUtc.Ticks
            created_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
        $sentinelPayload = [ordered]@{
            package_kind = $ExpectedKind
            marker_scope = "directory"
            ownership_token = $ownershipToken
            target_path = [System.IO.Path]::GetFullPath($Path)
            directory_creation_ticks = [string]$directory.CreationTimeUtc.Ticks
            created_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        }
        Write-JsonObjectCreateNew -Path $ExternalMarkerPath -Payload $externalPayload
        $externalMarkerCreated = $true
        Write-JsonObjectCreateNew -Path $SentinelPath -Payload $sentinelPayload
        Assert-OwnedDirectory -Path $Path -ExternalMarkerPath $ExternalMarkerPath -SentinelPath $SentinelPath -ExpectedKind $ExpectedKind -Label $Label | Out-Null
    }
    catch {
        if (Test-Path -LiteralPath $SentinelPath) {
            Remove-Item -LiteralPath $SentinelPath -Force -ErrorAction SilentlyContinue
        }
        if (Test-Path -LiteralPath $Path) {
            Remove-Item -LiteralPath $Path -Force -ErrorAction SilentlyContinue
        }
        if ($externalMarkerCreated) {
            Remove-OwnedJsonMarkerIfToken -Path $ExternalMarkerPath -ExpectedKind $ExpectedKind -OwnershipToken $ownershipToken
        }
        throw
    }
}

function Get-DemoSeedMode {
    $manifest = Read-JsonObject -Path $ManifestPath -Label "Starter manifest"
    # Older archives intentionally require their packaged DB. Never infer a
    # source-only build from an accidentally missing or damaged archive seed.
    if (-not ($manifest.PSObject.Properties.Name -contains "demo_seed_mode")) {
        return "packaged"
    }
    if ([string]$manifest.demo_seed_mode -ne "dataset") {
        Stop-TempleDbWindowsDemo "The starter manifest has an unsupported demo seed mode."
    }
    Assert-RegularPath -Path (Join-Path $WorkspaceRoot "PUBLIC_BUILD.json") -Label "Public source build manifest"
    return "dataset"
}

function Assert-WorkspaceContract {
    Assert-RegularPath -Path $WorkspaceRoot -Label "Workspace root" -Directory
    Assert-RegularPath -Path $AppRoot -Label "Application root" -Directory
    Assert-RegularPath -Path $ManagePy -Label "manage.py"
    if (Test-Path -LiteralPath $RuntimeRoot) {
        Assert-RegularPath -Path $RuntimeRoot -Label "Runtime root" -Directory
    }
    Assert-RegularPath -Path $DatasetRoot -Label "Dataset root" -Directory
    Assert-RegularPath -Path $ManifestPath -Label "Starter manifest"
    Assert-RegularPath -Path $DatasetManifestPath -Label "Dataset manifest"

    $manifest = Read-JsonObject -Path $ManifestPath -Label "Starter manifest"
    if ($manifest.package_kind -ne "templedb-unified-starter-v1") {
        Stop-TempleDbWindowsDemo "This folder is not a verified TempleDB starter workspace."
    }
    if ($manifest.database -ne "sqlite" -or $manifest.dataset_id -ne $DatasetId) {
        Stop-TempleDbWindowsDemo "The starter manifest does not describe the synthetic SQLite demo."
    }
    if ((Get-DemoSeedMode) -eq "packaged") {
        Assert-RegularPath -Path $SeedDatabasePath -Label "Packaged synthetic demo database"
    }
}

function Assert-CleanupWorkspaceContract {
    Assert-RegularPath -Path $WorkspaceRoot -Label "Workspace root" -Directory

    if (Test-Path -LiteralPath $WindowsRuntimeRoot) {
        Assert-OwnedDirectory -Path $WindowsRuntimeRoot -ExternalMarkerPath $RuntimeOwnershipMarker -SentinelPath $RuntimeOwnershipSentinel -ExpectedKind "templedb-windows-demo-runtime-v1" -Label "Windows demo runtime" -AllowMissingSentinel | Out-Null
    }
    elseif (Test-Path -LiteralPath $RuntimeOwnershipMarker) {
        Assert-ExternalOwnershipMarker -Path $RuntimeOwnershipMarker -ExpectedKind "templedb-windows-demo-runtime-v1" -ExpectedTargetPath $WindowsRuntimeRoot -Label "Windows demo runtime marker" | Out-Null
    }

    if (Test-Path -LiteralPath $VenvRoot) {
        Assert-OwnedDirectory -Path $VenvRoot -ExternalMarkerPath $VenvOwnershipMarker -SentinelPath $VenvOwnershipSentinel -ExpectedKind "templedb-windows-demo-venv-v1" -Label "Windows demo venv" -AllowMissingSentinel | Out-Null
    }
    elseif (Test-Path -LiteralPath $VenvOwnershipMarker) {
        Assert-ExternalOwnershipMarker -Path $VenvOwnershipMarker -ExpectedKind "templedb-windows-demo-venv-v1" -ExpectedTargetPath $VenvRoot -Label "Windows demo venv marker" | Out-Null
    }
}

function Enter-WindowsDemoOperationLock {
    if (-not (Test-Path -LiteralPath $OperationLockPath)) {
        $ownershipToken = [Guid]::NewGuid().ToString("N")
        Write-JsonObjectCreateNew -Path $OperationLockPath -Payload ([ordered]@{
            package_kind = "templedb-windows-demo-operation-lock-v1"
            ownership_token = $ownershipToken
            created_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
        })
    }
    Assert-RegularPath -Path $OperationLockPath -Label "Windows demo operation lock"
    try {
        $stream = [System.IO.FileStream]::new(
            $OperationLockPath,
            [System.IO.FileMode]::Open,
            [System.IO.FileAccess]::ReadWrite,
            [System.IO.FileShare]::None
        )
    }
    catch [System.IO.IOException] {
        Stop-TempleDbWindowsDemo "Another Windows demo setup, verification, server, or cleanup operation is active."
    }
    try {
        $marker = Read-JsonObjectFromOpenStream -Stream $stream -Label "Windows demo operation lock"
        if (
            -not ($marker.PSObject.Properties.Name -contains "package_kind") -or
            [string]$marker.package_kind -ne "templedb-windows-demo-operation-lock-v1" -or
            -not ($marker.PSObject.Properties.Name -contains "ownership_token") -or
            [string]$marker.ownership_token -notmatch '^[0-9a-f]{32}$'
        ) {
            Stop-TempleDbWindowsDemo "The Windows demo operation lock does not belong to this workflow."
        }
        $ownershipToken = [string]$marker.ownership_token
    }
    catch {
        $stream.Dispose()
        throw
    }
    $stream.Position = 0
    return [PSCustomObject]@{
        Stream = $stream
        OwnershipToken = $ownershipToken
    }
}

function Remove-OwnedOperationLock {
    param([string]$OwnershipToken)

    Remove-OwnedJsonMarkerIfToken -Path $OperationLockPath -ExpectedKind "templedb-windows-demo-operation-lock-v1" -OwnershipToken $OwnershipToken
}

function Clear-TempleDbAmbientEnvironment {
    # Do not enumerate Env:. Codex Desktop can provide PATH and Path together,
    # which makes the Windows PowerShell 5.1 environment provider fail before
    # this function can filter anything. Keep this explicit list aligned with
    # TempleDB's supported runtime inputs instead.
    foreach ($name in @(
        "DATABASE_HOST",
        "DATABASE_NAME",
        "DATABASE_PASSWORD",
        "DATABASE_PORT",
        "DATABASE_URL",
        "DATABASE_USER",
        "DJANGO_ALLOWED_HOSTS",
        "DJANGO_CSRF_TRUSTED_ORIGINS",
        "DJANGO_DEBUG",
        "DJANGO_SECRET_KEY",
        "DJANGO_SETTINGS_MODULE",
        "GOOGLE_APPLICATION_CREDENTIALS",
        "MPLCONFIGDIR",
        "OPENAI_API_KEY",
        "OPENAI_RESPONSES_URL",
        "PGAPPNAME",
        "PGCHANNELBINDING",
        "PGCLIENTENCODING",
        "PGCONNECT_TIMEOUT",
        "PGDATABASE",
        "PGDATESTYLE",
        "PGGEQO",
        "PGGSSDELEGATION",
        "PGGSSENCMODE",
        "PGGSSLIB",
        "PGHOST",
        "PGHOSTADDR",
        "PGKRBSRVNAME",
        "PGLOADBALANCEHOSTS",
        "PGLOCALEDIR",
        "PGOPTIONS",
        "PGPASSFILE",
        "PGPASSWORD",
        "PGPORT",
        "PGREQUIREAUTH",
        "PGREQUIREPEER",
        "PGREQUIRESSL",
        "PGSERVICE",
        "PGSERVICEFILE",
        "PGSSLCERT",
        "PGSSLCERTMODE",
        "PGSSLCOMPRESSION",
        "PGSSLCRL",
        "PGSSLCRLDIR",
        "PGSSLKEY",
        "PGSSLMAXPROTOCOLVERSION",
        "PGSSLMINPROTOCOLVERSION",
        "PGSSLMODE",
        "PGSSLNEGOTIATION",
        "PGSSLROOTCERT",
        "PGSSLSNI",
        "PGSYSCONFDIR",
        "PGTARGETSESSIONATTRS",
        "PGTZ",
        "PGUSER",
        "PIP_ABI",
        "PIP_ALL_RELEASES",
        "PIP_BREAK_SYSTEM_PACKAGES",
        "PIP_BUILD_CONSTRAINT",
        "PIP_CACHE_DIR",
        "PIP_CERT",
        "PIP_CHECK_BUILD_DEPENDENCIES",
        "PIP_CLIENT_CERT",
        "PIP_COMPILE",
        "PIP_CONFIG_FILE",
        "PIP_CONFIG_SETTINGS",
        "PIP_CONSTRAINT",
        "PIP_DEBUG",
        "PIP_DISABLE_PIP_VERSION_CHECK",
        "PIP_DRY_RUN",
        "PIP_EDITABLE",
        "PIP_EXISTS_ACTION",
        "PIP_EXTRA_INDEX_URL",
        "PIP_FIND_LINKS",
        "PIP_FORCE_REINSTALL",
        "PIP_GROUP",
        "PIP_HELP",
        "PIP_IGNORE_INSTALLED",
        "PIP_IGNORE_REQUIRES_PYTHON",
        "PIP_IMPLEMENTATION",
        "PIP_INDEX_URL",
        "PIP_ISOLATED",
        "PIP_KEYRING_PROVIDER",
        "PIP_LOG",
        "PIP_NO_BINARY",
        "PIP_NO_BUILD_ISOLATION",
        "PIP_NO_CACHE_DIR",
        "PIP_NO_CLEAN",
        "PIP_NO_COLOR",
        "PIP_NO_COMPILE",
        "PIP_NO_DEPS",
        "PIP_NO_INDEX",
        "PIP_NO_INPUT",
        "PIP_NO_WARN_CONFLICTS",
        "PIP_NO_WARN_SCRIPT_LOCATION",
        "PIP_ONLY_BINARY",
        "PIP_ONLY_FINAL",
        "PIP_PLATFORM",
        "PIP_PREFER_BINARY",
        "PIP_PRE",
        "PIP_PREFIX",
        "PIP_PROGRESS_BAR",
        "PIP_PROXY",
        "PIP_PYTHON",
        "PIP_PYTHON_VERSION",
        "PIP_QUIET",
        "PIP_REPORT",
        "PIP_REQUIREMENT",
        "PIP_REQUIREMENTS_FROM_SCRIPT",
        "PIP_REQUIRE_HASHES",
        "PIP_REQUIRE_VIRTUALENV",
        "PIP_RESUME_RETRIES",
        "PIP_RETRIES",
        "PIP_ROOT",
        "PIP_ROOT_USER_ACTION",
        "PIP_SRC",
        "PIP_TARGET",
        "PIP_TIMEOUT",
        "PIP_TRUSTED_HOST",
        "PIP_UPGRADE",
        "PIP_UPGRADE_STRATEGY",
        "PIP_UPLOADED_PRIOR_TO",
        "PIP_USE_DEPRECATED",
        "PIP_USE_FEATURE",
        "PIP_USE_PEP517",
        "PIP_USER",
        "PIP_VERBOSE",
        "PIP_VERSION",
        "PYLAUNCHER_ALLOW_INSTALL",
        "PYLAUNCHER_ALWAYS_INSTALL",
        "PYTHONHOME",
        "PYTHONPATH",
        "PYTHON_MANAGER_AUTOMATIC_INSTALL",
        "PYTEST_CURRENT_TEST",
        "TEMPLEDB_AI_MCP_HOST",
        "TEMPLEDB_AI_MCP_PORT",
        "TEMPLEDB_AI_MCP_TRANSPORT",
        "TEMPLEDB_AI_TOOLS_ENABLED",
        "TEMPLEDB_ALLOW_POSTGRESQL_DEMO",
        "TEMPLEDB_BACKUP_ADMIN_DATABASE",
        "TEMPLEDB_BACKUP_ADMIN_HOST",
        "TEMPLEDB_BACKUP_ADMIN_PASSWORD",
        "TEMPLEDB_BACKUP_ADMIN_PORT",
        "TEMPLEDB_BACKUP_ADMIN_USER",
        "TEMPLEDB_BACKUP_DESTINATION_PATH",
        "TEMPLEDB_BASE_URL",
        "TEMPLEDB_BIND_HOST",
        "TEMPLEDB_BROWSER_HOST",
        "TEMPLEDB_DATABASE_ENGINE",
        "TEMPLEDB_DEMO_ARCHIVE_PATH",
        "TEMPLEDB_DEMO_BUILD_TMPDIR",
        "TEMPLEDB_DEMO_DATASET_ID",
        "TEMPLEDB_DEMO_HOST",
        "TEMPLEDB_DEMO_MODE",
        "TEMPLEDB_DEMO_PASSWORD",
        "TEMPLEDB_DEMO_PORT",
        "TEMPLEDB_DEMO_USERNAME",
        "TEMPLEDB_EXTERNAL_BASE_URL",
        "TEMPLEDB_GOOGLE_SERVICE_ACCOUNT_FILE",
        "TEMPLEDB_GUNICORN_HOST",
        "TEMPLEDB_GUNICORN_PORT",
        "TEMPLEDB_GUNICORN_UPSTREAM",
        "TEMPLEDB_INSTANCE_PLATFORM_ROOT",
        "TEMPLEDB_LAUNCHER_DATABASE_ENGINE",
        "TEMPLEDB_LAUNCHER_ENV_FILE",
        "TEMPLEDB_LAUNCHER_EXPECTED_ENGINE",
        "TEMPLEDB_LAUNCHER_INSTANCE_LOCK_FD",
        "TEMPLEDB_LAUNCHER_LIFECYCLE_LOCK_DIR",
        "TEMPLEDB_LAUNCHER_POSTGRESQL_FORMULA",
        "TEMPLEDB_LAUNCHER_POSTGRESQL_LABEL",
        "TEMPLEDB_LAUNCHER_RUNTIME_DIR",
        "TEMPLEDB_LAUNCHER_SELECTED_INSTANCE",
        "TEMPLEDB_LAUNCHER_TENANT_ROOT",
        "TEMPLEDB_LEGACY_REIMPORT_ENABLED",
        "TEMPLEDB_MAX_AI_RERANK_CANDIDATES",
        "TEMPLEDB_MAX_AUTO_TAG_AI_CALLS_PER_RUN",
        "TEMPLEDB_MAX_AUTO_TAG_NOTES_PER_RUN",
        "TEMPLEDB_MAX_DYNAMIC_MEMO_TAGS",
        "TEMPLEDB_MAX_RENDERED_SEARCH_RESULTS",
        "TEMPLEDB_MEMORIAL_SHEET_PDF_RENDERER",
        "TEMPLEDB_MEMO_AI_MODELS",
        "TEMPLEDB_OPENAI_QUERY_TIMEOUT_SECONDS",
        "TEMPLEDB_OPENAI_RERANK_TIMEOUT_SECONDS",
        "TEMPLEDB_OPENAI_TAG_TIMEOUT_SECONDS",
        "TEMPLEDB_OPENAI_TIMEOUT_SECONDS",
        "TEMPLEDB_PDF_CHROME_BIN",
        "TEMPLEDB_PORT",
        "TEMPLEDB_POSTAL_SCAN_OCR_FALLBACK_CONFIDENCE",
        "TEMPLEDB_POSTAL_SCAN_OCR_FALLBACK_MODEL",
        "TEMPLEDB_POSTAL_SCAN_OCR_MODEL",
        "TEMPLEDB_POSTAL_SCAN_OCR_TIMEOUT_SECONDS",
        "TEMPLEDB_POSTAL_SCAN_REASONING_EFFORT",
        "TEMPLEDB_POSTAL_SCAN_REASONING_MODEL",
        "TEMPLEDB_POSTAL_SCAN_REASONING_TIMEOUT_SECONDS",
        "TEMPLEDB_POSTGRESQL_DEMO_MODE",
        "TEMPLEDB_POSTGRESQL_FORMULA",
        "TEMPLEDB_PRODUCT_HOST",
        "TEMPLEDB_PRODUCT_PORT",
        "TEMPLEDB_PRODUCT_SQLITE_MODE",
        "TEMPLEDB_RUNTIME_ROLE",
        "TEMPLEDB_SQLITE_DB_PATH",
        "TEMPLEDB_STAGING_ALLOW_OPENAI",
        "TEMPLEDB_STATIC_ROOT",
        "TEMPLEDB_TAILSCALE_SERVE",
        "TEMPLEDB_TENANT_ROOT",
        "TEMPLEDB_TRANSFER_TARGET_ADMIN_DATABASE",
        "TEMPLEDB_TRANSFER_TARGET_ADMIN_PASSWORD",
        "TEMPLEDB_TRANSFER_TARGET_ADMIN_USER",
        "TEMPLEDB_TRANSFER_TARGET_HOST",
        "TEMPLEDB_TRANSFER_TARGET_OWNER_PASSWORD",
        "TEMPLEDB_TRANSFER_TARGET_OWNER_USER",
        "TEMPLEDB_TRANSFER_TARGET_PORT",
        "TEMPLEDB_TRUSTED_PROXY_HTTPS",
        "TEMPLEDB_UI_THEME",
        "XDG_CACHE_HOME"
    )) {
        # A CLR null removes the name; a PowerShell null can bind as an empty
        # string on runtimes that support empty environment-variable values.
        [System.Environment]::SetEnvironmentVariable(
            $name,
            [NullString]::Value,
            [System.EnvironmentVariableTarget]::Process
        )
    }
}

function Set-TempleDbDemoEnvironment {
    Clear-TempleDbAmbientEnvironment
    $env:DJANGO_SETTINGS_MODULE = "config.settings"
    $env:DJANGO_SECRET_KEY = "templedb-demo-unsafe-local-key"
    $env:DJANGO_DEBUG = "1"
    $env:DJANGO_ALLOWED_HOSTS = "127.0.0.1,localhost"
    $env:TEMPLEDB_DATABASE_ENGINE = "sqlite"
    $env:TEMPLEDB_SQLITE_DB_PATH = [System.IO.Path]::GetFullPath($DatabasePath)
    $env:TEMPLEDB_DEMO_MODE = "1"
    $env:TEMPLEDB_DEMO_DATASET_ID = $DatasetId
    $env:TEMPLEDB_DEMO_USERNAME = "demo"
    $env:TEMPLEDB_DEMO_PASSWORD = "demo"
    $env:TEMPLEDB_DEMO_HOST = "127.0.0.1"
    $env:TEMPLEDB_DEMO_PORT = "8011"
    $env:TEMPLEDB_BASE_URL = "http://127.0.0.1:8011"
    $env:TEMPLEDB_RUNTIME_ROLE = "staging"
    $env:MPLCONFIGDIR = Join-Path $WindowsRuntimeRoot "matplotlib"
    $env:PIP_DISABLE_PIP_VERSION_CHECK = "1"
    $env:PYTHONIOENCODING = "utf-8"
    $env:PYTHONUTF8 = "1"
    $env:PYTHONDONTWRITEBYTECODE = "1"
    $env:PYTHON_MANAGER_AUTOMATIC_INSTALL = "false"
    $env:XDG_CACHE_HOME = Join-Path $WindowsRuntimeRoot "cache"
}

function Invoke-CheckedCommand {
    param(
        [string]$FilePath,
        [string[]]$ArgumentList,
        [string]$FailureMessage
    )

    & $FilePath @ArgumentList
    if ($LASTEXITCODE -ne 0) {
        Stop-TempleDbWindowsDemo $FailureMessage
    }
}

function Test-PythonCandidate {
    param(
        [string]$FilePath,
        [string[]]$PrefixArguments
    )

    $probe = @($PrefixArguments) + @(
        "-c",
        "import sqlite3, sys, sysconfig; ok = sys.implementation.name == 'cpython' and sys.platform == 'win32' and sys.version_info[:2] == (3, 13) and sysconfig.get_platform().lower() == 'win-arm64' and not sysconfig.get_config_var('Py_GIL_DISABLED'); raise SystemExit(0 if ok else 1)"
    )
    & $FilePath @probe 2>$null
    return $LASTEXITCODE -eq 0
}

function Select-BootstrapPython {
    if ($Python) {
        if (-not [System.IO.Path]::IsPathRooted($Python)) {
            Stop-TempleDbWindowsDemo "-Python must be an absolute path to python.exe."
        }
        $resolved = [System.IO.Path]::GetFullPath($Python)
        Assert-RegularPath -Path $resolved -Label "Python executable" -AllowOutsideWorkspace
        if (-not (Test-PythonCandidate -FilePath $resolved -PrefixArguments @())) {
            Stop-TempleDbWindowsDemo "The selected Python must be standard native ARM64 CPython 3.13 with sqlite3."
        }
        return [PSCustomObject]@{ Executable = $resolved; Prefix = @() }
    }

    $pyLauncher = Get-Command "py.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pyLauncher) {
        if (Test-PythonCandidate -FilePath $pyLauncher.Source -PrefixArguments @("-V:3.13-arm64")) {
            return [PSCustomObject]@{ Executable = $pyLauncher.Source; Prefix = @("-V:3.13-arm64") }
        }
        if (Test-PythonCandidate -FilePath $pyLauncher.Source -PrefixArguments @("-3.13")) {
            return [PSCustomObject]@{ Executable = $pyLauncher.Source; Prefix = @("-3.13") }
        }
    }

    $pythonCommand = Get-Command "python.exe" -ErrorAction SilentlyContinue
    if ($null -ne $pythonCommand) {
        if (Test-PythonCandidate -FilePath $pythonCommand.Source -PrefixArguments @()) {
            return [PSCustomObject]@{ Executable = $pythonCommand.Source; Prefix = @() }
        }
    }

    Stop-TempleDbWindowsDemo "Standard native ARM64 CPython 3.13 was not found. Install it explicitly before continuing."
}

function Invoke-BootstrapPython {
    param(
        [PSCustomObject]$Bootstrap,
        [string[]]$ArgumentList,
        [string]$FailureMessage
    )

    $arguments = @($Bootstrap.Prefix) + $ArgumentList
    Invoke-CheckedCommand -FilePath $Bootstrap.Executable -ArgumentList $arguments -FailureMessage $FailureMessage
}

function Assert-VenvPython {
    if (-not (Test-Path -LiteralPath $VenvPython -PathType Leaf)) {
        Stop-TempleDbWindowsDemo "Windows demo venv is missing. Run Setup first: $VenvPython"
    }
    Assert-OwnedDirectory -Path $VenvRoot -ExternalMarkerPath $VenvOwnershipMarker -SentinelPath $VenvOwnershipSentinel -ExpectedKind "templedb-windows-demo-venv-v1" -Label "Windows demo venv" | Out-Null
    Assert-RegularPath -Path $VenvPython -Label "Windows demo venv Python"
    if (-not (Test-PythonCandidate -FilePath $VenvPython -PrefixArguments @())) {
        Stop-TempleDbWindowsDemo "The Windows demo venv must use standard native ARM64 CPython 3.13 with sqlite3. Run Cleanup explicitly, then retry Setup."
    }
}

function Initialize-WindowsRuntimeRoot {
    Assert-NoWorkspaceReparsePoint -Path $RuntimeRoot -Label "Runtime root"
    if (-not (Test-Path -LiteralPath $RuntimeRoot)) {
        [System.IO.Directory]::CreateDirectory($RuntimeRoot) | Out-Null
    }
    Assert-RegularPath -Path $RuntimeRoot -Label "Runtime root" -Directory
    if (Test-Path -LiteralPath $WindowsRuntimeRoot) {
        Assert-OwnedDirectory -Path $WindowsRuntimeRoot -ExternalMarkerPath $RuntimeOwnershipMarker -SentinelPath $RuntimeOwnershipSentinel -ExpectedKind "templedb-windows-demo-runtime-v1" -Label "Windows demo runtime" | Out-Null
        return
    }
    if (Test-Path -LiteralPath $RuntimeOwnershipMarker) {
        Stop-TempleDbWindowsDemo "An orphaned Windows demo runtime marker exists. Run Cleanup before Setup."
    }
    New-OwnedDirectory -Path $WindowsRuntimeRoot -ExternalMarkerPath $RuntimeOwnershipMarker -SentinelPath $RuntimeOwnershipSentinel -ExpectedKind "templedb-windows-demo-runtime-v1" -Label "Windows demo runtime"
}

function Assert-WindowsRuntimeRoot {
    Assert-OwnedDirectory -Path $WindowsRuntimeRoot -ExternalMarkerPath $RuntimeOwnershipMarker -SentinelPath $RuntimeOwnershipSentinel -ExpectedKind "templedb-windows-demo-runtime-v1" -Label "Windows demo runtime" | Out-Null
}

function Initialize-WindowsVenv {
    if (Test-Path -LiteralPath $VenvRoot) {
        Assert-VenvPython
        return
    }
    $bootstrap = Select-BootstrapPython
    if (Test-Path -LiteralPath $VenvOwnershipMarker) {
        Stop-TempleDbWindowsDemo "An orphaned Windows demo venv marker exists. Run Cleanup before Setup."
    }
    New-OwnedDirectory -Path $VenvRoot -ExternalMarkerPath $VenvOwnershipMarker -SentinelPath $VenvOwnershipSentinel -ExpectedKind "templedb-windows-demo-venv-v1" -Label "Windows demo venv"
    Invoke-BootstrapPython -Bootstrap $bootstrap -ArgumentList @("-m", "venv", $VenvRoot) -FailureMessage "Could not create the isolated Windows demo venv."
    Assert-OwnedDirectory -Path $VenvRoot -ExternalMarkerPath $VenvOwnershipMarker -SentinelPath $VenvOwnershipSentinel -ExpectedKind "templedb-windows-demo-venv-v1" -Label "Windows demo venv" | Out-Null
    Assert-RegularPath -Path $VenvPython -Label "Windows demo venv Python"
    if (-not (Test-PythonCandidate -FilePath $VenvPython -PrefixArguments @())) {
        Stop-TempleDbWindowsDemo "The newly created Windows demo venv did not preserve the ARM64 CPython 3.13 contract."
    }
    Assert-VenvPython
}

function Write-WindowsDependencyRequirements {
    Assert-RegularPath -Path $PyprojectPath -Label "Application pyproject.toml"
    $includeAi = "0"
    if ($InstallAiTools) {
        $includeAi = "1"
    }
    $dependencyScript = "import pathlib, sys, tomllib; data = tomllib.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8')); dependencies = list(data['project']['dependencies']); dependencies.extend(data['project'].get('optional-dependencies', {}).get('ai', []) if sys.argv[3] == '1' else []); pathlib.Path(sys.argv[2]).write_text('\n'.join(dependencies) + '\n', encoding='utf-8')"
    Invoke-CheckedCommand -FilePath $VenvPython -ArgumentList @("-c", $dependencyScript, $PyprojectPath, $RequirementsPath, $includeAi) -FailureMessage "Could not prepare the isolated Windows dependency list."
    Assert-RegularPath -Path $RequirementsPath -Label "Windows dependency list"
}

function Invoke-ManagePy {
    param(
        [string[]]$ArgumentList,
        [string]$FailureMessage
    )

    $arguments = @($ManagePy) + $ArgumentList
    Invoke-CheckedCommand -FilePath $VenvPython -ArgumentList $arguments -FailureMessage $FailureMessage
}

function Assert-SingleLinkFile {
    param(
        [string]$Path,
        [string]$Label
    )

    Assert-RegularPath -Path $Path -Label $Label
    $probe = "import os, sys; raise SystemExit(0 if os.lstat(sys.argv[1]).st_nlink == 1 else 1)"
    & $VenvPython -c $probe $Path
    if ($LASTEXITCODE -ne 0) {
        Stop-TempleDbWindowsDemo "$Label must not be a hard link: $Path"
    }
}

function Assert-SeedArtifacts {
    param([switch]$AllowMissingMarkers)

    if ((Get-DemoSeedMode) -eq "packaged") {
        Assert-SingleLinkFile -Path $SeedDatabasePath -Label "Packaged synthetic demo database"
    }
    $datasetManifest = Read-JsonObject -Path $DatasetManifestPath -Label "Dataset manifest"
    $sourceId = [string]$datasetManifest.source_id
    $snapshotId = [string]$datasetManifest.prepared_snapshot_id
    if ($sourceId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$' -or $snapshotId -notmatch '^[A-Za-z0-9][A-Za-z0-9._-]*$') {
        Stop-TempleDbWindowsDemo "The synthetic dataset manifest is incomplete."
    }
    $exportRoot = Join-Path $AppRoot ("data\generated\legacy_exports\" + $sourceId)
    foreach ($path in @(
        (Join-Path $exportRoot "latest.json"),
        (Join-Path $exportRoot ($snapshotId + "\manifest.json")),
        (Join-Path $exportRoot ($snapshotId + "\export.log"))
    )) {
        Assert-NoWorkspaceReparsePoint -Path $path -Label "Synthetic demo export marker"
        if (-not $AllowMissingMarkers -or (Test-Path -LiteralPath $path)) {
            Assert-RegularPath -Path $path -Label "Synthetic demo export marker"
        }
    }
}

function Invoke-DatabaseIdentityVerification {
    param(
        [string]$Path,
        [string]$Label
    )

    Assert-SingleLinkFile -Path $Path -Label $Label
    $previousDatabasePath = $env:TEMPLEDB_SQLITE_DB_PATH
    try {
        $env:TEMPLEDB_SQLITE_DB_PATH = [System.IO.Path]::GetFullPath($Path)
        Invoke-ManagePy -ArgumentList @("verify_runtime_contract", "--engine", "sqlite", "--runtime-kind", "demo") -FailureMessage "$Label failed the demo database identity check."
    }
    finally {
        $env:TEMPLEDB_SQLITE_DB_PATH = $previousDatabasePath
    }
}

function Initialize-WindowsDemoDatabase {
    $seedMode = Get-DemoSeedMode
    if ($seedMode -eq "packaged") {
        Assert-SeedArtifacts
        Invoke-DatabaseIdentityVerification -Path $SeedDatabasePath -Label "Packaged synthetic demo database"
    }
    else {
        Assert-SeedArtifacts -AllowMissingMarkers
    }

    if (-not (Test-Path -LiteralPath $DatabasePath)) {
        $temporaryDirectoryPath = Join-Path $WindowsRuntimeRoot (".demo.sqlite3." + [Guid]::NewGuid().ToString("N") + ".tmp")
        $temporaryDatabasePath = Join-Path $temporaryDirectoryPath "demo.sqlite3"
        $temporaryDirectoryOwned = $false
        try {
            # Django permits initial migration only for a missing demo DB.
            # Reserve its parent exclusively, leaving the DB path absent.
            New-Item -ItemType Directory -Path $temporaryDirectoryPath | Out-Null
            $temporaryDirectoryOwned = $true
            Assert-RegularPath -Path $temporaryDirectoryPath -Label "Temporary Windows demo directory" -Directory
            if ($seedMode -eq "dataset") {
                Set-TempleDbDemoEnvironment
                $env:TEMPLEDB_SQLITE_DB_PATH = $temporaryDatabasePath
                Invoke-ManagePy -ArgumentList @("migrate", "--noinput") -FailureMessage "Could not create the isolated Windows demo schema."
                Invoke-ManagePy -ArgumentList @("load_demo_dataset", "--dataset-id", $DatasetId, "--dataset-root", $DatasetRoot, "--username", "demo", "--password", "demo") -FailureMessage "Could not load the synthetic Windows demo dataset."
                Invoke-ManagePy -ArgumentList @("check", "--fail-level", "ERROR") -FailureMessage "The new Windows demo failed Django system checks."
            }
            else {
                [System.IO.File]::Copy($SeedDatabasePath, $temporaryDatabasePath, $false)
            }
            Assert-SingleLinkFile -Path $temporaryDatabasePath -Label "Temporary Windows demo database"
            Invoke-DatabaseIdentityVerification -Path $temporaryDatabasePath -Label "Temporary Windows demo database"
            Assert-SeedArtifacts
            # The two-argument Move is exclusive: never replace an existing DB.
            [System.IO.File]::Move($temporaryDatabasePath, $DatabasePath)
        }
        finally {
            Set-TempleDbDemoEnvironment
            if ($temporaryDirectoryOwned -and (Test-Path -LiteralPath $temporaryDirectoryPath)) {
                Assert-NoNestedReparsePoint -Path $temporaryDirectoryPath -Label "Temporary Windows demo directory"
                Remove-Item -LiteralPath $temporaryDirectoryPath -Recurse -Force
            }
        }
    }

    Invoke-DatabaseIdentityVerification -Path $DatabasePath -Label "Windows demo database"
    Set-TempleDbDemoEnvironment
    Invoke-ManagePy -ArgumentList @("migrate", "--noinput") -FailureMessage "Could not apply migrations to the isolated Windows demo database."
}

function Invoke-DemoVerification {
    Assert-WindowsRuntimeRoot
    Assert-VenvPython
    Assert-SeedArtifacts
    if ((Get-DemoSeedMode) -eq "packaged") {
        Invoke-DatabaseIdentityVerification -Path $SeedDatabasePath -Label "Packaged synthetic demo database"
    }
    Invoke-DatabaseIdentityVerification -Path $DatabasePath -Label "Windows demo database"
    Set-TempleDbDemoEnvironment
    Invoke-CheckedCommand -FilePath $VenvPython -ArgumentList @("-m", "pip", "--isolated", "check") -FailureMessage "Python dependency verification failed."
    Invoke-ManagePy -ArgumentList @("migrate", "--check", "--skip-checks") -FailureMessage "The Windows demo database has pending migrations. Run Setup before Start."
    Invoke-ManagePy -ArgumentList @("check", "--fail-level", "ERROR") -FailureMessage "Django system check failed."
}

function Get-ServerGuardState {
    if (-not (Test-Path -LiteralPath $ServerGuardPath)) {
        return [PSCustomObject]@{ State = "absent"; Guard = $null; Process = $null }
    }
    $guard = Assert-OwnedMarker -Path $ServerGuardPath -ExpectedKind "templedb-windows-demo-server-v1" -Label "Windows demo server guard"
    foreach ($name in @("pid", "process_start_ticks", "ownership_token", "bind", "python", "manage_py")) {
        if (-not ($guard.PSObject.Properties.Name -contains $name)) {
            Stop-TempleDbWindowsDemo "The Windows demo server guard is incomplete."
        }
    }
    if ([string]$guard.bind -ne "127.0.0.1:8011") {
        Stop-TempleDbWindowsDemo "The Windows demo server guard has an unexpected listener."
    }
    if (
        [string]$guard.python -ne [System.IO.Path]::GetFullPath($VenvPython) -or
        [string]$guard.manage_py -ne [System.IO.Path]::GetFullPath($ManagePy)
    ) {
        Stop-TempleDbWindowsDemo "The Windows demo server guard has an unexpected executable path."
    }
    try {
        $process = [System.Diagnostics.Process]::GetProcessById([int]$guard.pid)
    }
    catch [System.ArgumentException] {
        return [PSCustomObject]@{ State = "stale"; Guard = $guard; Process = $null }
    }
    catch {
        return [PSCustomObject]@{ State = "unknown"; Guard = $guard; Process = $null }
    }
    try {
        $actualTicks = $process.StartTime.ToUniversalTime().Ticks
    }
    catch {
        return [PSCustomObject]@{ State = "unknown"; Guard = $guard; Process = $process }
    }
    if ([string]$actualTicks -eq [string]$guard.process_start_ticks) {
        return [PSCustomObject]@{ State = "live"; Guard = $guard; Process = $process }
    }
    return [PSCustomObject]@{ State = "stale"; Guard = $guard; Process = $process }
}

function Assert-DemoServerStopped {
    $guardState = Get-ServerGuardState
    if ($guardState.State -eq "live") {
        Stop-TempleDbWindowsDemo "The Windows demo server is still running. Stop it with Ctrl+C before continuing."
    }
    if ($guardState.State -eq "unknown") {
        Stop-TempleDbWindowsDemo "The Windows demo server state could not be verified. Close the server window and retry."
    }
    if ($guardState.State -eq "stale") {
        Remove-Item -LiteralPath $ServerGuardPath -Force
    }
}

function Write-ServerGuard {
    param(
        [System.Diagnostics.Process]$ServerProcess,
        [string]$OwnershipToken
    )

    $ServerProcess.Refresh()
    Write-JsonObjectCreateNew -Path $ServerGuardPath -Payload ([ordered]@{
        package_kind = "templedb-windows-demo-server-v1"
        pid = $ServerProcess.Id
        process_start_ticks = [string]$ServerProcess.StartTime.ToUniversalTime().Ticks
        ownership_token = $OwnershipToken
        bind = "127.0.0.1:8011"
        python = [System.IO.Path]::GetFullPath($VenvPython)
        manage_py = [System.IO.Path]::GetFullPath($ManagePy)
        created_at = [DateTime]::UtcNow.ToString("yyyy-MM-ddTHH:mm:ssZ")
    })
}

function Remove-OwnedServerGuard {
    param(
        [System.Diagnostics.Process]$ServerProcess,
        [string]$OwnershipToken
    )

    if (-not (Test-Path -LiteralPath $ServerGuardPath)) {
        return
    }
    $guard = Assert-OwnedMarker -Path $ServerGuardPath -ExpectedKind "templedb-windows-demo-server-v1" -Label "Windows demo server guard"
    foreach ($name in @("pid", "process_start_ticks", "ownership_token")) {
        if (-not ($guard.PSObject.Properties.Name -contains $name)) {
            return
        }
    }
    if (
        [string]$guard.ownership_token -ne $OwnershipToken -or
        [string]$guard.pid -ne [string]$ServerProcess.Id -or
        [string]$guard.process_start_ticks -ne [string]$ServerProcess.StartTime.ToUniversalTime().Ticks
    ) {
        return
    }
    Remove-Item -LiteralPath $ServerGuardPath -Force
}

function Write-EnvironmentRecord {
    $pythonVersion = & $VenvPython --version 2>&1
    $record = @(
        "# TempleDB Windows Demo Environment",
        "",
        "- prepared_at: $([DateTime]::UtcNow.ToString('yyyy-MM-ddTHH:mm:ssZ'))",
        "- scope: synthetic demo workspace only",
        "- python: $pythonVersion",
        "- database: runtime/windows-demo/demo.sqlite3",
        "- seed_mode: $(Get-DemoSeedMode)",
        "- packaged_seed: runtime/demo.sqlite3 (if bundled, preserved)",
        "- listener: 127.0.0.1:8011",
        "- cleanup: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Cleanup -ConfirmCleanup",
        ""
    )
    [System.IO.File]::WriteAllLines($EnvironmentLogPath, $record, $Utf8NoBom)
}

function Assert-NoNestedReparsePoint {
    param(
        [string]$Path,
        [string]$Label
    )

    $nestedReparsePoint = Get-ChildItem -LiteralPath $Path -Recurse -Force |
        Where-Object { ($_.Attributes -band [System.IO.FileAttributes]::ReparsePoint) -ne 0 } |
        Select-Object -First 1
    if ($null -ne $nestedReparsePoint) {
        Stop-TempleDbWindowsDemo "$Label contains a symbolic link or junction: $($nestedReparsePoint.FullName)"
    }
}

$operationLock = $null
$cleanupCompleted = $false
$scriptExitCode = 0

try {
    Assert-RegularPath -Path $WorkspaceRoot -Label "Workspace root" -Directory
    $operationLock = Enter-WindowsDemoOperationLock

    if ($Action -eq "Cleanup") {
        Assert-CleanupWorkspaceContract
    }
    else {
        Assert-WorkspaceContract
        Set-TempleDbDemoEnvironment
    }

    switch ($Action) {
        "Setup" {
            Initialize-WindowsRuntimeRoot
            Initialize-WindowsVenv
            Invoke-CheckedCommand -FilePath $VenvPython -ArgumentList @("-m", "pip", "--isolated", "install", "--upgrade", "--no-cache-dir", "--only-binary=:all:", "pip", "setuptools", "wheel") -FailureMessage "Could not prepare pip in the isolated Windows demo venv."
            Write-WindowsDependencyRequirements
            Invoke-CheckedCommand -FilePath $VenvPython -ArgumentList @("-m", "pip", "--isolated", "install", "--no-cache-dir", "--only-binary=:all:", "--requirement", $RequirementsPath) -FailureMessage "Could not install TempleDB dependencies into the isolated Windows demo venv."

            Initialize-WindowsDemoDatabase
            Invoke-DemoVerification
            $freeze = & $VenvPython -m pip --isolated freeze
            if ($LASTEXITCODE -ne 0) {
                Stop-TempleDbWindowsDemo "Could not record the installed dependency versions."
            }
            [System.IO.File]::WriteAllLines($PipFreezePath, [string[]]$freeze, $Utf8NoBom)
            Write-EnvironmentRecord
            Write-Host "TempleDB Windows demo setup completed."
            Write-Host "Windows demo is ready at runtime\windows-demo\demo.sqlite3 (seed mode: $(Get-DemoSeedMode))."
            Write-Host "Next: powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\bin\windows_demo.ps1 -Action Start"
        }

        "Verify" {
            Invoke-DemoVerification
            Write-Host "TempleDB Windows demo verification passed."
        }

        "Start" {
            Invoke-DemoVerification
            Assert-DemoServerStopped
            Set-TempleDbDemoEnvironment
            Write-Host "Starting TempleDB demo at http://127.0.0.1:8011/"
            Write-Host "Login: demo / demo"
            Write-Host "Press Ctrl+C in this window to stop the server."

            $serverProcess = $null
            $serverGuardPublished = $false
            $ownershipToken = [Guid]::NewGuid().ToString("N")
            $scriptExitCode = 1
            try {
                $serverProcess = Start-Process -FilePath $VenvPython -ArgumentList @("manage.py", "runserver", "--noreload", "--nothreading", "127.0.0.1:8011") -WorkingDirectory $AppRoot -NoNewWindow -PassThru
                Write-ServerGuard -ServerProcess $serverProcess -OwnershipToken $ownershipToken
                $serverGuardPublished = $true
                Wait-Process -Id $serverProcess.Id
                $serverProcess.Refresh()
                if ($serverProcess.HasExited) {
                    $scriptExitCode = $serverProcess.ExitCode
                }
            }
            finally {
                if ($null -ne $serverProcess) {
                    $serverProcess.Refresh()
                    if (-not $serverProcess.HasExited) {
                        if ($serverGuardPublished) {
                            $stoppedNaturally = $serverProcess.WaitForExit(10000)
                            if (-not $stoppedNaturally) {
                                [Console]::Error.WriteLine(
                                    "The Python demo server did not stop within 10 seconds. It was not force-killed; close it before retrying."
                                )
                                $scriptExitCode = 1
                            }
                        }
                        else {
                            $stoppedBeforeGuard = $serverProcess.WaitForExit(3000)
                            if (-not $stoppedBeforeGuard) {
                                $serverProcess.Kill()
                                $serverProcess.WaitForExit()
                            }
                        }
                    }
                    $serverProcess.Refresh()
                    if ($serverProcess.HasExited -and $serverGuardPublished) {
                        Remove-OwnedServerGuard -ServerProcess $serverProcess -OwnershipToken $ownershipToken
                    }
                    $serverProcess.Dispose()
                }
            }
        }

        "Cleanup" {
            if (-not $ConfirmCleanup) {
                Stop-TempleDbWindowsDemo "Cleanup requires -ConfirmCleanup and only removes Windows-generated files inside this starter workspace."
            }

            if (Test-Path -LiteralPath $WindowsRuntimeRoot) {
                Assert-DemoServerStopped
                Assert-NoNestedReparsePoint -Path $WindowsRuntimeRoot -Label "Windows demo runtime"
            }
            if (Test-Path -LiteralPath $VenvRoot) {
                Assert-NoNestedReparsePoint -Path $VenvRoot -Label "Windows demo venv"
            }

            if (Test-Path -LiteralPath $VenvRoot) {
                Remove-OwnedDirectorySafely -Path $VenvRoot -ExternalMarkerPath $VenvOwnershipMarker -SentinelPath $VenvOwnershipSentinel -ExpectedKind "templedb-windows-demo-venv-v1" -Label "Windows demo venv"
            }
            elseif (Test-Path -LiteralPath $VenvOwnershipMarker) {
                $venvMarker = Assert-ExternalOwnershipMarker -Path $VenvOwnershipMarker -ExpectedKind "templedb-windows-demo-venv-v1" -ExpectedTargetPath $VenvRoot -Label "Windows demo venv marker"
                Remove-OwnedJsonMarkerIfToken -Path $VenvOwnershipMarker -ExpectedKind "templedb-windows-demo-venv-v1" -OwnershipToken ([string]$venvMarker.ownership_token)
            }
            if (Test-Path -LiteralPath $WindowsRuntimeRoot) {
                Remove-OwnedDirectorySafely -Path $WindowsRuntimeRoot -ExternalMarkerPath $RuntimeOwnershipMarker -SentinelPath $RuntimeOwnershipSentinel -ExpectedKind "templedb-windows-demo-runtime-v1" -Label "Windows demo runtime"
            }
            elseif (Test-Path -LiteralPath $RuntimeOwnershipMarker) {
                $runtimeMarker = Assert-ExternalOwnershipMarker -Path $RuntimeOwnershipMarker -ExpectedKind "templedb-windows-demo-runtime-v1" -ExpectedTargetPath $WindowsRuntimeRoot -Label "Windows demo runtime marker"
                Remove-OwnedJsonMarkerIfToken -Path $RuntimeOwnershipMarker -ExpectedKind "templedb-windows-demo-runtime-v1" -OwnershipToken ([string]$runtimeMarker.ownership_token)
            }
            $cleanupCompleted = $true
            Write-Host "The isolated Windows demo venv, working database, and local records were removed."
            Write-Host "The packaged seed database, Python, and machine-level settings were not changed."
        }
    }
}
catch {
    [Console]::Error.WriteLine($_.Exception.Message)
    $scriptExitCode = 1
}
finally {
    if ($null -ne $operationLock) {
        $operationLock.Stream.Dispose()
    }
    if ($cleanupCompleted -and $null -ne $operationLock) {
        Remove-OwnedOperationLock -OwnershipToken $operationLock.OwnershipToken
    }
}

exit $scriptExitCode
