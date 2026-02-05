# Deployment Monitoring & Logging Guide - Vetting App V2

## Overview
This guide provides comprehensive monitoring and logging strategy for the V2 deployment to production.

---

## Pre-Deployment Checklist

### 1. Backup Strategy

```powershell
# CRITICAL: Backup before deployment
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupDir = "C:\Backups\VettingApp_V2_Deployment"

# Create backup directory
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null

# Backup database
Copy-Item "C:\Users\pmend\project\Vetting app\hub.db" `
    "$backupDir\hub.db.$timestamp.backup" -Force
Write-Host "✓ Database backed up: $backupDir\hub.db.$timestamp.backup"

# Backup current application code
Copy-Item "C:\Users\pmend\project\Vetting app\app" `
    "$backupDir\app.$timestamp.backup" -Recurse -Force
Write-Host "✓ Application code backed up"

# Backup templates
Copy-Item "C:\Users\pmend\project\Vetting app\templates" `
    "$backupDir\templates.$timestamp.backup" -Recurse -Force
Write-Host "✓ Templates backed up"
```

### 2. Pre-Deployment Health Check

```powershell
# Verify application is running
$process = Get-Process -Name "python" -ErrorAction SilentlyContinue | 
    Where-Object { $_.CommandLine -like "*main.py*" }

if ($process) {
    Write-Host "✓ Application currently running (PID: $($process.Id))"
} else {
    Write-Host "✗ Application not running - starting deployment" -ForegroundColor Yellow
}

# Check disk space
$drive = Get-PSDrive C
$freeSpaceGB = [math]::Round($drive.Free / 1GB, 2)
if ($freeSpaceGB -gt 1) {
    Write-Host "✓ Sufficient disk space: $freeSpaceGB GB"
} else {
    Write-Host "✗ WARNING: Low disk space: $freeSpaceGB GB" -ForegroundColor Red
}

# Verify database is accessible
$dbPath = "C:\Users\pmend\project\Vetting app\hub.db"
if (Test-Path $dbPath) {
    Write-Host "✓ Database accessible"
} else {
    Write-Host "✗ Database not found!" -ForegroundColor Red
}
```

---

## Application Logging Setup

### 1. Enable Enhanced Logging in main.py

Add this to the top of your `main.py` after imports:

```python
import logging
from logging.handlers import RotatingFileHandler
import os

# Create logs directory
LOG_DIR = Path(os.environ.get("LOG_DIR", str(BASE_DIR / "logs")))
LOG_DIR.mkdir(exist_ok=True, parents=True)

# Configure logging
log_file = LOG_DIR / "vetting_app.log"
handler = RotatingFileHandler(
    str(log_file),
    maxBytes=10 * 1024 * 1024,  # 10MB
    backupCount=10  # Keep 10 backup files
)

formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
handler.setFormatter(formatter)

logger = logging.getLogger()
logger.setLevel(logging.INFO)
logger.addHandler(handler)

# Log deployment
logger.info("="*80)
logger.info("APPLICATION STARTED - Vetting App V2")
logger.info(f"Database: {DB_PATH}")
logger.info(f"Upload Dir: {UPLOAD_DIR}")
logger.info("="*80)
```

### 2. Add Deployment Event Logging

Add to startup functions:

```python
# In ensure_seed_data() or startup
def log_deployment_status():
    """Log deployment status and migrations"""
    conn = get_db()
    
    try:
        # Check database tables
        cursor = conn.cursor()
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = cursor.fetchall()
        logger.info(f"Database tables: {[t[0] for t in tables]}")
        
        # Check institutions count
        inst_count = conn.execute("SELECT COUNT(*) FROM institutions").fetchone()[0]
        logger.info(f"Institutions: {inst_count}")
        
        # Check users count
        users_count = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        logger.info(f"Users: {users_count}")
        
        # Check cases count
        cases_count = conn.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        logger.info(f"Cases: {cases_count}")
        
        logger.info("✓ Database health check passed")
    except Exception as e:
        logger.error(f"✗ Database health check failed: {e}")
    finally:
        conn.close()

