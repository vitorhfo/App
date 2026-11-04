param([Parameter(Mandatory = $true)][string]$PayloadPath)

$ErrorActionPreference = 'Stop'
$data = Get-Content -LiteralPath $PayloadPath -Raw -Encoding UTF8 | ConvertFrom-Json
$excel = $null
$book = $null

function Set-Cell($sheet, [string]$address, $value) {
    $cell = $sheet.Range($address)
    try {
        if ($null -eq $value) { $cell.ClearContents() | Out-Null }
        elseif ($value -is [string]) { $cell.Formula = $value }
        else {
            $numericText = ([double]$value).ToString('0.############', [Globalization.CultureInfo]::InvariantCulture)
            $cell.Formula = $numericText
        }
    } catch {
        throw "Célula $address, tipo $($value.GetType().FullName), valor '$value': $($_.Exception.Message)"
    }
}

function Fill-Section($sheet, [int]$first, [int]$last, [int]$subtotal, $items, [string]$kind) {
    if ($null -eq $items) { $items = @() }
    else { $items = @($items) }
    $capacity = $last - $first + 1
    $count = @($items).Count
    $extra = [Math]::Max(0, $count - $capacity)
    if ($extra -gt 0) {
        $sheet.Rows("${last}:$($last + $extra - 1)").Insert() | Out-Null
        $sourceRow = $last + $extra
        for ($r = $last; $r -lt $last + $extra; $r++) {
            [void]$sheet.Range("B${sourceRow}:G${sourceRow}").Copy($sheet.Range("B${r}:G${r}"))
        }
    }
    $end = $last + $extra
    $sheet.Range("B${first}:G${end}").ClearContents() | Out-Null
    for ($i = 0; $i -lt $count; $i++) {
        $item = $items[$i]
        $r = $first + $i
        Set-Cell $sheet "B$r" $item.description
        if ($kind -eq 'comprado') {
            Set-Cell $sheet "C$r" $item.quantity
            if ($null -ne $item.unit_price) {
                Set-Cell $sheet "D$r" $item.unit_price
                Set-Cell $sheet "G$r" "=ROUND(C$r*D$r,2)"
            }
            continue
        }
        # O peso-base unitário conserva a precisão usada pelo app no custo.
        # O total exibido pode ter sido arredondado para quatro casas.
        if ($null -ne $item.cost_weight -and $item.cost_weight -gt 0) {
            Set-Cell $sheet "C$r" $item.cost_weight
        } elseif ($null -ne $item.total_weight -and $item.total_weight -gt 0) {
            Set-Cell $sheet "C$r" $item.total_weight
        }
        if ($null -ne $item.aggregate_total_price) {
            $aggregateWeight = $item.cost_weight
            if ($null -eq $aggregateWeight -or $aggregateWeight -le 0) { $aggregateWeight = $item.total_weight }
            if ($null -ne $aggregateWeight -and $aggregateWeight -gt 0) {
                $effectiveRate = [double]$item.aggregate_total_price / [double]$aggregateWeight
                if ($kind -ne 'chapa' -and $null -ne $item.unit_price -and $null -ne $item.rate -and $null -ne $item.factor) {
                    $gross = [double]$item.rate * (1 + [double]$item.ipi_pct / 100)
                    Set-Cell $sheet "D$r" $gross
                    Set-Cell $sheet "F$r" $effectiveRate
                    Set-Cell $sheet "E$r" "=D$r-F$r"
                } else {
                    Set-Cell $sheet "F$r" $effectiveRate
                }
                Set-Cell $sheet "G$r" "=ROUND(C$r*F$r,2)"
            } elseif ($null -ne $item.unit_price -and $null -ne $item.rate -and $null -ne $item.factor) {
                $gross = [double]$item.rate * (1 + [double]$item.ipi_pct / 100)
                if ($kind -eq 'chapa') {
                    Set-Cell $sheet "F$r" ($gross * [double]$item.factor)
                } else {
                    Set-Cell $sheet "D$r" $gross
                    $factorText = ([double]$item.factor).ToString('0.##########', [Globalization.CultureInfo]::InvariantCulture)
                    Set-Cell $sheet "F$r" "=D$r*$factorText"
                    Set-Cell $sheet "E$r" "=D$r-F$r"
                }
                Set-Cell $sheet "G$r" $item.aggregate_total_price
            } else {
                Set-Cell $sheet "G$r" $item.aggregate_total_price
            }
            continue
        }
        if ($null -ne $item.unit_price) {
            if ($null -ne $item.rate -and $null -ne $item.factor) {
                $gross = [double]$item.rate * (1 + [double]$item.ipi_pct / 100)
                if ($kind -eq 'chapa') {
                    Set-Cell $sheet "F$r" ($gross * [double]$item.factor)
                } else {
                    Set-Cell $sheet "D$r" $gross
                    $factorText = ([double]$item.factor).ToString('0.##########', [Globalization.CultureInfo]::InvariantCulture)
                    Set-Cell $sheet "F$r" "=D$r*$factorText"
                    Set-Cell $sheet "E$r" "=D$r-F$r"
                }
                if ($null -ne $item.total_weight -and $item.total_weight -gt 0) {
                    # O app arredonda o preço de cada peça a 4 casas antes de
                    # multiplicar pela quantidade. Repetir essa ordem mantém
                    # o subtotal da planilha igual ao orçamento salvo.
                    $qtyText = ([double]$item.quantity).ToString('0.##########', [Globalization.CultureInfo]::InvariantCulture)
                    if ([double]$item.quantity -gt 0) {
                        Set-Cell $sheet "G$r" "=ROUND(ROUND(C$r*F$r/$qtyText,4)*$qtyText,2)"
                    } else {
                        Set-Cell $sheet "G$r" "=ROUND(C$r*F$r,2)"
                    }
                } else {
                    Set-Cell $sheet "G$r" $item.total_price
                }
            } elseif ($null -ne $item.total_weight -and $item.total_weight -gt 0) {
                Set-Cell $sheet "F$r" ([double]$item.total_price / [double]$item.total_weight)
                Set-Cell $sheet "G$r" "=ROUND(C$r*F$r,2)"
            } else {
                Set-Cell $sheet "G$r" $item.total_price
            }
        }
    }
    $totalRow = $subtotal + $extra
    if ($kind -eq 'comprado') {
        Set-Cell $sheet "G$totalRow" "=SUM(G${first}:G${end})"
    } else {
        Set-Cell $sheet "C$totalRow" "=SUM(C${first}:C${end})"
        Set-Cell $sheet "G$totalRow" "=SUM(G${first}:G${end})"
    }
    return $extra
}

