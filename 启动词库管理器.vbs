' Prompt Library Manager silent launcher (no console window)
Set fso = CreateObject("Scripting.FileSystemObject")
Set shell = CreateObject("WScript.Shell")

base = fso.GetParentFolderName(WScript.ScriptFullName)
exe = base & "\dist\PromptLibraryManager\PromptLibraryManager.exe"

If fso.FileExists(exe) Then
    shell.CurrentDirectory = base & "\dist\PromptLibraryManager"
    shell.Run """" & exe & """", 0, False
Else
    shell.CurrentDirectory = base
    shell.Run "pythonw.exe main.py", 0, False
End If