# Call at startup
log_deployment_status()
```

---

## Monitoring Strategy

### 1. Real-Time Log Monitoring

```powershell
# Monitor application logs in real-time
function Monitor-AppLogs {
    param(
        [int]$RefreshSeconds = 2
    )
    
    $logPath = "C:\Users\pmend\project\Vetting app\logs\vetting_app.log"
    
    if (-not (Test-Path $logPath)) {
        Write-Host "Log file not found yet. Waiting..." -ForegroundColor Yellow
        Start-Sleep -Seconds 5
    }
    
    Write-Host "Monitoring application logs (Press Ctrl+C to stop)..." -ForegroundColor Cyan
    Write-Host "=" * 80
    
    $lastRead = 0
    while ($true) {
        try {
            $content = Get-Content $logPath -ErrorAction SilentlyContinue
            if ($content) {
                $lines = @($content) | Measure-Object -Line
                if ($lines.Lines -gt $lastRead) {
                    $newLines = @($content)[$lastRead..($lines.Lines - 1)]
                    $newLines | ForEach-Object {
                        if ($_ -match "ERROR|CRITICAL|FAIL") {
                            Write-Host $_ -ForegroundColor Red
                        }
                        elseif ($_ -match "WARNING|WARN") {
                            Write-Host $_ -ForegroundColor Yellow
                        }
                        else {
                            Write-Host $_
                        }
                    }
                    $lastRead = $lines.Lines
                }
            }
        }
        catch {
            # Ignore errors during monitoring
        }
        
        Start-Sleep -Seconds $RefreshSeconds
    }
}

# Usage
Monitor-AppLogs
```

### 2. Error Alert Script

```powershell
# Check for errors in last 5 minutes
function Get-RecentErrors {
    $logPath = "C:\Users\pmend\project\Vetting app\logs\vetting_app.log"
    $minutes = 5
    
    if (Test-Path $logPath) {
        $cutoffTime = (Get-Date).AddMinutes(-$minutes)
        
        $errors = Select-String -Path $logPath -Pattern "ERROR|CRITICAL" |
            Where-Object {
                [datetime]::ParseExact(
                    $_.Line.Substring(0, 19),
                    'yyyy-MM-dd HH:mm:ss',
                    $null
                ) -gt $cutoffTime
            }
        
        if ($errors) {
            Write-Host "⚠️ ERRORS FOUND IN LAST $minutes MINUTES:" -ForegroundColor Red
            $errors | ForEach-Object { Write-Host $_.Line -ForegroundColor Red }
            return $true
        }
        else {
            Write-Host "✓ No errors in last $minutes minutes" -ForegroundColor Green
            return $false
        }
    }
}

Get-RecentErrors
```

### 3. Application Health Check

```powershell
function Test-AppHealth {
    param(
        [string]$Url = "http://localhost:8000",
        [int]$TimeoutSeconds = 10
    )
    
    Write-Host "Testing application health..." -ForegroundColor Cyan
    
    try {
        $response = Invoke-WebRequest -Uri "$Url/admin" `
            -TimeoutSec $TimeoutSeconds `
            -ErrorAction Stop
        
        if ($response.StatusCode -eq 200 -or $response.StatusCode -eq 303) {
            Write-Host "✓ Application responding (HTTP $($response.StatusCode))" -ForegroundColor Green
            return $true
        }
    }
    catch {
        Write-Host "✗ Application not responding: $_" -ForegroundColor Red
        return $false
    }
}

Test-AppHealth
```

---

## Key Metrics to Monitor

### 1. Database Migration Status

```powershell
# Verify modified_at column exists
function Test-ModifiedAtColumn {
    param([string]$DbPath = "C:\Users\pmend\project\Vetting app\hub.db")
    
    $pythonScript = @"
import sqlite3
conn = sqlite3.connect('$DbPath')
cursor = conn.cursor()
cursor.execute("PRAGMA table_info(institutions)")
columns = [row[1] for row in cursor.fetchall()]
conn.close()

if 'modified_at' in columns:
    print("OK: modified_at column exists")
else:
    print("ERROR: modified_at column missing")
"@
    
    $pythonScript | python
}

