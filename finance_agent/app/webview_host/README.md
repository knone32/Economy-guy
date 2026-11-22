# Native WebView2 host

GuiWindow.cs is compiled with Windows .NET Framework csc (x64, winexe), referencing System.Windows.Forms/System.Drawing/System.Web.Extensions and the adjacent Microsoft.Web.WebView2.Core/WinForms SDK DLLs. DLLs are the existing E:/beside SDK copies, not a separate Python/CLR bridge. GuiWindow.exe is the compiled copy of this source.

Python passes local URL, an individual status-file path, and an ephemeral local GUI token. No API credential enters native arguments or status. Navigation and frontend initialization must both complete before startup succeeds. Closing asks the original host to verify current state. No default browser fallback and no automatic approval.

A WebView2 Runtime and .NET Framework 4.6.2+ are required on Windows. SDK source: https://developer.microsoft.com/microsoft-edge/webview2/ . Frozen external process DLL handling: https://pyinstaller.org/en/stable/common-issues-and-pitfalls.html .
