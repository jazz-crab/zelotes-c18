#requires -Version 5.1
<#
.SYNOPSIS
    Колесо мыши с модификатором -> громкость, без AutoHotkey.

.DESCRIPTION
    Ставит низкоуровневый хук мыши через встроенный .NET. По умолчанию
    работает Alt + колесо (Alt при отпускании ничего не открывает).
    Флаг -Win переключает на Win + колесо; там дополнительно отправляется
    пустое нажатие Ctrl, чтобы Windows не открыла «Пуск» на отпускании Win.

    Запуск (без окна):
        powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass `
            -File "...\tools\win-scroll-volume.ps1"

    Установить/убрать автозапуск (ярлык в shell:startup):
        ... -File "...\tools\win-scroll-volume.ps1" -Install [-Win]
        ... -File "...\tools\win-scroll-volume.ps1" -Uninstall

    Ограничения те же, что у любого хост-хука: игры с raw input и окна,
    запущенные от администратора, хоткей не увидят (если скрипт не elevated).
#>
param(
    [switch]$CompileOnly,
    [switch]$Install,
    [switch]$Uninstall,
    [switch]$Win
)

$source = @'
using System;
using System.ComponentModel;
using System.Diagnostics;
using System.Runtime.InteropServices;

public static class WinScrollVolume
{
    private const int WH_MOUSE_LL = 14;
    private const int WM_MOUSEWHEEL = 0x020A;
    private const int VK_LWIN = 0x5B;
    private const int VK_RWIN = 0x5C;
    private const int VK_SHIFT = 0x10;
    private const int VK_CONTROL = 0x11;
    private const int VK_MENU = 0x12;
    private const int VK_F24 = 0x87;
    private const byte VK_VOLUME_UP = 0xAF;
    private const byte VK_VOLUME_DOWN = 0xAE;
    private const uint KEYEVENTF_KEYUP = 0x0002;

    public static bool UseWin = false;

    [StructLayout(LayoutKind.Sequential)]
    private struct POINT
    {
        public int x;
        public int y;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct MSLLHOOKSTRUCT
    {
        public POINT pt;
        public uint mouseData;
        public uint flags;
        public uint time;
        public IntPtr dwExtraInfo;
    }

    // x64 MSG is 48 bytes: hwnd, message, wParam, lParam, time, pt, lPrivate.
    [StructLayout(LayoutKind.Sequential)]
    private struct MSG
    {
        public IntPtr hwnd;
        public uint message;
        public IntPtr wParam;
        public IntPtr lParam;
        public uint time;
        public POINT pt;
        public uint lPrivate;
    }

    private delegate IntPtr HookProc(int nCode, IntPtr wParam, IntPtr lParam);

    private static readonly HookProc mouseProc = MouseCallback;
    private static IntPtr mouseHook = IntPtr.Zero;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(
        int idHook, HookProc lpfn, IntPtr hMod, uint dwThreadId);

    [DllImport("user32.dll", SetLastError = true)]
    private static extern bool UnhookWindowsHookEx(IntPtr hhk);

    [DllImport("user32.dll")]
    private static extern IntPtr CallNextHookEx(
        IntPtr hhk, int nCode, IntPtr wParam, IntPtr lParam);

    [DllImport("kernel32.dll", CharSet = CharSet.Auto)]
    private static extern IntPtr GetModuleHandle(string lpModuleName);

    [DllImport("user32.dll")]
    private static extern short GetAsyncKeyState(int vKey);

    [DllImport("user32.dll")]
    private static extern void keybd_event(
        byte bVk, byte bScan, uint dwFlags, UIntPtr dwExtraInfo);

    [DllImport("user32.dll")]
    private static extern int GetMessage(
        out MSG lpMsg, IntPtr hWnd, uint wMsgFilterMin, uint wMsgFilterMax);

    [DllImport("user32.dll")]
    private static extern bool TranslateMessage(ref MSG lpMsg);

    [DllImport("user32.dll")]
    private static extern IntPtr DispatchMessage(ref MSG lpMsg);

    private static bool Down(int vk)
    {
        return (GetAsyncKeyState(vk) & 0x8000) != 0;
    }

    private static bool ModifierDown()
    {
        if (UseWin)
            return Down(VK_LWIN) || Down(VK_RWIN);
        return Down(VK_MENU);
    }

    private static void Tap(byte vk)
    {
        keybd_event(vk, 0, 0, UIntPtr.Zero);
        keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    }

    // Для режима Win: Windows открывает «Пуск» на отпускании Win, если за
    // время удержания не было обычного нажатия клавиши. Медиа-клавиши она не
    // считает, поэтому жмём нейтральный модификатор, который не занят.
    private static byte DummyKey()
    {
        if (!Down(VK_CONTROL)) return (byte)VK_CONTROL;
        if (!Down(VK_SHIFT)) return (byte)VK_SHIFT;
        if (!Down(VK_MENU)) return (byte)VK_MENU;
        return (byte)VK_F24;
    }

    private static void Log(string text)
    {
        string path = Environment.GetEnvironmentVariable("WIN_SCROLL_VOLUME_LOG");
        if (string.IsNullOrEmpty(path)) return;
        try
        {
            System.IO.File.AppendAllText(
                path, DateTime.Now.ToString("HH:mm:ss.fff") + " " + text + "\r\n");
        }
        catch
        {
        }
    }

    private static IntPtr MouseCallback(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode >= 0 && wParam == (IntPtr)WM_MOUSEWHEEL && ModifierDown())
        {
            MSLLHOOKSTRUCT data =
                (MSLLHOOKSTRUCT)Marshal.PtrToStructure(lParam, typeof(MSLLHOOKSTRUCT));
            int delta = (short)((data.mouseData >> 16) & 0xFFFF);

            if (UseWin)
                Tap(DummyKey());
            if (delta > 0)
                Tap(VK_VOLUME_UP);
            else if (delta < 0)
                Tap(VK_VOLUME_DOWN);

            Log("wheel delta=" + delta + " mode=" + (UseWin ? "win" : "alt"));
            return (IntPtr)1; // съедаем скролл, иначе страница тоже поедет
        }
        return CallNextHookEx(mouseHook, nCode, wParam, lParam);
    }

    public static void Run()
    {
        using (Process current = Process.GetCurrentProcess())
        using (ProcessModule module = current.MainModule)
        {
            mouseHook = SetWindowsHookEx(
                WH_MOUSE_LL, mouseProc, GetModuleHandle(module.ModuleName), 0);
        }

        if (mouseHook == IntPtr.Zero)
            throw new Win32Exception(Marshal.GetLastWin32Error());

        MSG msg;
        while (GetMessage(out msg, IntPtr.Zero, 0, 0) > 0)
        {
            TranslateMessage(ref msg);
            DispatchMessage(ref msg);
        }

        UnhookWindowsHookEx(mouseHook);
    }
}
'@

Add-Type -TypeDefinition $source -Language CSharp
[WinScrollVolume]::UseWin = [bool]$Win

$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir 'WinScrollVolume.lnk'
$powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcutArgs = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $PSCommandPath
if ($Win) {
    $shortcutArgs += ' -Win'
}

if ($Uninstall) {
    if (Test-Path $shortcutPath) {
        Remove-Item $shortcutPath -Force
        Write-Host "Удалён автозапуск: $shortcutPath"
    } else {
        Write-Host "Автозапуск не был установлен."
    }

    $hookPattern = '-File\s+"?' + [regex]::Escape($PSCommandPath) + '"?'
    Get-CimInstance Win32_Process |
        Where-Object {
            $_.ProcessId -ne $PID -and
            $_.CommandLine -and
            $_.CommandLine -match $hookPattern -and
            $_.CommandLine -notmatch '-Install|-Uninstall|-CompileOnly'
        } |
        ForEach-Object {
            Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue
            Write-Host "Остановлен процесс PID $($_.ProcessId)."
        }
    exit 0
}

if ($Install) {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powershellExe
    $shortcut.Arguments = $shortcutArgs
    $shortcut.WorkingDirectory = Split-Path $PSCommandPath
    $shortcut.WindowStyle = 7
    $shortcut.Description = 'Колесо + модификатор -> громкость'
    $shortcut.Save()
    Write-Host "Автозапуск установлен: $shortcutPath"
    Write-Host "Запустить сейчас: $powershellExe $shortcutArgs"
    exit 0
}

if (-not $CompileOnly) {
    $mode = if ($Win) { 'Win' } else { 'Alt' }
    Write-Host "$mode + колесо -> громкость. Ctrl+C или закрыть окно, чтобы остановить."
    [WinScrollVolume]::Run()
}
