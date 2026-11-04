param([Parameter(Mandatory = $true)][string]$Folder)
$ErrorActionPreference = 'Stop'
$excel = $null
$book = $null
try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $calc = Get-ChildItem -LiteralPath $Folder -Filter '*.xls' | Select-Object -First 1
    $cost = Get-ChildItem -LiteralPath $Folder -Filter '*.xlsx' | Select-Object -First 1
    $book = $excel.Workbooks.Open($calc.FullName, 0, $true)
    $book.Worksheets.Item('Total').ExportAsFixedFormat(0, (Join-Path $Folder '_preview_calculo.pdf'))
    $book.Close($false)
    $book = $excel.Workbooks.Open($cost.FullName, 0, $true)
    $book.Worksheets.Item(1).ExportAsFixedFormat(0, (Join-Path $Folder '_preview_custo_mp.pdf'))
    $book.Worksheets.Item(2).ExportAsFixedFormat(0, (Join-Path $Folder '_preview_custo_comprados.pdf'))
    $book.Close($false)
    $book = $null
} finally {
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $excel) {
        $excel.Quit()
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
    }
}
