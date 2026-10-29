Set-StrictMode -Version Latest

$script:ModuleRoot = Split-Path -Parent $PSScriptRoot
$script:SchemaPath = Join-Path $script:ModuleRoot 'sql/schema.sql'

function Quote-SqlLiteral([string]$Value) {
    if ($null -eq $Value) { return 'NULL' }
    return "'" + ($Value -replace "'", "''") + "'"
}

function Invoke-PhoneDuckDb {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$DatabasePath,
        [Parameter(Mandatory)] [string]$Sql,
        [switch]$Quiet
    )
    $duckdb = if ($env:DUCKDB_PATH) { $env:DUCKDB_PATH } else { 'duckdb' }
    $output = & $duckdb $DatabasePath '-csv' '-header' '-c' $Sql 2>&1
    if ($LASTEXITCODE -ne 0) { throw "DuckDB failed: $($output -join [Environment]::NewLine)" }
    if (-not $Quiet) { return $output }
}

function Initialize-PhoneDatabase {
    [CmdletBinding()]
    param([string]$DatabasePath = (Join-Path (Get-Location) 'phones.duckdb'))
    $parent = Split-Path -Parent (Resolve-Path -LiteralPath $DatabasePath -ErrorAction SilentlyContinue)
    if ($parent) { New-Item -ItemType Directory -Force -Path $parent | Out-Null }
    $schema = Get-Content -Raw -LiteralPath $script:SchemaPath
    Invoke-PhoneDuckDb -DatabasePath $DatabasePath -Sql $schema -Quiet
    return (Resolve-Path -LiteralPath $DatabasePath).Path
}

function Get-XmlValue($Node, [string]$XPath) {
    if ($null -eq $Node) { return $null }
    $n = $Node.SelectSingleNode($XPath)
    if ($null -eq $n) { return $null }
    $v = $n.InnerText.Trim()
    if ($v.Length -eq 0) { return $null }
    return $v
}

function Get-XmlAttribute($Node, [string]$XPath, [string]$Name) {
    if ($null -eq $Node) { return $null }
    $n = $Node.SelectSingleNode($XPath)
    if ($null -eq $n -or $null -eq $n.Attributes[$Name]) { return $null }
    return $n.Attributes[$Name].Value
}

