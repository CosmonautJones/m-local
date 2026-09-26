param([string]$Distribution = 'Ubuntu')
$ErrorActionPreference = 'Stop'
$repoPath = Split-Path -Parent $PSScriptRoot
& wsl.exe -d $Distribution --cd $repoPath --exec bash scripts/dev.sh
exit $LASTEXITCODE
