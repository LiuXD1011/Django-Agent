# Private launcher protocol only; not an arbitrary-command or business runtime CLI.
# https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
$ErrorActionPreference = 'Stop'
[Console]::InputEncoding = [System.Text.UTF8Encoding]::new($false)
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
try {
    if ($args.Count -ne 0) { throw 'protocol' }
    $line = [Console]::ReadLine()
    if ($null -eq $line -or $line.Length -gt 1048576) { throw 'protocol' }
    $plan = $line | ConvertFrom-Json
    if ($plan.format -ne 'marlin-electron-launch-v1' -or $plan.cwd -isnot [string] -or $plan.executable -isnot [string] -or
        $plan.cwd -ne [IO.Path]::GetFullPath($plan.cwd) -or $plan.executable -ne [IO.Path]::Combine($plan.cwd, 'node_modules\electron\dist\electron.exe') -or
        -not [IO.File]::Exists($plan.executable) -or -not [IO.Directory]::Exists($plan.cwd) -or $plan.argv -isnot [array] -or
        $plan.argv.Count -lt 1 -or $plan.argv.Count -gt 4 -or $plan.argv[0] -ne $plan.cwd) { throw 'protocol' }
    $values = [System.Collections.Generic.List[string]]::new()
    foreach ($value in $plan.argv) {
        if ($value -isnot [string] -or $value.Contains([char]0)) { throw 'protocol' }
        $values.Add($value)
    }
    if ($values.Count -gt 1 -and ($values.Count -lt 3 -or $values[1] -ne '--data-dir' -or $values[2].Length -eq 0 -or
        ($values.Count -eq 4 -and $values[3] -ne '--smoke-test'))) { throw 'protocol' }
    if ($null -eq $plan.env) { throw 'protocol' }
    $environment = [System.Collections.Generic.List[string]]::new()
    $seen = [System.Collections.Generic.HashSet[string]]::new([StringComparer]::OrdinalIgnoreCase)
    foreach ($property in $plan.env.PSObject.Properties) {
        if ($property.Name -notmatch '^(systemroot|windir|systemdrive|comspec|pathext|temp|tmp|userprofile|localappdata|appdata)$' -or
            $property.Value -isnot [string] -or $property.Value.Contains([char]0) -or -not $seen.Add($property.Name)) { throw 'protocol' }
        $environment.Add($property.Name + '=' + $property.Value)
    }
    $environment.Sort([StringComparer]::OrdinalIgnoreCase)
    Add-Type -Language CSharp -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
using System.Text;
using System.Diagnostics;
using System.Threading;
using System.Threading.Tasks;
public static class MarlinLaunchJob {
    [StructLayout(LayoutKind.Sequential)] struct BasicLimit {
        public long userTime, jobTime; public uint flags; public UIntPtr minWorking, maxWorking; public uint activeLimit;
        public UIntPtr affinity; public uint priority, scheduling;
    }
    [StructLayout(LayoutKind.Sequential)] struct IoCounters { public ulong reads, writes, other, readBytes, writeBytes, otherBytes; }
    [StructLayout(LayoutKind.Sequential)] struct ExtendedLimit { public BasicLimit basic; public IoCounters io; public UIntPtr processMemory, jobMemory, peakProcess, peakJob; }
    [StructLayout(LayoutKind.Sequential)] struct Accounting { public long user, kernel, periodUser, periodKernel; public uint faults, total, active, terminated; }
    [StructLayout(LayoutKind.Sequential, CharSet=CharSet.Unicode)] struct Startup {
        public uint cb; public string reserved, desktop, title; public uint x, y, width, height, columns, rows, fill, flags;
        public ushort show, reservedSize; public IntPtr reservedBytes, stdin, stdout, stderr;
    }
    [StructLayout(LayoutKind.Sequential)] struct ProcessInfo { public IntPtr process, thread; public uint pid, tid; }
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateJobObjectW(IntPtr security, string name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool SetInformationJobObject(IntPtr job, int info, ref ExtendedLimit value, uint length);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool QueryInformationJobObject(IntPtr job, int info, out Accounting value, uint length, IntPtr returned);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateJobObject(IntPtr job, uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool TerminateProcess(IntPtr process, uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint ResumeThread(IntPtr thread);
    [DllImport("kernel32.dll", SetLastError=true)] static extern uint WaitForSingleObject(IntPtr handle, uint milliseconds);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool GetExitCodeProcess(IntPtr process, out uint code);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool CloseHandle(IntPtr handle);
    [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
    [DllImport("kernel32.dll", SetLastError=true)] static extern IntPtr GetStdHandle(int name);
    [DllImport("kernel32.dll", SetLastError=true)] static extern bool DuplicateHandle(IntPtr sourceProcess, IntPtr source, IntPtr targetProcess, out IntPtr target, uint access, bool inherit, uint options);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern IntPtr CreateFileW(string name, uint access, uint sharing, IntPtr security, uint creation, uint attributes, IntPtr template);
    [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)] static extern bool CreateProcessW(string executable, StringBuilder command, IntPtr processSecurity, IntPtr threadSecurity, bool inherit, uint flags, IntPtr environment, string cwd, ref Startup startup, out ProcessInfo process);
    static void Checked(bool success, string action) { if (!success) throw new InvalidOperationException(action + " (" + Marshal.GetLastWin32Error() + ")"); }
    static IntPtr Checked(IntPtr handle, string action) { Checked(handle != IntPtr.Zero && handle != new IntPtr(-1), action); return handle; }
    static IntPtr Duplicate(IntPtr handle) {
        IntPtr result; Checked(DuplicateHandle(GetCurrentProcess(), Checked(handle, "standard handle"), GetCurrentProcess(), out result, 0, true, 2), "duplicate standard handle"); return result;
    }
    static string Quote(string value) {
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (char ch in value) {
            if (ch == '\\') { slashes++; continue; }
            if (ch == '"') result.Append('\\', slashes * 2 + 1); else result.Append('\\', slashes);
            result.Append(ch); slashes = 0;
        }
        return result.Append('\\', slashes * 2).Append('"').ToString();
    }
    public static int Run(string executable, string[] argv, string cwd, string[] environment) {
        IntPtr job = IntPtr.Zero, block = IntPtr.Zero, input = IntPtr.Zero, output = IntPtr.Zero, error = IntPtr.Zero, nullInput = IntPtr.Zero;
        ProcessInfo process = new ProcessInfo(); bool assigned = false, finished = false;
        var control = Task.Factory.StartNew(() => Console.In.ReadLine(), TaskCreationOptions.LongRunning);
        try {
            job = Checked(CreateJobObjectW(IntPtr.Zero, null), "create private job");
            var limits = new ExtendedLimit(); limits.basic.flags = 0x2000; // KILL_ON_JOB_CLOSE, no breakaway.
            Checked(SetInformationJobObject(job, 9, ref limits, (uint)Marshal.SizeOf(limits)), "set private job limits");
            nullInput = Checked(CreateFileW("NUL", 0x80000000, 3, IntPtr.Zero, 3, 0x80, IntPtr.Zero), "open child stdin");
            input = Duplicate(nullInput); output = Duplicate(GetStdHandle(-11)); error = Duplicate(GetStdHandle(-12));
            block = Marshal.StringToHGlobalUni(string.Join("\0", environment) + "\0\0");
            var startup = new Startup(); startup.cb = (uint)Marshal.SizeOf(startup); startup.flags = 0x100;
            startup.stdin = input; startup.stdout = output; startup.stderr = error;
            var command = new StringBuilder(Quote(executable)); foreach (string value in argv) command.Append(' ').Append(Quote(value));
            Checked(CreateProcessW(executable, command, IntPtr.Zero, IntPtr.Zero, true, 0x4 | 0x400, block, cwd, ref startup, out process), "create suspended child");
            Checked(AssignProcessToJobObject(job, process.process), "assign suspended child"); assigned = true;
            uint code = 143;
            if (!control.IsCompleted) {
                Checked(ResumeThread(process.thread) != 0xFFFFFFFF, "resume owned child");
                while (true) {
                    if (control.IsCompleted) break; // CANCEL or EOF: the owning Node stopped.
                    uint wait = WaitForSingleObject(process.process, 50);
                    Checked(wait == 0 || wait == 0x102, "wait owned child");
                    if (wait == 0) { Checked(GetExitCodeProcess(process.process, out code), "read child result"); break; }
                }
            }
            // Parent exit does not end ownership: terminate and verify the whole private job.
            Checked(TerminateJobObject(job, code), "finish private job");
            var cleanup = Stopwatch.StartNew();
            Checked(WaitForSingleObject(process.process, 5000) == 0, "wait retained child handle");
            while (true) {
                Accounting accounting;
                Checked(QueryInformationJobObject(job, 1, out accounting, (uint)Marshal.SizeOf(typeof(Accounting)), IntPtr.Zero), "query private job exit");
                if (accounting.active == 0) break;
                Checked(cleanup.ElapsedMilliseconds < 5000, "private job cleanup deadline"); Thread.Sleep(20);
            }
            finished = true; return unchecked((int)code);
        } finally {
            try {
                if (process.process != IntPtr.Zero && !finished) {
                    // Retained handles only: never discover or kill a process by a reusable PID.
                    if (assigned) Checked(TerminateJobObject(job, 125), "finish private job");
                    else Checked(TerminateProcess(process.process, 125), "terminate suspended child");
                    Checked(WaitForSingleObject(process.process, 5000) == 0, "wait retained child handle");
                    if (assigned) {
                        var cleanup = Stopwatch.StartNew();
                        while (true) {
                            Accounting accounting;
                            Checked(QueryInformationJobObject(job, 1, out accounting, (uint)Marshal.SizeOf(typeof(Accounting)), IntPtr.Zero), "query private job exit");
                            if (accounting.active == 0) break;
                            Checked(cleanup.ElapsedMilliseconds < 5000, "private job cleanup deadline"); Thread.Sleep(20);
                        }
                    }
                }
            } finally {
                if (job != IntPtr.Zero) CloseHandle(job);
                foreach (IntPtr handle in new [] { process.thread, process.process, input, output, error, nullInput }) if (handle != IntPtr.Zero) CloseHandle(handle);
                if (block != IntPtr.Zero) Marshal.FreeHGlobal(block);
            }
        }
    }
}
'@
    exit [MarlinLaunchJob]::Run($plan.executable, $values.ToArray(), $plan.cwd, $environment.ToArray())
} catch {
    $reason = 'fixed owned launch guard failed.'
    $inner = $_.Exception.InnerException
    if ($null -ne $inner -and $inner.Message -match '^(create private job|set private job limits|open child stdin|standard handle|duplicate standard handle|create suspended child|assign suspended child|resume owned child|wait owned child|read child result|finish private job|terminate suspended child|wait retained child handle|query private job exit|private job cleanup deadline) \([0-9]+\)$') { $reason = $inner.Message }
    [Console]::Error.WriteLine('WIN32_SUPERVISION_FAILED: ' + $reason)
    exit 125
}
