param(
    [switch]$InstallDeps,
    [switch]$SkipPrompts
)

$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $Root

function Ask-Value {
    param(
        [string]$Prompt,
        [string]$Default = ""
    )

    if ($SkipPrompts) {
        return $Default
    }

    if ([string]::IsNullOrWhiteSpace($Default)) {
        $answer = Read-Host $Prompt
    } else {
        $answer = Read-Host "$Prompt [$Default]"
    }

    if ([string]::IsNullOrWhiteSpace($answer)) {
        return $Default
    }
    return $answer.Trim()
}

function Ask-YesNo {
    param(
        [string]$Prompt,
        [bool]$Default = $true
    )

    if ($SkipPrompts) {
        return $Default
    }

    $defaultText = if ($Default) { "Y/n" } else { "y/N" }
    $answer = Read-Host "$Prompt [$defaultText]"
    if ([string]::IsNullOrWhiteSpace($answer)) {
        return $Default
    }
    return $answer.Trim().ToLowerInvariant().StartsWith("y")
}

function Set-DotEnvValue {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )

    if (-not (Test-Path $Path)) {
        New-Item -ItemType File -Path $Path -Force | Out-Null
    }

    $lines = [System.Collections.Generic.List[string]]::new()
    $lines.AddRange([string[]](Get-Content -Path $Path -ErrorAction SilentlyContinue))
    $escapedKey = [regex]::Escape($Key)
    $found = $false

    for ($i = 0; $i -lt $lines.Count; $i++) {
        if ($lines[$i] -match "^$escapedKey=") {
            $lines[$i] = "$Key=$Value"
            $found = $true
            break
        }
    }

    if (-not $found) {
        $lines.Add("$Key=$Value")
    }

    Set-Content -Path $Path -Value $lines -Encoding UTF8
}


function Set-DotEnvValueIfProvided {
    param(
        [string]$Path,
        [string]$Key,
        [string]$Value
    )

    if (-not [string]::IsNullOrWhiteSpace($Value)) {
        Set-DotEnvValue -Path $Path -Key $Key -Value $Value
    }
}
function Write-SystemPrompt {
    param(
        [string]$CampaignName,
        [string]$PersonaName,
        [string]$SettingSummary,
        [string]$Tone,
        [string]$RulesPolicy,
        [string]$UnknownPolicy
    )

    $prompt = @"
You are $PersonaName, the in-world assistant for the $CampaignName campaign.

Campaign premise:
$SettingSummary

Voice and behavior:
- Tone: $Tone
- Treat the campaign notes and database records as the source of truth.
- Do not invent campaign lore, locations, factions, NPCs, dates, or history when the notes do not support it.
- When the answer is not supported by available notes, say: "$UnknownPolicy"
- Keep answers useful for a tabletop RPG table: concise when the user needs speed, richer when they ask for color.
- Separate established canon from suggestions, guesses, or optional ideas.

Rules policy:
$RulesPolicy

RAG policy:
- Prefer retrieved campaign context over general memory.
- If retrieved context conflicts, mention the conflict instead of silently choosing one.
- If the user asks out of character, answer plainly and helpfully.
"@

    Set-Content -Path (Join-Path $Root "system_prompt.txt") -Value $prompt.Trim() -Encoding UTF8
}

function Write-RagProfile {
    param(
        [string]$CampaignName,
        [string]$PersonaName,
        [string]$SettingSummary,
        [string]$Tone,
        [string]$RulesPolicy,
        [string]$HouseRules,
        [string]$CanonicalSources,
        [string]$AvoidList,
        [string]$UnknownPolicy
    )

    $campaignDocs = Join-Path $Root "campaign_docs"
    New-Item -ItemType Directory -Path $campaignDocs -Force | Out-Null

    $profile = @"
RAG Profile for $CampaignName

This file is local-only campaign guidance. It is ignored by git so each table can keep its own lore private.

Campaign name: $CampaignName
Assistant/persona name: $PersonaName
Setting summary: $SettingSummary
Tone: $Tone

Rules policy:
$RulesPolicy

House rules and table preferences:
$HouseRules

Canonical sources to trust first:
$CanonicalSources

Topics, tones, or assumptions to avoid:
$AvoidList

When lore is missing, say:
$UnknownPolicy

Notes for adding more RAG material:
- Put local lore text files in campaign_docs as .txt files.
- Keep one topic per file when possible, such as factions.txt, locations.txt, house_rules.txt, or session_zero.txt.
- The bot can also read training documents from MySQL when those are imported.
- Do not commit private campaign notes unless you intentionally want them public.
"@

    Set-Content -Path (Join-Path $campaignDocs "rag_profile.txt") -Value $profile.Trim() -Encoding UTF8
}

Write-Host "TowerBot new campaign setup"
Write-Host "Repo root: $Root"
Write-Host "This script prepares local files only. It does not start, stop, or modify any running bot service."
Write-Host ""

$campaignName = Ask-Value "Campaign/world name" "My Campaign"
$personaName = Ask-Value "Assistant/persona name" "Campaign Oracle"
$settingSummary = Ask-Value "One sentence setting premise" "A fantasy campaign world run by this table."
$tone = Ask-Value "Preferred voice/tone" "helpful, atmospheric, and table-practical"
$rulesPolicy = Ask-Value "Rules answer policy" "Answer D&D 5e rules plainly, flag uncertainty, and keep table rulings separate from rules text."
$houseRules = Ask-Value "House rules or table preferences" "No house rules recorded yet."
$canonicalSources = Ask-Value "Canonical sources to trust first" "Local campaign_docs files, imported training_docs records, then user-provided chat context."
$avoidList = Ask-Value "Topics, tones, or assumptions to avoid" "Do not assume this is the Tower of Last Chance unless local notes say so."
$unknownPolicy = Ask-Value "Phrase to use when lore is missing" "I don't know based on the lore provided."

