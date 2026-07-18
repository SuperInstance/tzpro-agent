"""Debug process detection on Windows."""
import subprocess, sys

# PowerShell approach
cmd = ('Get-CimInstance Win32_Process | '
       'Where-Object {$_.Name -match "python"} | '
       'Select-Object ProcessId,CommandLine | '
       'ConvertTo-Csv -NoTypeInformation')
result = subprocess.run(
    ['powershell', '-Command', cmd],
    capture_output=True, text=True, timeout=10
)
print("=== PowerShell Get-CimInstance ===")
print(result.stdout[:2000])
print("=== stderr ===")
print(result.stderr[:500])
