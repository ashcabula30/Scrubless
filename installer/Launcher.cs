// Scrubless.exe: starts the app (pythonw -m footage_finder app) with no console window.
// Settings come from launcher.ini next to this exe:
//   data=D:\footage-finder-data      where the Python environment and AI models live
//   app=<folder with footage_finder> defaults to the "app" folder next to this exe
using System;
using System.Diagnostics;
using System.IO;
using System.Windows.Forms;

static class Launcher
{
    [STAThread]
    static void Main()
    {
        string here = AppDomain.CurrentDomain.BaseDirectory;
        string data = @"D:\footage-finder-data";
        string app = Path.Combine(here, "app");
        string ini = Path.Combine(here, "launcher.ini");
        if (File.Exists(ini))
        {
            foreach (string raw in File.ReadAllLines(ini))
            {
                string line = raw.Trim();
                int eq = line.IndexOf('=');
                if (eq <= 0 || line.StartsWith("#") || line.StartsWith(";")) continue;
                string key = line.Substring(0, eq).Trim().ToLowerInvariant();
                string val = Environment.ExpandEnvironmentVariables(line.Substring(eq + 1).Trim());
                if (key == "data") data = val;
                else if (key == "app") app = val;
            }
        }

        string pythonw = Path.Combine(data, @"venv\Scripts\pythonw.exe");
        if (!File.Exists(pythonw))
        {
            var answer = MessageBox.Show(
                "Scrubless needs a one-time setup on this PC: Python and the AI libraries, about 4 GB " +
                "downloaded into " + data + ".\n\nSet it up now? A window shows the progress and Scrubless " +
                "opens when it's done.",
                "Scrubless", MessageBoxButtons.YesNo, MessageBoxIcon.Information);
            if (answer == DialogResult.Yes)
            {
                // Started through Explorer, not as our child: when the installer opens the app, Windows
                // applies the installer's restrictions to its children and uv's Python folder junction
                // fails ("untrusted mount point").
                string setup = Path.Combine(here, @"tools\setup.cmd");
                Process.Start("explorer.exe", "\"" + setup + "\"");
            }
            return;
        }

        var psi = new ProcessStartInfo(pythonw, "-m footage_finder app")
        {
            WorkingDirectory = app,  // python -m puts this folder first on the import path
            UseShellExecute = false,
            CreateNoWindow = true,
        };
        psi.EnvironmentVariables["FF_DATA"] = data;
        psi.EnvironmentVariables["HF_HOME"] = Path.Combine(data, "models");
        psi.EnvironmentVariables["FF_LOG"] = "1";  // no console: the app writes to <data>\app.log
        try
        {
            Process.Start(psi);
        }
        catch (Exception e)
        {
            MessageBox.Show("Couldn't start Scrubless:\n" + e.Message, "Scrubless",
                MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
