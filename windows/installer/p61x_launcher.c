/*
 * Native Windows GUI Launcher for P61x Console.
 * Launches the bundled Python runtime (runtime/pythonw.exe or .venv/Scripts/pythonw.exe)
 * completely headless (no terminal window, no lock held on P61x Console.exe during self-updates),
 * prepending dsp/, runtime/, and PySide6 DLL directories plus WebEngine safety flags.
 */
#define UNICODE
#define _UNICODE
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <wchar.h>

static void prepend_path_env(const wchar_t *exe_dir) {
    wchar_t old_path[32768];
    old_path[0] = L'\0';
    DWORD old_len = GetEnvironmentVariableW(L"PATH", old_path, 32768);
    if (old_len >= 32768) old_len = 0;

    wchar_t new_path[32768];
    _snwprintf(
        new_path,
        32768,
        L"%ls\\dsp;%ls\\runtime;%ls\\runtime\\Lib\\site-packages\\PySide6%ls%ls",
        exe_dir,
        exe_dir,
        exe_dir,
        old_len > 0 ? L";" : L"",
        old_len > 0 ? old_path : L""
    );
    new_path[32767] = L'\0';
    SetEnvironmentVariableW(L"PATH", new_path);
}

static int file_exists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    (void)hInstance;
    (void)hPrevInstance;
    (void)nCmdShow;

    wchar_t exe_path[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, exe_path, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) {
        MessageBoxW(NULL, L"Nao foi possivel localizar o diretorio do P61x Console.", L"P61x Console", MB_ICONERROR | MB_OK);
        return 1;
    }

    wchar_t exe_dir[MAX_PATH];
    wcsncpy(exe_dir, exe_path, MAX_PATH - 1);
    exe_dir[MAX_PATH - 1] = L'\0';
    wchar_t *last_sep = wcsrchr(exe_dir, L'\\');
    if (last_sep) *last_sep = L'\0';

    prepend_path_env(exe_dir);
    SetEnvironmentVariableW(L"PYTHONUTF8", L"1");
    SetEnvironmentVariableW(L"PYTHONNOUSERSITE", L"1");
    SetEnvironmentVariableW(
        L"QTWEBENGINE_CHROMIUM_FLAGS",
        L"--disable-features=WebMidi,WebHid,WebUSB,HardwareMediaKeyHandling"
    );

    wchar_t main_py[MAX_PATH];
    _snwprintf(main_py, MAX_PATH, L"%ls\\main.py", exe_dir);
    main_py[MAX_PATH - 1] = L'\0';
    if (!file_exists(main_py)) {
        MessageBoxW(NULL, L"Arquivo main.py nao encontrado na pasta de instalacao.", L"P61x Console", MB_ICONERROR | MB_OK);
        return 1;
    }

    const wchar_t *candidates[] = {
        L"runtime\\pythonw.exe",
        L"runtime\\python.exe",
        L".venv\\Scripts\\pythonw.exe",
        L".venv\\Scripts\\python.exe"
    };
    wchar_t py_exe[MAX_PATH];
    int found = 0;
    for (int i = 0; i < 4; ++i) {
        _snwprintf(py_exe, MAX_PATH, L"%ls\\%ls", exe_dir, candidates[i]);
        py_exe[MAX_PATH - 1] = L'\0';
        if (file_exists(py_exe)) {
            found = 1;
            break;
        }
    }

    if (!found) {
        wchar_t bat_path[MAX_PATH];
        _snwprintf(bat_path, MAX_PATH, L"%ls\\iniciar_p61x.bat", exe_dir);
        bat_path[MAX_PATH - 1] = L'\0';
        if (file_exists(bat_path)) {
            ShellExecuteW(NULL, L"open", bat_path, pCmdLine, exe_dir, SW_SHOWNORMAL);
            return 0;
        }
        MessageBoxW(
            NULL,
            L"Runtime Python embutido nao encontrado.\nExecute instalar_windows.bat ou reinstale usando o Setup .exe.",
            L"P61x Console",
            MB_ICONERROR | MB_OK
        );
        return 1;
    }

    wchar_t cmdline[8192];
    if (pCmdLine && pCmdLine[0] != L'\0') {
        _snwprintf(cmdline, 8192, L"\"%ls\" \"%ls\" %ls", py_exe, main_py, pCmdLine);
    } else {
        _snwprintf(cmdline, 8192, L"\"%ls\" \"%ls\"", py_exe, main_py);
    }
    cmdline[8191] = L'\0';

    STARTUPINFOW si;
    PROCESS_INFORMATION pi;
    ZeroMemory(&si, sizeof(si));
    ZeroMemory(&pi, sizeof(pi));
    si.cb = sizeof(si);
    si.dwFlags = STARTF_USESHOWWINDOW;
    si.wShowWindow = SW_HIDE;

    DWORD flags = CREATE_NO_WINDOW | DETACHED_PROCESS;
    if (!CreateProcessW(py_exe, cmdline, NULL, NULL, FALSE, flags, NULL, exe_dir, &si, &pi)) {
        MessageBoxW(
            NULL,
            L"Falha ao iniciar o motor P61x Console (CreateProcessW).",
            L"P61x Console",
            MB_ICONERROR | MB_OK
        );
        return 1;
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