try {
    $excel = New-Object -ComObject Excel.Application
    $excel.Visible = $false
    $excel.DisplayAlerts = $false
    $excel.AskToUpdateLinks = $false
    $excel.EnableEvents = $false

    foreach ($page in $data.calculations) {
        $book = $excel.Workbooks.Open([string]$page.path, 0, $false)
        $sheet = $book.Worksheets.Item('Total')
        foreach ($property in $page.cells.PSObject.Properties) {
            Set-Cell $sheet $property.Name $property.Value
        }
        $excel.Calculate()
        $book.Save()
        $book.Close($false)
        $book = $null
    }

    if ($null -ne $data.cost_path -and [string]$data.cost_path -ne '') {
    $book = $excel.Workbooks.Open([string]$data.cost_path, 0, $false)
    $mp = $book.Worksheets.Item(1)
    $bought = $book.Worksheets.Item(2)

    # De baixo para cima: as inserções anteriores movem as seções já prontas,
    # mas não alteram as coordenadas das seções ainda não processadas.
    $paintExtra = Fill-Section $mp 37 39 40 $data.sections.paint 'tinta'
    $sheetExtra = Fill-Section $mp 25 29 32 $data.sections.sheet 'chapa'
    $wireExtra = Fill-Section $mp 18 21 22 $data.sections.wire 'arame'
    $tubeExtra = Fill-Section $mp 9 13 15 $data.sections.tube 'tubo'
    $totalRow = 42 + $tubeExtra + $wireExtra + $sheetExtra + $paintExtra
    $tubeTotal = 15 + $tubeExtra
    $wireTotal = 22 + $tubeExtra + $wireExtra
    $sheetTotal = 32 + $tubeExtra + $wireExtra + $sheetExtra
    $paintTotal = 40 + $tubeExtra + $wireExtra + $sheetExtra + $paintExtra
    Set-Cell $mp "C$totalRow" "=SUM(C$tubeTotal,C$wireTotal,C$sheetTotal)"
    Set-Cell $mp "G$totalRow" "=SUM(G$tubeTotal,G$wireTotal,G$sheetTotal,G$paintTotal)"

    $null = Fill-Section $bought 9 29 30 $data.sections.bought 'comprado'

    Set-Cell $mp 'E5' $data.client
    Set-Cell $mp 'B7' "DESCRIÇÃO DO ITEM: $($data.project_name)"
    Set-Cell $mp 'E7' "Data Orçamento: $($data.project_date)"
    Set-Cell $bought 'E5' $data.client
    $excel.Calculate()
    $book.Save()
    $book.Close($false)
    $book = $null
    }
} catch {
    Write-Error "$($_.Exception.Message) -- $($_.ScriptStackTrace)"
    throw
} finally {
    if ($null -ne $book) { $book.Close($false) }
    if ($null -ne $excel) {
        $excel.Quit()
        [void][System.Runtime.InteropServices.Marshal]::FinalReleaseComObject($excel)
    }
    [GC]::Collect()
    [GC]::WaitForPendingFinalizers()
}
