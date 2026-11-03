#requires -Version 5.1
<#
.SYNOPSIS
    Win + колесо мыши -> громкость, без AutoHotkey.

.DESCRIPTION
    Ставит низкоуровневый хук мыши (WH_MOUSE_LL) через встроенный .NET и
    шлёт VK_VOLUME_UP / VK_VOLUME_DOWN, когда колесо крутят с зажатым Win.
    Обычный скролл не трогает.

    Запуск (без окна):
        powershell.exe -NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass `
            -File "...\tools\win-scroll-volume.ps1"

    Установить/убрать автозапуск (ярлык в shell:startup):
        ... -File "...\tools\win-scroll-volume.ps1" -Install
        ... -File "...\tools\win-scroll-volume.ps1" -Uninstall

    Ограничения те же, что у любого хост-хука: игры с raw input и окна,
    запущенные от администратора, хоткей не увидят (если скрипт не elevated).
#>
param(
    [switch]$CompileOnly,
    [switch]$Install,
    [switch]$Uninstall
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
    private const byte VK_VOLUME_UP = 0xAF;
    private const byte VK_VOLUME_DOWN = 0xAE;
    private const uint KEYEVENTF_KEYUP = 0x0002;

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

    private delegate IntPtr LowLevelMouseProc(int nCode, IntPtr wParam, IntPtr lParam);

    private static readonly LowLevelMouseProc proc = HookCallback;
    private static IntPtr hookID = IntPtr.Zero;

    [DllImport("user32.dll", SetLastError = true)]
    private static extern IntPtr SetWindowsHookEx(
        int idHook, LowLevelMouseProc lpfn, IntPtr hMod, uint dwThreadId);

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

    private static bool WinDown()
    {
        return (GetAsyncKeyState(VK_LWIN) & 0x8000) != 0
            || (GetAsyncKeyState(VK_RWIN) & 0x8000) != 0;
    }

    private static void Tap(byte vk)
    {
        keybd_event(vk, 0, 0, UIntPtr.Zero);
        keybd_event(vk, 0, KEYEVENTF_KEYUP, UIntPtr.Zero);
    }

    private static IntPtr HookCallback(int nCode, IntPtr wParam, IntPtr lParam)
    {
        if (nCode >= 0 && wParam == (IntPtr)WM_MOUSEWHEEL && WinDown())
        {
            MSLLHOOKSTRUCT data =
                (MSLLHOOKSTRUCT)Marshal.PtrToStructure(lParam, typeof(MSLLHOOKSTRUCT));
            int delta = (short)((data.mouseData >> 16) & 0xFFFF);
            if (delta > 0)
                Tap(VK_VOLUME_UP);
            else if (delta < 0)
                Tap(VK_VOLUME_DOWN);
            return (IntPtr)1; // съедаем скролл, иначе страница тоже поедет
        }
        return CallNextHookEx(hookID, nCode, wParam, lParam);
    }

    public static void Run()
    {
        using (Process current = Process.GetCurrentProcess())
        using (ProcessModule module = current.MainModule)
        {
            hookID = SetWindowsHookEx(
                WH_MOUSE_LL, proc, GetModuleHandle(module.ModuleName), 0);
        }

        if (hookID == IntPtr.Zero)
            throw new Win32Exception(Marshal.GetLastWin32Error());

        MSG msg;
        while (GetMessage(out msg, IntPtr.Zero, 0, 0) > 0)
        {
            TranslateMessage(ref msg);
            DispatchMessage(ref msg);
        }

        UnhookWindowsHookEx(hookID);
    }
}
'@

Add-Type -TypeDefinition $source -Language CSharp

$startupDir = [Environment]::GetFolderPath('Startup')
$shortcutPath = Join-Path $startupDir 'WinScrollVolume.lnk'
$powershellExe = Join-Path $env:SystemRoot 'System32\WindowsPowerShell\v1.0\powershell.exe'
$shortcutArgs = '-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File "{0}"' -f $PSCommandPath

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
    $shortcut.Description = 'Win + колесо мыши -> громкость'
    $shortcut.Save()
    Write-Host "Автозапуск установлен: $shortcutPath"
    Write-Host "Запустить сейчас: $powershellExe $shortcutArgs"
    exit 0
}

if (-not $CompileOnly) {
    Write-Host "Win + колесо -> громкость. Ctrl+C или закрыть окно, чтобы остановить."
    [WinScrollVolume]::Run()
}