function Convert-ToNullableDouble($Value) {
    if ([string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    return [double]::Parse($Value, [Globalization.CultureInfo]::InvariantCulture)
}

function Convert-ToNullableInt($Value) {
    if ([string]::IsNullOrWhiteSpace([string]$Value)) { return $null }
    return [int]$Value
}

function Import-DfrpXml {
    [CmdletBinding()]
    param(
        [Parameter(Mandatory)] [string]$XmlPath,
        [Parameter(Mandatory)] [string]$DatabasePath
    )
    Initialize-PhoneDatabase $DatabasePath | Out-Null
    $properties = [Collections.Generic.List[object]]::new()
    $locations = [Collections.Generic.List[object]]::new()
    $structures = [Collections.Generic.List[object]]::new()
    $imported = (Get-Date).ToUniversalTime().ToString('s')
    $reader = [Xml.XmlReader]::Create((Resolve-Path $XmlPath).Path)
    try {
        while ($reader.Read()) {
            if ($reader.NodeType -ne [Xml.XmlNodeType]::Element -or $reader.Name -ne 'Property') { continue }
            $subtree = $reader.ReadSubtree()
            $doc = [Xml.XmlDocument]::new()
            $doc.Load($subtree)
            $subtree.Dispose()
            $root = $doc.DocumentElement
            $pn = Get-XmlValue $root 'Property_Number'
            if (-not $pn) { continue }
            $properties.Add([pscustomobject]@{
                property_number=$pn; property_name_en=(Get-XmlValue $root 'Property_Name_E'); property_name_fr=(Get-XmlValue $root 'Property_Name_F')
                address_en=(Get-XmlValue $root 'Address_E'); address_fr=(Get-XmlValue $root 'Address_F')
                primary_use_en=(Get-XmlValue $root 'Primary_Use_E'); primary_use_code=(Get-XmlAttribute $root 'Primary_Use_E' 'code')
                interest_type_en=(Get-XmlValue $root 'Interest_Type_E'); interest_type_code=(Get-XmlAttribute $root 'Interest_Type_E' 'code')
                restriction_en=(Get-XmlValue $root 'Restriction_on_Interest_E'); created_date=(Get-XmlValue $root '@createdDate')
                last_modified_date=(Get-XmlValue $root '@lastModifiedDate'); source_file=(Split-Path $XmlPath -Leaf); imported_at=$imported
            })
            foreach ($parcel in $root.SelectNodes('Parcels/Parcel')) {
                $loc = $parcel.SelectSingleNode('Location')
                if ($loc) {
                    $locations.Add([pscustomobject]@{
                        property_number=$pn; parcel_number=$parcel.GetAttribute('Number'); sgc=$loc.GetAttribute('sgc'); fed=$loc.GetAttribute('fed'); location_type=$loc.GetAttribute('type'); rural_area=($loc.GetAttribute('inRuralArea') -eq 'true')
                        province_en=(Get-XmlValue $loc 'Province_E'); municipality_en=(Get-XmlValue $loc 'Municipality_E'); place_name_en=(Get-XmlValue $loc 'Place_Name_EN'); metro_area_en=(Get-XmlValue $loc 'Metro_Area_Name_E')
                        latitude=(Convert-ToNullableDouble (Get-XmlValue $loc 'Latitude')); longitude=(Convert-ToNullableDouble (Get-XmlValue $loc 'Longitude')); positional_accuracy_m=(Convert-ToNullableDouble (Get-XmlValue $loc 'Positional_Accuracy')); country_code=(Get-XmlAttribute $loc 'Country_Name_E' 'code')
                        source_file=(Split-Path $XmlPath -Leaf); imported_at=$imported
                    })
                }
                foreach ($structure in $parcel.SelectNodes('Structures/Structure')) {
                    $sloc = $structure.SelectSingleNode('Location')
                    $structures.Add([pscustomobject]@{
                        property_number=$pn; parcel_number=$parcel.GetAttribute('Number'); structure_number=(Get-XmlValue $structure 'Structure_Number'); structure_name_en=(Get-XmlValue $structure 'Structure_Name_E'); address_en=(Get-XmlValue $structure 'Address_E')
                        latitude=(Convert-ToNullableDouble (Get-XmlValue $sloc 'Latitude')); longitude=(Convert-ToNullableDouble (Get-XmlValue $sloc 'Longitude')); construction_year=(Convert-ToNullableInt (Get-XmlValue $structure 'Construction_Year')); condition_en=(Get-XmlValue $structure 'Condition_E'); floor_area_sqm=(Convert-ToNullableDouble (Get-XmlValue $structure 'Floor_Area')); source_file=(Split-Path $XmlPath -Leaf); imported_at=$imported
                    })
                }
            }
        }
    } finally { $reader.Dispose() }
    $stage = Join-Path ([IO.Path]::GetTempPath()) ('phones-' + [guid]::NewGuid())
    New-Item -ItemType Directory -Path $stage | Out-Null
    try {
        @(@{Rows=$properties; Table='dfrp.properties'}, @{Rows=$locations; Table='dfrp.locations'}, @{Rows=$structures; Table='dfrp.structures'}) | ForEach-Object {
            $csv = Join-Path $stage ($_.Table.Replace('.', '-') + '.csv')
            $_.Rows | Export-Csv -LiteralPath $csv -NoTypeInformation -Encoding UTF8
            $sql = "DELETE FROM $($_.Table); INSERT INTO $($_.Table) SELECT * FROM read_csv_auto(" + (Quote-SqlLiteral $csv) + ", header=true, union_by_name=true, nullstr='');"
            Invoke-PhoneDuckDb $DatabasePath $sql -Quiet
        }
    } finally { Remove-Item -Recurse -Force $stage -ErrorAction SilentlyContinue }
    [pscustomobject]@{ Properties=$properties.Count; Locations=$locations.Count; Structures=$structures.Count }
}

function Import-CnaCoCodes {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$CsvPath, [Parameter(Mandatory)][string]$DatabasePath)
    Initialize-PhoneDatabase $DatabasePath | Out-Null
    $stage = Join-Path ([IO.Path]::GetTempPath()) ('cna-' + [guid]::NewGuid() + '.csv')
    $rows = Import-Csv $CsvPath | Where-Object { $_.NPA -match '^\d{3}$' -and $_.'CO Code (NXX)' -match '^\d{3}$' }
    $snapshot = (Get-Item $CsvPath).LastWriteTime.ToString('yyyy-MM-dd')
    $rows | ForEach-Object {
        [pscustomobject]@{ npa=$_.NPA; nxx=$_.'CO Code (NXX)'; status=$_.Status; pooled=$_.Pooled; exchange_area=$_.'Exchange Area'; province=$_.Province; company=$_.Company; ocn=$_.OCN; date_assigned=$_.'Date Assigned'; remarks=$_.Remarks; source_url='https://www.cnac.ca/data/COCodeStatus_ALL.zip'; source_snapshot_date=$snapshot; imported_at=(Get-Date).ToUniversalTime().ToString('s') }
    } | Export-Csv $stage -NoTypeInformation -Encoding UTF8
    try {
        $sql = "DELETE FROM telephone.co_codes; INSERT INTO telephone.co_codes SELECT * FROM read_csv_auto(" + (Quote-SqlLiteral $stage) + ", header=true, union_by_name=true, nullstr='');"
        Invoke-PhoneDuckDb $DatabasePath $sql -Quiet
    } finally { Remove-Item $stage -Force -ErrorAction SilentlyContinue }
    return $rows.Count
}

function Normalize-PhoneText([string]$Text) {
    if ($null -eq $Text) { return '' }
    $normalized = $Text.Normalize([Text.NormalizationForm]::FormD) -replace '\p{Mn}', ''
    return (($normalized.ToLowerInvariant() -replace '[^a-z0-9]+', ' ').Trim() -replace '\s+', ' ')
}

function Get-LevenshteinDistance([string]$A, [string]$B) {
    $a = Normalize-PhoneText $A; $b = Normalize-PhoneText $B
    $previous = 0..$b.Length
    for ($i=1; $i -le $a.Length; $i++) {
        $current = New-Object int[] ($b.Length + 1); $current[0] = $i
        for ($j=1; $j -le $b.Length; $j++) { $cost = if ($a[$i-1] -eq $b[$j-1]) { 0 } else { 1 }; $current[$j] = [Math]::Min([Math]::Min($current[$j-1]+1, $previous[$j]+1), $previous[$j-1]+$cost) }
        $previous = $current
    }
    return $previous[$b.Length]
}

function Get-FuzzyPhoneScore([string]$Query, [string]$Text) {
    $q = Normalize-PhoneText $Query; $t = Normalize-PhoneText $Text
    if (-not $q -or -not $t) { return 0.0 }
    if ($t -eq $q) { return 1.0 }
    $tokens = $q -split ' ' | Where-Object { $_.Length -gt 1 }
    $hits = @($tokens | Where-Object { $t.Contains($_) }).Count
    $tokenScore = if ($tokens.Count) { $hits / $tokens.Count } else { 0 }
    $maxLen = [Math]::Max($q.Length, $t.Length); $edit = 1 - ((Get-LevenshteinDistance $q $t) / [double]$maxLen)
    return [Math]::Round((0.65 * $tokenScore) + (0.35 * [Math]::Max(0, $edit)), 4)
}

function Find-FederalOffice {
    [CmdletBinding()]
    param([Parameter(Mandatory, Position=0)][string]$Query, [string]$DatabasePath='phones.duckdb', [double]$MinimumScore=0.35, [int]$Limit=25)
    $safe = $Query -replace "'", "''"
    $sql = "SELECT * FROM dfrp.property_search WHERE lower(search_text) LIKE '%' || lower('$safe') || '%' OR lower(search_text) LIKE '%' || lower(split_part('$safe',' ',1)) || '%' LIMIT 500;"
    $rows = @(Invoke-PhoneDuckDb $DatabasePath $sql | ConvertFrom-Csv)
    if (-not $rows) { $rows = @(Invoke-PhoneDuckDb $DatabasePath 'SELECT * FROM dfrp.property_search LIMIT 500;' | ConvertFrom-Csv) }
    $rows | ForEach-Object { $text = $_.search_text; $score = Get-FuzzyPhoneScore $Query $text; if ($score -ge $MinimumScore) { $_ | Add-Member NoteProperty MatchScore $score -PassThru } } | Sort-Object MatchScore -Descending | Select-Object -First $Limit
}

function Find-Exchange {
    [CmdletBinding()]
    param([Parameter(Mandatory, Position=0)][string]$Query, [string]$DatabasePath='phones.duckdb', [double]$MinimumScore=0.35, [int]$Limit=25)
    $rows = @(Invoke-PhoneDuckDb $DatabasePath 'SELECT * FROM telephone.exchange_search WHERE status = ''In Service'';' | ConvertFrom-Csv)
    $rows | ForEach-Object { $score = Get-FuzzyPhoneScore $Query $_.search_text; if ($score -ge $MinimumScore) { $_ | Add-Member NoteProperty MatchScore $score -PassThru } } | Sort-Object MatchScore -Descending | Select-Object -First $Limit
}

function Get-PropertyTelephone {
    [CmdletBinding()]
    param([Parameter(Mandatory)][string]$PropertyNumber, [string]$DatabasePath='phones.duckdb')
    $sql = "SELECT p.property_number, p.property_name_en, p.municipality_en, p.place_name_en, e.npa, e.nxx, e.exchange_area, e.province, e.company, e.status FROM dfrp.property_search p LEFT JOIN telephone.co_codes e ON (lower(e.exchange_area) = lower(p.municipality_en) OR lower(e.exchange_area) = lower(regexp_replace(coalesce(p.place_name_en, ''), ', [A-Z]{2}$', ''))) WHERE p.property_number = '$(($PropertyNumber -replace "'", "''"))';"
    Invoke-PhoneDuckDb $DatabasePath $sql | ConvertFrom-Csv
}

Export-ModuleMember -Function Initialize-PhoneDatabase, Import-DfrpXml, Import-CnaCoCodes, Find-FederalOffice, Find-Exchange, Get-PropertyTelephone
