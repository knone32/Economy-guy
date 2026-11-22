using System;
using System.IO;
using System.Collections.Generic;
using System.Web.Script.Serialization;
using System.Windows.Forms;
using System.Net;
using System.Text;
using Microsoft.Web.WebView2.Core;
using Microsoft.Web.WebView2.WinForms;

internal static class Program {
    static string status;
    static bool ready;
    static bool uiReady;
    static string lastError;
    static string exitAction;
    static void Record(string phase, string error = null) {
        if (error != null) lastError=error;
        if (String.IsNullOrEmpty(status)) return;
        var item = new Dictionary<string, object> {
            { "phase", phase }, { "ready", ready }, { "ui_ready", uiReady }, { "error", lastError }, {"exit_action",exitAction},
            { "pid", System.Diagnostics.Process.GetCurrentProcess().Id },
            { "time", DateTime.UtcNow.ToString("o") }
        };
        try { File.WriteAllText(status, new JavaScriptSerializer().Serialize(item)); } catch {}
    }
    [STAThread]
    static int Main(string[] args) {
        status = args.Length > 1 ? args[1] : null;
        Record("starting");
        try {
            if (args.Length < 1) throw new ArgumentException("Missing local workbench URL");
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            var form = new Form { Text = "Economy-guy 财税工作台 · 提交版", Width = 1440,
                Height = 900, MinimumSize = new System.Drawing.Size(1100,700),
                StartPosition = FormStartPosition.CenterScreen };
            var web = new WebView2 { Dock = DockStyle.Fill };
            form.Controls.Add(web);
            bool closing=false, checkingClose=false;
            form.FormClosing += async delegate(object sender, FormClosingEventArgs e) {
                if (closing || !ready) return;
                e.Cancel=true;
                if (checkingClose) return;
                checkingClose=true;
                try {
                    using(var client=new WebClient()) {
                        client.Encoding=Encoding.UTF8;
                        client.Headers["X-GUI-Token"]=args[2];
                        var serializer=new JavaScriptSerializer();
                        var state=serializer.Deserialize<Dictionary<string,object>>(
                            await client.DownloadStringTaskAsync(new Uri(new Uri(args[0]),"/api/snapshot")));
                        var snapshot=(Dictionary<string,object>)state["snapshot"];
                        client.Headers["Content-Type"]="application/json";
                        await client.UploadStringTaskAsync(new Uri(new Uri(args[0]),"/api/close"),"POST",
                            serializer.Serialize(new Dictionary<string,object>{{"context",snapshot["context"]}}));
                    }
                    closing=true;form.Close();
                } catch(Exception) {
                    exitAction=null;
                    MessageBox.Show("请先处理运行中的请求、预览、待补或未知提交；可在页面暂缓或取消后再关闭。", "当前事项尚未收口");
                } finally { checkingClose=false; }
            };
            form.Load += async delegate {
                try {
                    Record("initializing-webview2");
                    string cache = Path.Combine(Environment.GetFolderPath(
                        Environment.SpecialFolder.LocalApplicationData),"Economy-guy","native-webview2");
                    var environment = await CoreWebView2Environment.CreateAsync(null,cache,null);
                    await web.EnsureCoreWebView2Async(environment);
                    web.CoreWebView2.Settings.AreDefaultContextMenusEnabled=false;
                    web.CoreWebView2.Settings.IsStatusBarEnabled=false;
                    web.CoreWebView2.Settings.IsPasswordAutosaveEnabled=false;
                    web.CoreWebView2.Settings.IsGeneralAutofillEnabled=false;
                    web.CoreWebView2.WebMessageReceived += async delegate(object sender, CoreWebView2WebMessageReceivedEventArgs e) {
                        try {
                            var message=new JavaScriptSerializer().Deserialize<Dictionary<string,object>>(e.WebMessageAsJson);
                            if (new Uri(e.Source).GetLeftPart(UriPartial.Authority)==new Uri(args[0]).GetLeftPart(UriPartial.Authority)
                                    && message.ContainsKey("kind") && (string)message["kind"]=="ui-ready") {
                                uiReady=true; Record("ui-ready");
                            }
                            if(new Uri(e.Source).GetLeftPart(UriPartial.Authority)!=new Uri(args[0]).GetLeftPart(UriPartial.Authority))return;
                            string kind=message.ContainsKey("kind")?(string)message["kind"]:"";
                            if(kind=="pick-workbook") {
                                using(var picker=new OpenFileDialog()) {
                                    picker.Title="选择已有本机账簿（不改变当前绑定）";
                                    picker.Filter="SQLite账簿|*.sqlite3;*.sqlite;*.db|所有文件|*.*";
                                    if(picker.ShowDialog(form)==DialogResult.OK) {
                                        using(var client=new WebClient()) {
                                            client.Encoding=Encoding.UTF8;client.Headers["X-Native-Token"]=args[3];
                                            client.Headers["Content-Type"]="application/json";
                                            var payload=new Dictionary<string,object>{{"path",picker.FileName},{"context",message["context"]}};
                                            await client.UploadStringTaskAsync(new Uri(new Uri(args[0]),"/api/native_workbook"),"POST",new JavaScriptSerializer().Serialize(payload));
                                        }
                                        await web.CoreWebView2.ExecuteScriptAsync("refresh()");
                                    }
                                }
                            }
                            if(kind=="advanced") {
                                if(MessageBox.Show("将关闭当前GUI并进入原高级控制台。当前待补、预览或未知提交必须先处理。继续？","原高级入口",MessageBoxButtons.OKCancel)==DialogResult.OK) {
                                    exitAction="advanced";form.Close();
                                }
                            }
                            if(kind=="sign-out")form.Close();
                        } catch(Exception error) { MessageBox.Show(error.Message,"本机操作未完成"); }
                    };
                    web.CoreWebView2.NavigationCompleted += delegate(object sender, CoreWebView2NavigationCompletedEventArgs e) {
                        if (e.IsSuccess) { ready=true; Record("ready"); }
                        else { Record("navigation-error",e.WebErrorStatus.ToString()); }
                    };
                    web.CoreWebView2.Navigate(args[0]);
                } catch (Exception error) {
                    Record("failed",error.Message); Environment.ExitCode=2;
                    MessageBox.Show(error.Message,"内嵌窗口启动失败"); form.Close();
                }
            };
            form.FormClosed += delegate { Record("closed"); };
            Application.Run(form);
            return ready ? 0 : 2;
        } catch(Exception error) {
            Record("failed",error.Message); MessageBox.Show(error.Message,"内嵌窗口启动失败"); return 2;
        }
    }
}
