[CmdletBinding()]
param(
  [Parameter(ValueFromRemainingArguments = $true)]
  [string[]]$PassThroughArgs
)

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$pythonScript = Join-Path $scriptDir 'harmony_build.py'

$pythonCommands = @(
  @('py', '-3'),
  @('python'),
  @('python3')
)

foreach ($candidate in $pythonCommands) {
  $commandName = $candidate[0]
  if (Get-Command $commandName -ErrorAction SilentlyContinue) {
    $prefixArgs = @()
    if ($candidate.Length -gt 1) {
      $prefixArgs = $candidate[1..($candidate.Length - 1)]
    }
    & $candidate[0] @prefixArgs $pythonScript @PassThroughArgs
    exit $LASTEXITCODE
  }
}

Write-Error 'No Python launcher was found. Install Python or use py/python/python3 from PATH.'
exit 1
