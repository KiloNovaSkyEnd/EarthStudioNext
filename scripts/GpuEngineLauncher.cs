// Windows framework launcher: CUDA NVRTC requires ASCII header/source paths.
using System;
using System.Diagnostics;
using System.IO;
using System.Security.Cryptography;
using System.Text;

class GpuEngineLauncher
{
    static string Quote(string value)
    {
        var result = new StringBuilder("\""); int slashes = 0;
        foreach (char ch in value)
        {
            if (ch == '\\') { slashes++; continue; }
            result.Append('\\', ch == '"' ? slashes * 2 + 1 : slashes);
            result.Append(ch); slashes = 0;
        }
        result.Append('\\', slashes * 2); result.Append('"'); return result.ToString();
    }

    static int Main(string[] args)
    {
        try
        {
            Console.OutputEncoding = new UTF8Encoding(false);
            Console.InputEncoding = new UTF8Encoding(false);
            string engineRoot = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
            string cache = Environment.GetEnvironmentVariable("EARTHSTUDIO_GPU_ALIAS_ROOT");
            if (String.IsNullOrEmpty(cache)) cache = Path.Combine(Environment.GetFolderPath(Environment.SpecialFolder.LocalApplicationData), "Deepsky", "EarthStudio", "GpuRuntime");
            foreach (char ch in cache) if (ch > 127) throw new IOException("Set EARTHSTUDIO_GPU_ALIAS_ROOT to a writable ASCII path for CUDA.");
            Directory.CreateDirectory(cache);
            string hash;
            using (var sha = SHA256.Create()) hash = BitConverter.ToString(sha.ComputeHash(Encoding.UTF8.GetBytes(engineRoot.ToUpperInvariant()))).Replace("-", "").Substring(0, 16);
            string alias = Path.Combine(cache, "engine_" + hash);
            if (!Directory.Exists(alias))
            {
                var link = new ProcessStartInfo(Path.Combine(Environment.SystemDirectory, "cmd.exe"), "/d /c mklink /J " + Quote(alias) + " " + Quote(engineRoot));
                link.UseShellExecute = false; link.CreateNoWindow = true;
                link.RedirectStandardOutput = true; link.RedirectStandardError = true;
                using (var process = Process.Start(link))
                {
                    string output = process.StandardOutput.ReadToEnd(); string error = process.StandardError.ReadToEnd(); process.WaitForExit();
                    if (process.ExitCode != 0) throw new IOException("GPU path alias creation failed: " + output + error);
                }
            }
            string target = Path.Combine(alias, "EarthScience.Cuda.exe");
            if (!File.Exists(target)) throw new FileNotFoundException("GPU runtime alias is unavailable", target);
            var command = new StringBuilder(); foreach (string arg in args) command.Append(Quote(arg)).Append(' ');
            var info = new ProcessStartInfo(target, command.ToString());
            info.UseShellExecute = false; info.CreateNoWindow = true;
            info.RedirectStandardOutput = true; info.RedirectStandardError = true;
            info.StandardOutputEncoding = new UTF8Encoding(false);
            info.StandardErrorEncoding = new UTF8Encoding(false);
            bool bridge = args.Length > 0 && args[0] == "bridge";
            info.RedirectStandardInput = bridge;
            info.EnvironmentVariables["CUPY_CACHE_IN_MEMORY"] = "1";
            info.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
            info.EnvironmentVariables["PYTHONUTF8"] = "1";
            using (var process = new Process())
            {
                process.StartInfo = info;
                process.OutputDataReceived += (sender, data) => { if (data.Data != null) Console.Out.WriteLine(data.Data); };
                process.ErrorDataReceived += (sender, data) => { if (data.Data != null) Console.Error.WriteLine(data.Data); };
                process.Start(); process.BeginOutputReadLine(); process.BeginErrorReadLine();
                if (bridge) { process.StandardInput.Write(Console.In.ReadToEnd()); process.StandardInput.Close(); }
                process.WaitForExit(); return process.ExitCode;
            }
        }
        catch (Exception error) { Console.Error.WriteLine(error.ToString()); return 1; }
    }
}
