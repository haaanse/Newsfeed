# Sichert die Newsfeed-Datenbank nach .\backups\newsfeed-JJJJ-MM-TT_HHMM.db
# Aufruf im Projektordner:  powershell -ExecutionPolicy Bypass -File scripts\backup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$stamp = Get-Date -Format "yyyy-MM-dd_HHmm"
New-Item -ItemType Directory -Force -Path backups | Out-Null
docker compose exec -T newsfeed python -m app.backup /data/backup-tmp.db
docker compose cp newsfeed:/data/backup-tmp.db "backups/newsfeed-$stamp.db"
docker compose exec -T newsfeed rm /data/backup-tmp.db
# Nur die letzten 14 Sicherungen behalten
Get-ChildItem backups\newsfeed-*.db | Sort-Object Name -Descending | Select-Object -Skip 14 | Remove-Item
Write-Host "Backup gespeichert: backups\newsfeed-$stamp.db"
