/*
 * Native Windows GUI Launcher for P61x Console.
 * Launches the bundled Python runtime (runtime/pythonw.exe or .venv/Scripts/pythonw.exe)
 * cleanly with all DLL search paths, QtWebEngine safety flags, and early-crash detection.
 * If Python terminates immediately (< 3.5s) with an error, runs a headless diagnostic pass
 * via python.exe capturing stderr into logs/p61x_startup_error.log and displays MessageBoxW.
 */
#ifndef UNICODE
#define UNICODE
#endif
#ifndef _UNICODE
#define _UNICODE
#endif
#define WIN32_LEAN_AND_MEAN
#include <windows.h>
#include <shellapi.h>
#include <stdlib.h>
#include <wchar.h>

static void prepend_path_env(const wchar_t *exe_dir) {
    const size_t CAP = 32768;
    wchar_t *old_path = (wchar_t *)calloc(CAP, sizeof(wchar_t));
    wchar_t *new_path = (wchar_t *)calloc(CAP, sizeof(wchar_t));
    if (!old_path || !new_path) {
        free(old_path);
        free(new_path);
        return;
    }

    DWORD old_len = GetEnvironmentVariableW(L"PATH", old_path, (DWORD)CAP);
    if (old_len >= CAP) old_len = 0;

    _snwprintf(
        new_path,
        CAP,
        L"%ls\\dsp;%ls\\runtime;%ls\\runtime\\Lib\\site-packages\\PySide6;%ls\\runtime\\Lib\\site-packages\\shiboken6%ls%ls",
        exe_dir,
        exe_dir,
        exe_dir,
        exe_dir,
        old_len > 0 ? L";" : L"",
        old_len > 0 ? old_path : L""
    );
    new_path[CAP - 1] = L'\0';
    SetEnvironmentVariableW(L"PATH", new_path);
    free(old_path);
    free(new_path);
}

static int file_exists(const wchar_t *path) {
    DWORD attr = GetFileAttributesW(path);
    return (attr != INVALID_FILE_ATTRIBUTES && !(attr & FILE_ATTRIBUTE_DIRECTORY));
}

static void capture_startup_failure(const wchar_t *exe_dir, const wchar_t *py_console, const wchar_t *main_py, DWORD exit_code) {
    wchar_t logs_dir[MAX_PATH];
    wchar_t err_log[MAX_PATH];
    _snwprintf(logs_dir, MAX_PATH, L"%ls\\logs", exe_dir);
    logs_dir[MAX_PATH - 1] = L'\0';
    CreateDirectoryW(logs_dir, NULL);

    _snwprintf(err_log, MAX_PATH, L"%ls\\logs\\p61x_startup_error.log", exe_dir);
    err_log[MAX_PATH - 1] = L'\0';

    /* If main.py hasn't written a startup error yet and python.exe exists, run a headless trace capture */
    if (!file_exists(err_log) && py_console && file_exists(py_console)) {
        SECURITY_ATTRIBUTES sa;
        ZeroMemory(&sa, sizeof(sa));
        sa.nLength = sizeof(sa);
        sa.bInheritHandle = TRUE;

        HANDLE hLog = CreateFileW(
            err_log,
            GENERIC_WRITE,
            FILE_SHARE_READ,
            &sa,
            CREATE_ALWAYS,
            FILE_ATTRIBUTE_NORMAL,
            NULL
        );
        if (hLog != INVALID_HANDLE_VALUE) {
            wchar_t diag_cmd[2048];
            _snwprintf(diag_cmd, 2048, L"\"%ls\" -X faulthandler \"%ls\" --check", py_console, main_py);
            diag_cmd[2047] = L'\0';

            STARTUPINFOW si;
            PROCESS_INFORMATION pi;
            ZeroMemory(&si, sizeof(si));
            ZeroMemory(&pi, sizeof(pi));
            si.cb = sizeof(si);
            si.dwFlags = STARTF_USESHOWWINDOW | STARTF_USESTDHANDLES;
            si.wShowWindow = SW_HIDE;
            si.hStdOutput = hLog;
            si.hStdError = hLog;
            si.hStdInput = GetStdHandle(STD_INPUT_HANDLE);

            if (CreateProcessW(py_console, diag_cmd, NULL, NULL, TRUE, CREATE_NO_WINDOW, NULL, exe_dir, &si, &pi)) {
                WaitForSingleObject(pi.hProcess, 8000);
                CloseHandle(pi.hThread);
                CloseHandle(pi.hProcess);
            }
            CloseHandle(hLog);
        }
    }

    wchar_t msg[1200];
    _snwprintf(
        msg,
        1200,
        L"O P61x Console encerrou inesperadamente ao iniciar (codigo %lu / 0x%08lX).\n\n"
        L"Confira os logs em:\n%ls\\logs\\p61x_runtime.log\n%ls\n\n"
        L"Dica: Voce tambem pode abrir 'iniciar_p61x.bat' para diagnosticar no terminal.",
        (unsigned long)exit_code,
        (unsigned long)exit_code,
        exe_dir,
        err_log
    );
    msg[1199] = L'\0';
    MessageBoxW(NULL, msg, L"P61x Console — Erro ao Iniciar", MB_ICONERROR | MB_OK);
}

