[CmdletBinding()]
Param(
    [Parameter(Mandatory)]
    [string]$Pattern
)

$files = Get-ChildItem -Exclude *Workspace* | Get-ChildItem -Include *.atgraphic,*.apx,*.atplot -File -Force -Recurse

foreach ($file in $files) {
    $search_result = $file | Select-String -Pattern $Pattern -Encoding unicode -AllMatches

    if ($search_result) {
        Write-Output $file.PSPath
        foreach ($result in $search_result) {
            foreach ($match in $result.Matches) {
                Write-Output $match.Value
            }
        }
    }
}