Test-ModifiedAtColumn
```

### 2. Performance Metrics

```powershell
# Monitor key performance indicators
function Get-AppMetrics {
    param([string]$LogPath = "C:\Users\pmend\project\Vetting app\logs\vetting_app.log")
    
    if (Test-Path $LogPath) {
        $errorCount = (Select-String -Path $LogPath -Pattern "ERROR" -ErrorAction SilentlyContinue | Measure-Object).Count
        $warningCount = (Select-String -Path $LogPath -Pattern "WARNING" -ErrorAction SilentlyContinue | Measure-Object).Count
        $lineCount = (Get-Content $LogPath | Measure-Object -Line).Lines
        
        Write-Host "Application Metrics:" -ForegroundColor Cyan
        Write-Host "  Total log lines: $lineCount"
        Write-Host "  Errors: $errorCount" -ForegroundColor $(if ($errorCount -gt 0) { "Red" } else { "Green" })
        Write-Host "  Warnings: $warningCount" -ForegroundColor $(if ($warningCount -gt 0) { "Yellow" } else { "Green" })
        
        if ($errorCount -eq 0) {
            Write-Host "✓ Status: Healthy" -ForegroundColor Green
        }
        elseif ($errorCount -lt 5) {
            Write-Host "⚠️ Status: Minor issues" -ForegroundColor Yellow
        }
        else {
            Write-Host "✗ Status: Multiple errors detected" -ForegroundColor Red
        }
    }
}

Get-AppMetrics
```

---

## Post-Deployment Validation

### 1. Immediate Post-Deployment (0-5 minutes)

```powershell
# Run immediately after deployment
Write-Host "POST-DEPLOYMENT VALIDATION" -ForegroundColor Cyan
Write-Host "=" * 80

# 1. Application startup
Write-Host "`n1. Testing application startup..."
Start-Sleep -Seconds 3
if (Test-AppHealth) {
    Write-Host "   ✓ PASS"
} else {
    Write-Host "   ✗ FAIL - Check logs immediately"
}

# 2. Database migration
Write-Host "`n2. Checking database migration..."
Test-ModifiedAtColumn

# 3. Log check
Write-Host "`n3. Checking for startup errors..."
Get-RecentErrors

# 4. Basic connectivity
Write-Host "`n4. Testing basic endpoints..."
try {
    $login = Invoke-WebRequest "http://localhost:8000/login" -TimeoutSec 5 -ErrorAction Stop
    Write-Host "   ✓ Login page accessible"
} catch {
    Write-Host "   ✗ Login page error: $_" -ForegroundColor Red
}
```

### 2. Extended Post-Deployment (5-30 minutes)

```powershell
# Run 5-30 minutes after deployment
Write-Host "EXTENDED VALIDATION" -ForegroundColor Cyan
Write-Host "=" * 80

# 1. Performance check
Write-Host "`n1. Performance check..."
$stopwatch = [System.Diagnostics.Stopwatch]::StartNew()
try {
    Invoke-WebRequest "http://localhost:8000/admin" -TimeoutSec 10 -ErrorAction Stop | Out-Null
    $stopwatch.Stop()
    $elapsed = $stopwatch.ElapsedMilliseconds
    
    if ($elapsed -lt 3000) {
        Write-Host "   ✓ Response time: ${elapsed}ms (Good)"
    }
    elseif ($elapsed -lt 5000) {
        Write-Host "   ⚠️ Response time: ${elapsed}ms (Slow)" -ForegroundColor Yellow
    }
    else {
        Write-Host "   ✗ Response time: ${elapsed}ms (Too slow)" -ForegroundColor Red
    }
} catch {
    Write-Host "   ✗ Failed to test performance: $_" -ForegroundColor Red
}

# 2. Error rate check
Write-Host "`n2. Error rate check..."
Get-AppMetrics

# 3. Database integrity
Write-Host "`n3. Database integrity check..."
$pythonScript = @"
import sqlite3
conn = sqlite3.connect('C:\\Users\\pmend\\project\\Vetting app\\hub.db')
cursor = conn.cursor()

# Check data integrity
cursor.execute("SELECT COUNT(*) FROM cases")
cases = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM institutions")
institutions = cursor.fetchone()[0]

cursor.execute("SELECT COUNT(*) FROM users")
users = cursor.fetchone()[0]

print(f"Cases: {cases}")
print(f"Institutions: {institutions}")
print(f"Users: {users}")

conn.close()
"@

