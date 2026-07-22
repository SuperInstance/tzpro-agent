$tasks = Get-ScheduledTask | Where-Object { $_.TaskName -match 'Capture|Hermes|Hermit|NMEA|Voice|Agent' }
foreach ($t in $tasks) {
    $act = ($t | Select-Object -ExpandProperty Actions)
    $info = Get-ScheduledTaskInfo -TaskName $t.TaskName -ErrorAction SilentlyContinue
    "{0} | state={1} | LastResult={2}" -f $t.TaskName, $t.State, $info.LastTaskResult
    "  CMD: {0} {1}" -f $act.Execute, $act.Arguments
    "  CWD: {0}" -f $act.WorkingDirectory
    ""
}