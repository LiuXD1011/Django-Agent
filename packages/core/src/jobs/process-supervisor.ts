// Fixed OS shim: no job input, model configuration or user script is interpolated here.
// Windows 8+ inherits unnamed Job Objects; no breakaway is enabled.
// https://learn.microsoft.com/en-us/windows/win32/procthread/job-objects
const windowsGuard = String.raw`
$ErrorActionPreference = 'Stop'
$owner = $null
$job = [IntPtr]::Zero
try {
  $owner = [Diagnostics.Process]::GetProcessById([int]$env:MARLIN_JOB_OWNER_PID)
  $ownerHandle = $owner.Handle
  [Console]::Out.WriteLine('pinned')
  [Console]::Out.Flush()
  # A still-live owner must acknowledge this pinned handle before assignment.
  # EOF before acknowledgement cannot assign a reused PID to our Job Object.
  if ([Console]::In.ReadLine() -ne 'assign') { exit 125 }
  Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;
public static class MarlinOwnedJob {
  [StructLayout(LayoutKind.Sequential)] public struct Basic {
    public long ProcessTime, JobTime;
    public uint Flags;
    public UIntPtr Minimum, Maximum;
    public uint Active;
    public UIntPtr Affinity;
    public uint Priority, Scheduling;
  }
  [StructLayout(LayoutKind.Sequential)] public struct Io {
    public ulong ReadOperations, WriteOperations, OtherOperations, ReadBytes, WriteBytes, OtherBytes;
  }
  [StructLayout(LayoutKind.Sequential)] public struct Extended {
    public Basic Basic;
    public Io Io;
    public UIntPtr ProcessMemory, JobMemory, PeakProcess, PeakJob;
  }
  [DllImport("kernel32.dll", CharSet=CharSet.Unicode, SetLastError=true)]
  static extern IntPtr CreateJobObjectW(IntPtr attributes, string name);
  [DllImport("kernel32.dll", SetLastError=true)]
  static extern bool SetInformationJobObject(IntPtr job, int kind, ref Extended info, uint size);
  [DllImport("kernel32.dll", SetLastError=true)]
  static extern bool AssignProcessToJobObject(IntPtr job, IntPtr process);
  [DllImport("kernel32.dll")] static extern IntPtr GetCurrentProcess();
  [DllImport("kernel32.dll")] public static extern bool CloseHandle(IntPtr handle);
  public static IntPtr Protect(IntPtr owner) {
    IntPtr job = CreateJobObjectW(IntPtr.Zero, null);
    if (job == IntPtr.Zero) throw new InvalidOperationException("Job creation failed");
    Extended info = new Extended();
    info.Basic.Flags = 0x2000; // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
    if (!SetInformationJobObject(job, 9, ref info, (uint)Marshal.SizeOf(typeof(Extended))) ||
        !AssignProcessToJobObject(job, GetCurrentProcess()) || !AssignProcessToJobObject(job, owner)) {
      CloseHandle(job);
      throw new InvalidOperationException("Job protection failed");
    }
    return job;
  }
}
'@
  $job = [MarlinOwnedJob]::Protect($ownerHandle)
  [Console]::Out.WriteLine('ready')
  [Console]::Out.Flush()
  while ([Console]::In.Read() -ne -1) {}
} catch { exit 125 }
finally {
  if ($job -ne [IntPtr]::Zero) { [void][MarlinOwnedJob]::CloseHandle($job) }
  if ($owner) { $owner.Dispose() }
}
`;

/** Inline executable source is part of the compiled core, including inside ASAR.
 * Electron must preserve RunAsNode; ELECTRON_RUN_AS_NODE uses its bundled Node,
 * not a system Node installation. A disabled fuse must fail startup, never fall
 * back to an unprotected payload. No ordinary job depends on Python.
 * https://www.electronjs.org/docs/latest/tutorial/fuses#runasnode
 */
