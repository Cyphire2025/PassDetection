[CmdletBinding()]
param(
    [string]$FixturePath = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot "..")).Path
if ([string]::IsNullOrWhiteSpace($FixturePath)) {
    $FixturePath = Join-Path $projectRoot "fixtures\v2-regression-form.html"
}
elseif (-not [IO.Path]::IsPathRooted($FixturePath)) {
    $FixturePath = Join-Path $projectRoot $FixturePath
}

$resolvedFixture = (Resolve-Path -LiteralPath $FixturePath).Path
$html = [IO.File]::ReadAllText($resolvedFixture, [Text.Encoding]::UTF8)

function Assert-Fixture {
    param(
        [Parameter(Mandatory = $true)]
        [bool]$Condition,

        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    if (-not $Condition) {
        throw "V2 fixture validation failed: $Message"
    }
}

function Get-CaseOpeningTag {
    param(
        [Parameter(Mandatory = $true)]
        [string]$CaseId
    )

    $pattern = '(?s)<div class="case"\s+[^>]*data-case-id="' +
        [regex]::Escape($CaseId) +
        '"[^>]*>'
    $match = [regex]::Match($html, $pattern)
    Assert-Fixture $match.Success "$CaseId opening tag is missing"
    return $match.Value
}

$expectedCaseIds = @(
    "LABEL-01", "LABEL-02", "LABEL-03", "LABEL-04", "LABEL-05",
    "LABEL-06", "LABEL-07", "LABEL-08", "LABEL-09", "LABEL-10",
    "NORMALIZE-01", "NORMALIZE-02", "NORMALIZE-03", "NORMALIZE-04",
    "PHONE-01", "PHONE-02", "PHONE-03", "PHONE-04", "PHONE-05", "PHONE-06",
    "FORMAT-01", "FORMAT-02", "FORMAT-03", "FORMAT-04", "FORMAT-05",
    "FORMAT-06", "FORMAT-07",
    "LEARN-01", "LEARN-02", "LEARN-03",
    "AMBIGUOUS-01", "AMBIGUOUS-02", "AMBIGUOUS-03", "AMBIGUOUS-04"
)

$caseMatches = [regex]::Matches($html, 'data-case-id="([^"]+)"')
$actualCaseIds = @($caseMatches | ForEach-Object { $_.Groups[1].Value })
$duplicateCaseIds = @(
    $actualCaseIds |
        Group-Object |
        Where-Object { $_.Count -ne 1 } |
        ForEach-Object { $_.Name }
)
$missingCaseIds = @($expectedCaseIds | Where-Object { $_ -notin $actualCaseIds })
$unexpectedCaseIds = @($actualCaseIds | Where-Object { $_ -notin $expectedCaseIds })

Assert-Fixture ($actualCaseIds.Count -eq $expectedCaseIds.Count) `
    "expected $($expectedCaseIds.Count) cases, found $($actualCaseIds.Count)"
Assert-Fixture ($duplicateCaseIds.Count -eq 0) `
    "duplicate case IDs: $($duplicateCaseIds -join ', ')"
Assert-Fixture ($missingCaseIds.Count -eq 0) `
    "missing case IDs: $($missingCaseIds -join ', ')"
Assert-Fixture ($unexpectedCaseIds.Count -eq 0) `
    "unexpected case IDs: $($unexpectedCaseIds -join ', ')"

foreach ($caseId in $expectedCaseIds) {
    $openingPattern = '(?s)<div class="case"\s+[^>]*data-case-id="' +
        [regex]::Escape($caseId) +
        '"[^>]*data-expected-outcome="[^"]+"[^>]*>'
    Assert-Fixture ([regex]::IsMatch($html, $openingPattern)) `
        "$caseId has no machine-readable expected outcome"
}

$idMatches = [regex]::Matches($html, '\sid="([^"]+)"')
$elementIds = @($idMatches | ForEach-Object { $_.Groups[1].Value })
$duplicateElementIds = @(
    $elementIds |
        Group-Object |
        Where-Object { $_.Count -ne 1 } |
        ForEach-Object { $_.Name }
)
Assert-Fixture ($duplicateElementIds.Count -eq 0) `
    "duplicate HTML element IDs: $($duplicateElementIds -join ', ')"

$labelTargets = @(
    [regex]::Matches($html, '<label\s+for="([^"]+)"') |
        ForEach-Object { $_.Groups[1].Value }
)
$missingLabelTargets = @($labelTargets | Where-Object { $_ -notin $elementIds })
Assert-Fixture ($missingLabelTargets.Count -eq 0) `
    "labels reference missing controls: $($missingLabelTargets -join ', ')"

$externalResourcePattern =
    '(?i)(?:src|href)\s*=\s*["'']https?://|url\(\s*["'']?https?://'
Assert-Fixture (-not [regex]::IsMatch($html, $externalResourcePattern)) `
    "fixture contains an external resource"
Assert-Fixture ($html.Contains("connect-src 'none'")) `
    "Content Security Policy must block connections"
Assert-Fixture ($html.Contains("form-action 'none'")) `
    "Content Security Policy must block form navigation"
Assert-Fixture ($html.Contains("Values are never logged.")) `
    "privacy-safe event-monitor notice is missing"
Assert-Fixture (-not $html.Contains('${target.value}')) `
    "event log interpolates a raw control value"
Assert-Fixture (-not $html.Contains('log(target.value')) `
    "event log writes a raw control value"

$genericTelephoneCases = @(
    "PHONE-02",
    "PHONE-03",
    "FORMAT-05",
    "LEARN-01",
    "LEARN-02"
)
$genericPhoneCandidates =
    'data-expected-candidates="contact.landline,contact.mobile"'
foreach ($caseId in $genericTelephoneCases) {
    $openingTag = Get-CaseOpeningTag $caseId
    Assert-Fixture ($openingTag.Contains($genericPhoneCandidates)) `
        "$caseId must recommend exactly available mobile and landline fields"
    Assert-Fixture ($openingTag.Contains('data-expected-outcome="picker')) `
        "$caseId must require first-use picker confirmation"
    Assert-Fixture (-not $openingTag.Contains("contact.alternate_mobile")) `
        "$caseId incorrectly recommends alternate mobile"
    Assert-Fixture (-not $openingTag.Contains("emergency.phone")) `
        "$caseId incorrectly recommends emergency phone"
    Assert-Fixture (-not $openingTag.Contains("contact.country_calling_code")) `
        "$caseId incorrectly recommends calling code"
    Assert-Fixture ($openingTag.Contains('data-remember-default="checked"')) `
        "$caseId must document the checked runtime-only remember control"
}
Assert-Fixture (-not $html.Contains("unique compatible auto")) `
    "generic telephone must not silently auto-paste on first use"
Assert-Fixture (-not $html.Contains("unique full number auto")) `
    "generic telephone must require first-use confirmation"
Assert-Fixture ($html.Contains('data-case-id="FORMAT-04"')) `
    "date-format regression case is missing"
Assert-Fixture ($html.Contains('data-source-sample="29.04.2002"')) `
    "date-format source sample is missing"
Assert-Fixture ($html.Contains('data-expected-value="29/04/2002"')) `
    "date-format expected value is missing"
Assert-Fixture ($html.Contains('data-source-sample="0012 345-678"')) `
    "digits-only source sample is missing"
Assert-Fixture ($html.Contains('data-expected-value="0012345678"')) `
    "digits-only expected value does not preserve leading zeroes"
Assert-Fixture ($html.Contains('data-expected-outcome="manual-unsupported"')) `
    "dropdown automation boundary is missing"
Assert-Fixture ($html.Contains("Restarting the app forgets it")) `
    "runtime-only learning boundary is missing"
Assert-Fixture ($html.Contains("V2 has no domain-persistent mapping")) `
    "fixture overstates persistent website learning"
Assert-Fixture ($html.Contains("Chrome, Edge, and Brave")) `
    "supported-browser fixture guidance is incomplete"
Assert-Fixture ($html.Contains("rememberDefault: node.dataset.rememberDefault")) `
    "machine-readable remember-default contract is missing"

$scriptMatch = [regex]::Match($html, '(?s)<script>(.*?)</script>')
Assert-Fixture ($scriptMatch.Success) "inline fixture script is missing"

$node = Get-Command node -ErrorAction SilentlyContinue
if ($null -ne $node) {
    $nodeOutput = $scriptMatch.Groups[1].Value | & $node.Source --check - 2>&1
    if ($LASTEXITCODE -ne 0) {
        throw "V2 fixture JavaScript syntax check failed: $nodeOutput"
    }
}
else {
    Write-Warning "Node.js is unavailable; JavaScript syntax check was skipped."
}

Write-Host (
    (
        "[fixture-v2] PASS: {0} unique cases, offline CSP, label targets, " +
        "phone scope, format hints, runtime-learning boundaries, and log guards."
    ) -f $actualCaseIds.Count
)
