// Stable entry point for shortcuts and Windows startup.
//
// The installer keeps the selected edition under {app}\runtime\<edition>, so
// switching editions changes the real executable path. Shortcuts, taskbar pins
// and the startup entry point at {app}\WatchedKettle.exe instead, and this
// launcher starts whichever runtime the installer recorded.
//
// A partial update (docs/decisions/0007-partial-updates.md) prepares the new
// runtime beside the current one as runtime\<edition>.next and then starts
// this launcher with --apply-staged-update before the app quits. The launcher
// swaps the folders once nothing runs from the current one, then starts the
// app as usual.
// build_installer.ps1 compiles it with the .NET Framework csc.exe shipped with Windows.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;
using System.Threading;

static class WatchedKettleLauncher
{
    const string ExecutableName = "WatchedKettle.exe";
    // Written by the installer after it removes the other edition.
    const string EditionMarker = "edition";
    static readonly string[] Editions = { "pet-assistant", "pet-only" };
    const string ApplyFlag = "--apply-staged-update";
    // The app writes this last, so a half-prepared folder is never swapped in.
    const string ReadyMarker = ".ready";
    // Read by the app on its next start (watched_kettle/application/update_check.py).
    const string ResultFile = "update-result.txt";
    const string ApplyMutex = @"Local\watched-kettle-update-apply";
    // Long enough for the app, its settings window and a hook bridge call to exit.
    const int ApplyWaitMilliseconds = 30000;
    const int RetryMilliseconds = 250;

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    [STAThread]
    static int Main()
    {
        string runtimeRoot = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "runtime");
        string arguments = ArgumentsAfterProgram(Environment.CommandLine);
        bool applyRequested = StartsWithFlag(arguments, ApplyFlag);
        if (applyRequested)
            arguments = arguments.Substring(ApplyFlag.Length).TrimStart(' ', '\t');
        // A normal start tries once, so a staged update left by a crash still
        // applies, while a second launch next to a running app stays quick.
        ApplyStagedUpdate(runtimeRoot, applyRequested ? ApplyWaitMilliseconds : 0);
        string target = FindRuntime(runtimeRoot);
        if (target == null)
        {
            MessageBoxW(IntPtr.Zero,
                "Watched Kettle 프로그램을 찾지 못했습니다. 설치 프로그램을 다시 실행해 주세요.\n\n" +
                "Could not find the Watched Kettle program. Please run the installer again.",
                "Watched Kettle", 0x10);
            return 1;
        }
        ProcessStartInfo info = new ProcessStartInfo(target, arguments);
        info.UseShellExecute = false;
        info.WorkingDirectory = Path.GetDirectoryName(target);
        try
        {
            Process.Start(info).Dispose();
        }
        catch (Exception error)
        {
            MessageBoxW(IntPtr.Zero,
                "Watched Kettle을 시작하지 못했습니다.\nCould not start Watched Kettle.\n\n" + error.Message,
                "Watched Kettle", 0x10);
            return 1;
        }
        return 0;
    }

    static string RecordedEdition(string runtimeRoot)
    {
        try
        {
            string recorded = File.ReadAllText(Path.Combine(runtimeRoot, EditionMarker)).Trim();
            if (Array.IndexOf(Editions, recorded) >= 0)
                return recorded;
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        return null;
    }

    static string FindRuntime(string runtimeRoot)
    {
        string recorded = RecordedEdition(runtimeRoot);
        if (recorded != null)
        {
            string candidate = Path.Combine(Path.Combine(runtimeRoot, recorded), ExecutableName);
            if (File.Exists(candidate))
                return candidate;
        }
        foreach (string edition in Editions)
        {
            string candidate = Path.Combine(Path.Combine(runtimeRoot, edition), ExecutableName);
            if (File.Exists(candidate))
                return candidate;
        }
        return null;
    }

    // Swap runtime\<edition>.next in for runtime\<edition>. Renaming a folder
    // fails while any file in it is open or running, so the retry also waits
    // for the app to finish quitting. A failure leaves the current runtime in
    // place and the staged one for the app to discard.
    static void ApplyStagedUpdate(string runtimeRoot, int waitMilliseconds)
    {
        string edition = RecordedEdition(runtimeRoot);
        if (edition == null)
            return;
        string current = Path.Combine(runtimeRoot, edition);
        string next = current + ".next";
        string ready = Path.Combine(next, ReadyMarker);
        if (!File.Exists(ready))
            return;
        using (Mutex mutex = new Mutex(false, ApplyMutex))
        {
            bool owned;
            try
            {
                owned = mutex.WaitOne(waitMilliseconds);
            }
            catch (AbandonedMutexException)
            {
                owned = true;
            }
            if (!owned)
                return;
            try
            {
                SwapFolders(runtimeRoot, current, next, ready, waitMilliseconds);
            }
            finally
            {
                mutex.ReleaseMutex();
            }
        }
    }

    static void SwapFolders(string runtimeRoot, string current, string next, string ready, int waitMilliseconds)
    {
        if (!File.Exists(ready))
            return;
        string version;
        try
        {
            version = File.ReadAllText(ready).Trim();
        }
        catch (IOException)
        {
            return;
        }
        string old = current + ".old";
        if (Directory.Exists(old))
        {
            // The app removes old folders at start; one may still be locked.
            old = current + ".old-" + DateTime.UtcNow.Ticks;
        }
        DateTime deadline = DateTime.UtcNow.AddMilliseconds(waitMilliseconds);
        if (Directory.Exists(current))
        {
            while (true)
            {
                try
                {
                    Directory.Move(current, old);
                    break;
                }
                catch (Exception error)
                {
                    if (!(error is IOException || error is UnauthorizedAccessException))
                        throw;
                    if (DateTime.UtcNow >= deadline)
                    {
                        // A normal start next to a running app is not a failure.
                        if (waitMilliseconds > 0)
                            WriteResult(runtimeRoot, "failed", version, "in_use");
                        return;
                    }
                    Thread.Sleep(RetryMilliseconds);
                }
            }
        }
        try
        {
            Directory.Move(next, current);
        }
        catch (Exception error)
        {
            if (!(error is IOException || error is UnauthorizedAccessException))
                throw;
            try
            {
                if (Directory.Exists(old) && !Directory.Exists(current))
                    Directory.Move(old, current);
            }
            catch (IOException) { }
            catch (UnauthorizedAccessException) { }
            WriteResult(runtimeRoot, "failed", version, "swap");
            return;
        }
        try
        {
            File.Delete(Path.Combine(current, ReadyMarker));
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        WriteResult(runtimeRoot, "applied", version, "");
    }

    static void WriteResult(string runtimeRoot, string state, string version, string reason)
    {
        try
        {
            File.WriteAllText(Path.Combine(runtimeRoot, ResultFile),
                "state=" + state + "\nversion=" + version + "\nreason=" + reason + "\n");
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
    }

    static bool StartsWithFlag(string arguments, string flag)
    {
        return arguments == flag ||
            arguments.StartsWith(flag + " ", StringComparison.Ordinal) ||
            arguments.StartsWith(flag + "\t", StringComparison.Ordinal);
    }

    // Forward the original argument text untouched. Windows parses the program
    // name without escapes: a quoted name ends at the next quote, otherwise at
    // the first space or tab.
    static string ArgumentsAfterProgram(string commandLine)
    {
        int index = 0;
        if (commandLine.StartsWith("\""))
        {
            index = commandLine.IndexOf('"', 1);
            index = index < 0 ? commandLine.Length : index + 1;
        }
        else
        {
            while (index < commandLine.Length && commandLine[index] != ' ' && commandLine[index] != '\t')
                index++;
        }
        return commandLine.Substring(index).TrimStart(' ', '\t');
    }
}