int WINAPI wWinMain(HINSTANCE hInstance, HINSTANCE hPrevInstance, PWSTR pCmdLine, int nCmdShow) {
    (void)hInstance;
    (void)hPrevInstance;
    (void)nCmdShow;

    wchar_t exe_path[MAX_PATH];
    DWORD len = GetModuleFileNameW(NULL, exe_path, MAX_PATH);
    if (len == 0 || len >= MAX_PATH) {
        MessageBoxW(NULL, L"Nao foi possivel localizar a pasta de instalacao do P61x Console.", L"P61x Console", MB_ICONERROR | MB_OK);
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
    SetEnvironmentVariableW(L"QTWEBENGINE_DISABLE_SANDBOX", L"1");
    SetEnvironmentVariableW(
        L"QTWEBENGINE_CHROMIUM_FLAGS",
        L"--disable-features=WebMidi,WebHID,WebUSB,HardwareMediaKeyHandling"
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
    int is_console_py = 0;
    for (int i = 0; i < 4; ++i) {
        _snwprintf(py_exe, MAX_PATH, L"%ls\\%ls", exe_dir, candidates[i]);
        py_exe[MAX_PATH - 1] = L'\0';
        if (file_exists(py_exe)) {
            found = 1;
            is_console_py = (i == 1 || i == 3);
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

    wchar_t py_console[MAX_PATH];
    _snwprintf(py_console, MAX_PATH, L"%ls\\runtime\\python.exe", exe_dir);
    py_console[MAX_PATH - 1] = L'\0';
    if (!file_exists(py_console)) {
        _snwprintf(py_console, MAX_PATH, L"%ls\\.venv\\Scripts\\python.exe", exe_dir);
        py_console[MAX_PATH - 1] = L'\0';
    }

    wchar_t *cmdline = (wchar_t *)calloc(8192, sizeof(wchar_t));
    if (!cmdline) return 1;
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
    si.wShowWindow = is_console_py ? SW_HIDE : SW_SHOWNORMAL;

    /* Avoid DETACHED_PROCESS which invalidates std handles for Chromium/QtWebEngine helpers */
    DWORD flags = is_console_py ? CREATE_NO_WINDOW : 0;
    if (!CreateProcessW(py_exe, cmdline, NULL, NULL, FALSE, flags, NULL, exe_dir, &si, &pi)) {
        DWORD err = GetLastError();
        free(cmdline);
        wchar_t err_msg[512];
        _snwprintf(
            err_msg,
            512,
            L"Falha ao iniciar o P61x Console (CreateProcessW erro %lu).\nVerifique se o antivirus nao bloqueou 'runtime\\pythonw.exe'.",
            (unsigned long)err
        );
        err_msg[511] = L'\0';
        MessageBoxW(NULL, err_msg, L"P61x Console — Erro", MB_ICONERROR | MB_OK);
        return 1;
    }
    free(cmdline);

    /* Monitor first 3.5s: if Python dies quickly with non-zero code, show diagnostics immediately;
       otherwise exit launcher cleanly so P61x Console.exe isn't file-locked during self-updates. */
    DWORD wait_res = WaitForSingleObject(pi.hProcess, 3500);
    if (wait_res == WAIT_OBJECT_0) {
        DWORD exit_code = 0;
        if (GetExitCodeProcess(pi.hProcess, &exit_code) && exit_code != 0) {
            CloseHandle(pi.hThread);
            CloseHandle(pi.hProcess);
            capture_startup_failure(exe_dir, py_console, main_py, exit_code);
            return (int)exit_code;
        }
    }

    CloseHandle(pi.hThread);
    CloseHandle(pi.hProcess);
    return 0;
}
