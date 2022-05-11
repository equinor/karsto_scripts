[CmdletBinding()]
Param(
    [Parameter(Mandatory)]
    [string]$Pattern
)

$files = Get-ChildItem -Exclude *Workspace* | Get-ChildItem -Include *.atgraphic,*.apx,*.atplot -File -Force -Recurse

foreach ($file in $files) {
    if ($file | Select-String -Pattern $Pattern -Encoding unicode -Quiet) {
        Write-Output $file.PSPath
    }
}