$pythonScript | python
```

---

## Incident Response Procedure

### If Critical Error Detected

```powershell
function Invoke-Rollback {
    param(
        [string]$BackupTimestamp # Format: yyyyMMdd_HHmmss
    )
    
    Write-Host "INITIATING ROLLBACK PROCEDURE" -ForegroundColor Red
    Write-Host "=" * 80
    
    $backupDir = "C:\Backups\VettingApp_V2_Deployment"
    
    # Stop application
    Write-Host "`n1. Stopping application..."
    Get-Process -Name "python" -ErrorAction SilentlyContinue | 
        Where-Object { $_.CommandLine -like "*main.py*" } | 
        Stop-Process -Force
    Start-Sleep -Seconds 2
    Write-Host "   ✓ Application stopped"
    
    # Restore database
    Write-Host "`n2. Restoring database..."
    $restoreDbPath = "$backupDir\hub.db.$BackupTimestamp.backup"
    if (Test-Path $restoreDbPath) {
        Copy-Item $restoreDbPath "C:\Users\pmend\project\Vetting app\hub.db" -Force
        Write-Host "   ✓ Database restored"
    } else {
        Write-Host "   ✗ Backup not found: $restoreDbPath" -ForegroundColor Red
        return
    }
    
    # Restore application code
    Write-Host "`n3. Restoring application code..."
    $restoreAppPath = "$backupDir\app.$BackupTimestamp.backup"
    if (Test-Path $restoreAppPath) {
        Remove-Item "C:\Users\pmend\project\Vetting app\app" -Recurse -Force
        Copy-Item $restoreAppPath "C:\Users\pmend\project\Vetting app\app" -Recurse -Force
        Write-Host "   ✓ Application code restored"
    }
    
    Write-Host "`n✓ ROLLBACK COMPLETE - Application ready to restart" -ForegroundColor Green
}

# Usage: Invoke-Rollback -BackupTimestamp "20260131_143022"
```

---

## Monitoring Dashboard Summary

Create a simple status dashboard:

```powershell
function Show-DeploymentStatus {
    Clear-Host
    Write-Host "╔════════════════════════════════════════════════════════════════════════════════╗" -ForegroundColor Cyan
    Write-Host "║           VETTING APP V2 - DEPLOYMENT MONITORING DASHBOARD                     ║" -ForegroundColor Cyan
    Write-Host "║                        $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')                           ║" -ForegroundColor Cyan
    Write-Host "╚════════════════════════════════════════════════════════════════════════════════╝" -ForegroundColor Cyan
    
    Write-Host ""
    Write-Host "APPLICATION STATUS:" -ForegroundColor Yellow
    if (Test-AppHealth -ErrorAction SilentlyContinue) {
        Write-Host "  Status: ✓ RUNNING" -ForegroundColor Green
    } else {
        Write-Host "  Status: ✗ NOT RESPONDING" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "DATABASE STATUS:" -ForegroundColor Yellow
    $dbPath = "C:\Users\pmend\project\Vetting app\hub.db"
    if (Test-Path $dbPath) {
        $dbSize = [math]::Round((Get-Item $dbPath).Length / 1MB, 2)
        Write-Host "  Status: ✓ ACCESSIBLE" -ForegroundColor Green
        Write-Host "  Size: $dbSize MB"
    } else {
        Write-Host "  Status: ✗ NOT FOUND" -ForegroundColor Red
    }
    
    Write-Host ""
    Write-Host "ERROR LOG STATUS:" -ForegroundColor Yellow
    $hasErrors = Get-RecentErrors -ErrorAction SilentlyContinue
    
    Write-Host ""
    Write-Host "NEXT STEPS:" -ForegroundColor Yellow
    Write-Host "  • Monitor-AppLogs          - Real-time log monitoring"
    Write-Host "  • Get-AppMetrics           - View current metrics"
    Write-Host "  • Get-RecentErrors         - Check for recent errors"
    Write-Host "  • Invoke-Rollback          - Rollback if needed"
}

Show-DeploymentStatus
```

---

## Monitoring Schedule

| Time Window | Action | Frequency |
|-------------|--------|-----------|
| 0-5 min post-deployment | Immediate validation | Continuous |
| 5-30 min | Extended validation | Every 5 min |
| 30 min - 2 hours | Check error rates | Every 15 min |
| 2-24 hours | Standard monitoring | Every hour |
| 24+ hours | Production baseline | Daily |

---

## Contact & Escalation

**On-Call Contacts:**
- Tech Lead: [Name] - [Phone/Email]
- DevOps: [Name] - [Phone/Email]
- Database Admin: [Name] - [Phone/Email]

**Escalation Path:**
1. Error detected → Check logs
2. Unable to resolve → Contact Tech Lead
3. Service down → Contact DevOps Lead
4. Data integrity issue → Contact Database Admin
