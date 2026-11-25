Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")
baseDir = fso.GetParentFolderName(WScript.ScriptFullName)
shell.CurrentDirectory = baseDir
shell.Environment("PROCESS")("PATH") = baseDir & "\dsp;" & baseDir & "\runtime;" & baseDir & "\runtime\Lib\site-packages\PySide6;" & baseDir & "\runtime\Lib\site-packages\shiboken6;" & shell.Environment("PROCESS")("PATH")
shell.Environment("PROCESS")("PYTHONUTF8") = "1"
shell.Environment("PROCESS")("QTWEBENGINE_DISABLE_SANDBOX") = "1"
shell.Environment("PROCESS")("QTWEBENGINE_CHROMIUM_FLAGS") = "--disable-features=WebMidi,WebHID,WebUSB,HardwareMediaKeyHandling"

runExe = ""
pywRuntime = baseDir & "\runtime\pythonw.exe"
pywVenv = baseDir & "\.venv\Scripts\pythonw.exe"
pyVenv = baseDir & "\.venv\Scripts\python.exe"
cfgPy = baseDir & "\config\.python_exe.txt"

If fso.FileExists(pywRuntime) Then
    runExe = pywRuntime
ElseIf fso.FileExists(pywVenv) Then
    runExe = pywVenv
ElseIf fso.FileExists(pyVenv) Then
    runExe = pyVenv
ElseIf fso.FileExists(cfgPy) Then
    On Error Resume Next
    Set tf = fso.OpenTextFile(cfgPy, 1)
    linePy = Trim(tf.ReadLine)
    tf.Close
    On Error GoTo 0
    If linePy <> "" And fso.FileExists(linePy) Then
        pywSys = fso.GetParentFolderName(linePy) & "\pythonw.exe"
        If fso.FileExists(pywSys) Then
            runExe = pywSys
        Else
            runExe = linePy
        End If
    End If
End If

If runExe <> "" Then
    rc = shell.Run("""" & runExe & """ """ & baseDir & "\main.py""", 0, True)
    If rc <> 0 Then
        MsgBox "O P61x Console encerrou com erro (codigo " & rc & ")." & vbCrLf & "Execute 'iniciar_p61x.bat' para ver os detalhes no console ou confira a pasta 'logs'.", 16, "P61x Console v1.3.7"
    End If
Else
    shell.Run """" & baseDir & "\iniciar_p61x.bat""", 1, False
End If
