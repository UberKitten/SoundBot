#!/usr/bin/env pwsh
<#
.SYNOPSIS
    Migrate play counts from db.json to state.json
.DESCRIPTION
    This script migrates sound play counts from the legacy db.json file to the current state.json file.
    It will:
    - Overwrite discord play counts in state.json with counts from db.json
    - Add any sounds that exist in db.json but not in state.json
    - Preserve all other data in state.json (entrances, exits, timestamps, etc.)
    - Print warnings for any issues encountered
.EXAMPLE
    .\migrate-db-to-state.ps1
#>

$ErrorActionPreference = "Stop"

$dbPath = "config/db.json"
$statePath = "config/state.json"

Write-Host "=== SoundBot Migration: db.json -> state.json ===" -ForegroundColor Cyan
Write-Host ""

# Check if files exist
if (-not (Test-Path $dbPath)) {
    Write-Host "ERROR: db.json not found at $dbPath" -ForegroundColor Red
    exit 1
}

if (-not (Test-Path $statePath)) {
    Write-Host "WARNING: state.json not found at $statePath - creating new file" -ForegroundColor Yellow
    $state = @{
        entrances = @{}
        exits = @{}
        sounds = @{}
    }
} else {
    # Load existing state
    try {
        $state = Get-Content $statePath -Raw | ConvertFrom-Json -AsHashtable
        $soundCount = $state.sounds.Count
        Write-Host "[OK] Loaded state.json ($soundCount sounds)" -ForegroundColor Green
    } catch {
        Write-Host "ERROR: Failed to parse state.json: $_" -ForegroundColor Red
        exit 1
    }
}

# Load db.json
try {
    $db = Get-Content $dbPath -Raw | ConvertFrom-Json
    $dbSoundCount = $db.sounds.Count
    Write-Host "[OK] Loaded db.json ($dbSoundCount sounds)" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to parse db.json: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "Migrating play counts..." -ForegroundColor Cyan

$updated = 0
$added = 0
$warnings = 0

foreach ($dbSound in $db.sounds) {
    $soundName = $dbSound.name.ToLower()
    $count = if ($dbSound.count) { [int]$dbSound.count } else { 0 }
    
    if ($state.sounds.ContainsKey($soundName)) {
        # Sound exists in state - update count
        $oldCount = $state.sounds[$soundName].discord.plays
        $state.sounds[$soundName].discord.plays = $count
        
        if ($count -ne $oldCount) {
            Write-Host "  Updated: $soundName ($oldCount -> $count plays)" -ForegroundColor Yellow
            $updated++
        }
    } else {
        # Sound doesn't exist in state - add it as legacy format
        Write-Host "  WARNING: Sound '$soundName' exists in db.json but not in state.json" -ForegroundColor Yellow
        Write-Host "           This sound may not have audio files. Count: $count plays" -ForegroundColor Gray
        
        # Add as legacy sound entry
        $state.sounds[$soundName] = @{
            filename = "$soundName.mp3"
            original_filename = "$soundName-original.mp3"
            source = $null
            source_title = $null
            created = (Get-Date).ToUniversalTime().ToString("o")
            modified = (Get-Date).ToUniversalTime().ToString("o")
            discord = @{
                plays = $count
                last_played = $null
            }
            twitch = @{
                plays = 0
                last_played = $null
            }
            crop = $null
        }
        
        $added++
        $warnings++
    }
}

Write-Host ""
Write-Host "Migration complete!" -ForegroundColor Green
Write-Host "  - Updated: $updated sounds" -ForegroundColor Cyan
Write-Host "  - Added: $added sounds (as legacy entries)" -ForegroundColor Cyan

if ($warnings -gt 0) {
    Write-Host ""
    Write-Host "WARNINGS: $warnings sounds were added but may be missing audio files" -ForegroundColor Yellow
    Write-Host "These sounds may need to be re-added with /add command" -ForegroundColor Yellow
}

# Migrate entrances/exits if they don't exist in state
if (-not $state.ContainsKey("entrances") -or $state.entrances.Count -eq 0) {
    if ($db.entrances -and $db.entrances.PSObject.Properties.Count -gt 0) {
        Write-Host ""
        Write-Host "Migrating entrance sounds..." -ForegroundColor Cyan
        $state.entrances = @{}
        foreach ($prop in $db.entrances.PSObject.Properties) {
            $state.entrances[$prop.Name] = $prop.Value
            Write-Host "  - User $($prop.Name): $($prop.Value)" -ForegroundColor Gray
        }
    }
}

if (-not $state.ContainsKey("exits") -or $state.exits.Count -eq 0) {
    if ($db.exits -and $db.exits.PSObject.Properties.Count -gt 0) {
        Write-Host ""
        Write-Host "Migrating exit sounds..." -ForegroundColor Cyan
        $state.exits = @{}
        foreach ($prop in $db.exits.PSObject.Properties) {
            $state.exits[$prop.Name] = $prop.Value
            Write-Host "  - User $($prop.Name): $($prop.Value)" -ForegroundColor Gray
        }
    }
}

# Backup old state
$backupPath = "$statePath.backup"
if (Test-Path $statePath) {
    Copy-Item $statePath $backupPath
    Write-Host ""
    Write-Host "Backed up old state.json to $backupPath" -ForegroundColor Gray
}

# Save updated state
try {
    $state | ConvertTo-Json -Depth 10 | Set-Content $statePath -Encoding UTF8
    Write-Host "[OK] Saved updated state.json" -ForegroundColor Green
} catch {
    Write-Host "ERROR: Failed to save state.json: $_" -ForegroundColor Red
    exit 1
}

Write-Host ""
Write-Host "=== Migration Complete ===" -ForegroundColor Green
Write-Host "You can now safely archive or delete db.json if desired." -ForegroundColor Gray