Write-SystemPrompt -CampaignName $campaignName -PersonaName $personaName -SettingSummary $settingSummary -Tone $tone -RulesPolicy $rulesPolicy -UnknownPolicy $unknownPolicy
Write-RagProfile -CampaignName $campaignName -PersonaName $personaName -SettingSummary $settingSummary -Tone $tone -RulesPolicy $rulesPolicy -HouseRules $houseRules -CanonicalSources $canonicalSources -AvoidList $avoidList -UnknownPolicy $unknownPolicy

$envPath = Join-Path $Root ".env"
$envExamplePath = Join-Path $Root ".env.example"

if (-not (Test-Path $envPath)) {
    Copy-Item -Path $envExamplePath -Destination $envPath
    Write-Host "Created .env from .env.example"
} else {
    Write-Host ".env already exists; updating selected values only."
}

$mysqlHost = Ask-Value "MySQL host" "127.0.0.1"
$mysqlPort = Ask-Value "MySQL port" "3306"
$mysqlUser = Ask-Value "MySQL user" "towerbot"
$mysqlDb = Ask-Value "MySQL database" "towerbot"
$mysqlPassword = Ask-Value "MySQL password (leave blank to edit .env later)" ""

$ollamaUrl = Ask-Value "Ollama URL" "http://localhost:11434"
$ollamaModel = Ask-Value "Ollama main model" "qwen3-8b-slim:latest"
$ollamaFastModel = Ask-Value "Ollama fast model" $ollamaModel

$a1111Url = Ask-Value "A1111 URL" "http://127.0.0.1:7860"
$a1111Model = Ask-Value "A1111 model/checkpoint (optional)" ""
$generateMaps = if (Ask-YesNo "Generate tactical maps during module generation" $true) { "true" } else { "false" }

$discordToken = Ask-Value "Discord bot token (leave blank to edit .env later)" ""
$discordChannel = Ask-Value "Main Discord channel ID" ""
$missionChannel = Ask-Value "Mission board channel ID" ""
$mapsChannel = Ask-Value "Maps channel ID" ""
$replyingChannel = Ask-Value "Reply-all Discord channel ID" ""
$adminIds = Ask-Value "Admin Discord user IDs, comma-separated" ""

Set-DotEnvValue $envPath "MYSQL_HOST" $mysqlHost
Set-DotEnvValue $envPath "MYSQL_PORT" $mysqlPort
Set-DotEnvValue $envPath "MYSQL_USER" $mysqlUser
Set-DotEnvValueIfProvided $envPath "MYSQL_PASSWORD" $mysqlPassword
Set-DotEnvValue $envPath "MYSQL_DB" $mysqlDb
Set-DotEnvValue $envPath "OLLAMA_URL" $ollamaUrl
Set-DotEnvValue $envPath "OLLAMA_MODEL" $ollamaModel
Set-DotEnvValue $envPath "OLLAMA_FAST_MODEL" $ollamaFastModel
Set-DotEnvValue $envPath "QWEN_MODEL" $ollamaModel
Set-DotEnvValue $envPath "KIMI_MODEL" $ollamaModel
Set-DotEnvValue $envPath "A1111_URL" $a1111Url
Set-DotEnvValueIfProvided $envPath "A1111_MODEL" $a1111Model
Set-DotEnvValue $envPath "MODULE_GENERATE_MAPS" $generateMaps
Set-DotEnvValue $envPath "MIMIR_CAMPAIGN_NAME" $campaignName
Set-DotEnvValueIfProvided $envPath "DISCORD_BOT_TOKEN" $discordToken
Set-DotEnvValueIfProvided $envPath "DISCORD_CHANNEL_ID" $discordChannel
Set-DotEnvValueIfProvided $envPath "MISSION_BOARD_CHANNEL_ID" $missionChannel
Set-DotEnvValueIfProvided $envPath "MAPS_CHANNEL_ID" $mapsChannel
Set-DotEnvValueIfProvided $envPath "REPLYING_ALL_DISCORD_CHANNEL_ID" $replyingChannel
Set-DotEnvValueIfProvided $envPath "ADMIN_USER_IDS" $adminIds

New-Item -ItemType Directory -Path (Join-Path $Root "logs") -Force | Out-Null
New-Item -ItemType Directory -Path (Join-Path $Root "generated_modules") -Force | Out-Null

if ($InstallDeps -or (Ask-YesNo "Create .venv and install Python/Node dependencies now" $false)) {
    if (-not (Test-Path (Join-Path $Root ".venv"))) {
        python -m venv .venv
    }
    & (Join-Path $Root ".venv\Scripts\python.exe") -m pip install --upgrade pip
    & (Join-Path $Root ".venv\Scripts\pip.exe") install -r requirements.txt
    if (Test-Path (Join-Path $Root "package.json")) {
        npm install
    }
}

Write-Host ""
Write-Host "Setup files written:"
Write-Host "- .env"
Write-Host "- system_prompt.txt"
Write-Host "- campaign_docs\rag_profile.txt"
Write-Host ""
Write-Host "Next manual checks:"
Write-Host "1. Review .env and fill any blank secrets or channel IDs."
Write-Host "2. Create/import the MySQL database using database_schema.sql."
Write-Host "3. Start Ollama and A1111 if those features are enabled."
Write-Host "4. Run: .\.venv\Scripts\Activate.ps1"
Write-Host "5. Run: python main.py"
Write-Host ""
Write-Host "For a full walkthrough, read docs\setup_walkthrough.md."

