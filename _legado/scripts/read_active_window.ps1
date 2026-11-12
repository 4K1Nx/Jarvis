# Read-only UI Automation. No screenshot, input injection or cloud transfer.
$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
Add-Type -TypeDefinition 'using System; using System.Runtime.InteropServices; public static class VivWindow { [DllImport("user32.dll")] public static extern IntPtr GetForegroundWindow(); }'
$root = [System.Windows.Automation.AutomationElement]::FromHandle([VivWindow]::GetForegroundWindow())
if ($null -eq $root -or $root.Current.Name -match '(?i)\.env\b') { throw 'Window unavailable or protected' }
$items = [System.Collections.Generic.List[string]]::new()
$queue = [System.Collections.Generic.Queue[System.Windows.Automation.AutomationElement]]::new()
$queue.Enqueue($root)
$walker = [System.Windows.Automation.TreeWalker]::ControlViewWalker
$count = 0
while ($queue.Count -gt 0 -and $count -lt 200 -and $items.Count -lt 60) {
    $element = $queue.Dequeue()
    $count++
    try {
        if ($element.Current.IsPassword -or $element.Current.IsOffscreen) { continue }
        $name = $element.Current.Name
        if ($name -and $name -notmatch '(?i)\.env\b' -and -not $items.Contains($name)) {
            $items.Add($name.Substring(0, [Math]::Min(300, $name.Length)))
        }
        $child = $walker.GetFirstChild($element)
        while ($null -ne $child -and $queue.Count -lt 200) {
            $queue.Enqueue($child)
            $child = $walker.GetNextSibling($child)
        }
    } catch { continue }
}
@{texts=@($items)} | ConvertTo-Json -Compress