export const ownedSupervisorSource = String.raw`
'use strict';
const {spawn} = require('node:child_process');
const {join} = require('node:path');
const {StringDecoder} = require('node:string_decoder');
const windowsGuard = __WINDOWS_GUARD__;
const keepAlive = setInterval(() => {}, 1000);
let stopping = false, started = false, payload, guard, guardReady = false, guardTimer;
let reported = false, reportSent = Promise.resolve();
function report(result) {
  if (reported) return;
  reported = true;
  if (process.connected) reportSent = new Promise(resolve => process.send({type:'result', ...result}, () => resolve()));
}
function stoppedWithoutGroup() {
  clearInterval(keepAlive);
  // Explicit failures must reach the host before an unprotected bootstrap exits.
  reportSent.then(() => process.exit(125));
}
function stopTree() {
  if (stopping) return;
  stopping = true;
  if (process.platform === 'win32') {
    // The guard owns the last Job Object handle. EOF kills the protected tree,
    // even after the payload or its parent has already exited.
    if (guard && guard.exitCode === null && guard.signalCode === null) guard.stdin.end();
    else stoppedWithoutGroup();
  } else {
    // This supervisor itself is the persistent PGID owner until the final kill.
    // Payloads use private pipes and inherit our group, never a foreign group.
    try { process.kill(-process.pid, 'SIGTERM'); } catch {}
    setTimeout(() => { try { process.kill(-process.pid, 'SIGKILL'); } catch { process.exit(125); } }, 250);
  }
}
process.on('SIGTERM', stopTree);
process.on('SIGINT', stopTree);
process.on('disconnect', stopTree);
process.stdout.on('error', stopTree);
process.stderr.on('error', stopTree);
function fail(code) { report({error:code}); stopTree(); }
function run(input) {
  if (stopping) { stopTree(); return; }
  try {
    const env = input.env || process.env;
    // Running the bundled Electron executable as a helper also needs Node mode.
    const payloadEnv = input.file === process.execPath ? {...env, ELECTRON_RUN_AS_NODE:'1'} : env;
    payload = spawn(input.file, input.args, {cwd:input.cwd, env:payloadEnv, shell:false, windowsHide:true, stdio:['pipe','pipe','pipe']});
    payload.stdin.on('error', () => {});
    process.stdin.pipe(payload.stdin);
    payload.stdout.pipe(process.stdout, {end:false});
    payload.stderr.pipe(process.stderr, {end:false});
    payload.once('error', () => fail('child_start_failed'));
    payload.once('spawn', () => { if (process.connected) process.send({type:'started'}, () => {}); });
    payload.once('exit', (code, signal) => { report({code, signal}); stopTree(); });
  } catch { fail('child_start_failed'); }
}
function protectWindows(input) {
  try {
    const powershell = join(process.env.SystemRoot || 'C:\\Windows', 'System32', 'WindowsPowerShell', 'v1.0', 'powershell.exe');
    guard = spawn(powershell, ['-NoLogo','-NoProfile','-NonInteractive','-EncodedCommand',Buffer.from(windowsGuard,'utf16le').toString('base64')], {
      env:{...process.env, MARLIN_JOB_OWNER_PID:String(process.pid)}, shell:false, windowsHide:true, stdio:['pipe','pipe','pipe']
    });
    const decoder = new StringDecoder('utf8'); let pending = '';
    guard.stdin.on('error', () => {});
    guard.stderr.resume(); // Compiler/native errors may contain paths; never relay.
    guard.stdout.on('data', bytes => {
      pending += decoder.write(bytes);
      for (;;) {
        const newline = pending.indexOf('\n'); if (newline < 0) break;
        const line = pending.slice(0,newline).trim(); pending = pending.slice(newline+1);
        if (line === 'pinned' && !stopping) guard.stdin.write('assign\n');
        if (line === 'ready') {
          guardReady = true; clearTimeout(guardTimer);
          if (stopping) guard.stdin.end(); else run(input);
        }
      }
    });
    guard.once('error', () => { report({error:'child_isolation_failed'}); stoppedWithoutGroup(); });
    guard.once('exit', () => {
      clearTimeout(guardTimer);
      if (!guardReady) { report({error:'child_isolation_failed'}); stoppedWithoutGroup(); }
    });
    guardTimer = setTimeout(() => {
      report({error:'child_isolation_failed'});
      // This is our live ChildProcess handle, never a discovered/reused PID.
      guard.kill('SIGKILL');
    }, 10000);
    if (stopping) guard.stdin.end();
  } catch { fail('child_isolation_failed'); }
}
process.on('message', input => {
  if (input && input.type === 'stop') { stopTree(); return; }
  if (!input || input.type !== 'start' || started || stopping) return;
  started = true;
  if (process.platform === 'win32') protectWindows(input); else run(input);
});
`.replace('__WINDOWS_GUARD__', JSON.stringify(windowsGuard));
