// Stable entry point for shortcuts and Windows startup.
//
// The installer keeps the selected edition under {app}\runtime\<edition>, so
// switching editions changes the real executable path. Shortcuts, taskbar pins
// and the startup entry point at {app}\WatchedKettle.exe instead, and this
// launcher starts whichever runtime the installer recorded.
// build_installer.ps1 compiles it with the .NET Framework csc.exe shipped with Windows.
using System;
using System.Diagnostics;
using System.IO;
using System.Runtime.InteropServices;

static class WatchedKettleLauncher
{
    const string ExecutableName = "WatchedKettle.exe";
    // Written by the installer after it removes the other edition.
    const string EditionMarker = "edition";
    static readonly string[] Editions = { "pet-assistant", "pet-only" };

    [DllImport("user32.dll", CharSet = CharSet.Unicode)]
    static extern int MessageBoxW(IntPtr owner, string text, string caption, uint type);

    [STAThread]
    static int Main()
    {
        string runtimeRoot = Path.Combine(AppDomain.CurrentDomain.BaseDirectory, "runtime");
        string target = FindRuntime(runtimeRoot);
        if (target == null)
        {
            MessageBoxW(IntPtr.Zero,
                "Watched Kettle 프로그램을 찾지 못했습니다. 설치 프로그램을 다시 실행해 주세요.\n\n" +
                "Could not find the Watched Kettle program. Please run the installer again.",
                "Watched Kettle", 0x10);
            return 1;
        }
        ProcessStartInfo info = new ProcessStartInfo(target, ArgumentsAfterProgram(Environment.CommandLine));
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

    static string FindRuntime(string runtimeRoot)
    {
        try
        {
            string recorded = File.ReadAllText(Path.Combine(runtimeRoot, EditionMarker)).Trim();
            if (Array.IndexOf(Editions, recorded) >= 0)
            {
                string candidate = Path.Combine(Path.Combine(runtimeRoot, recorded), ExecutableName);
                if (File.Exists(candidate))
                    return candidate;
            }
        }
        catch (IOException) { }
        catch (UnauthorizedAccessException) { }
        foreach (string edition in Editions)
        {
            string candidate = Path.Combine(Path.Combine(runtimeRoot, edition), ExecutableName);
            if (File.Exists(candidate))
                return candidate;
        }
        return null;
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
