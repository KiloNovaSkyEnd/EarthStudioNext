using System.Diagnostics;
using Microsoft.UI.Xaml;
using Microsoft.UI.Xaml.Controls;

namespace EarthStudio.App.UI;

sealed class AccountsView
{
    public UIElement Content { get; }
    public event Action<string, string>? ConnectRequested;
    public event Action? ContinueRequested;
    private readonly TextBox key = new() { Header = "Consumer Key", MaxLength = 1024 };
    private readonly PasswordBox secret = new() { Header = "Consumer Secret", MaxLength = 2048 };
    private readonly TextBlock state = Ui.Text("尚未检查本机凭据", 14, true);
    private readonly Button connect;
    public AccountsView()
    {
        connect = Ui.Button("验证并连接 EUMETSAT", () => ConnectRequested?.Invoke(key.Text.Trim(), secret.Password), true);
        Content = Ui.Scroll(Ui.Column(Ui.Text("1 · 数据账户与来源", 28),
            Ui.Text("连接一次，以后由后台引擎使用；密钥不进入项目文件或任务日志。", muted: true),
            Ui.Card(Ui.Column(Ui.Text("NOAA 公共存档", 20), Ui.Text("GOES 与公开日葵存档无需填写账户；实际历史可用性以目录检查为准。", muted: true))),
            Ui.Card(Ui.Column(Ui.Text("EUMETSAT", 20),
                Ui.Text("欧洲、非洲和印度洋方向。需要API密钥及对应数据许可；这里填写的不是网站登录密码。", muted: true),
                Ui.Button("注册 / 获取官方 API 密钥", () => Process.Start(new ProcessStartInfo("https://api.eumetsat.int/api-key/") { UseShellExecute = true })),
                key, secret, connect, state,
                Ui.Text("仅在认证成功后，以 Windows 当前用户 DPAPI 加密保存。已有本机凭据会复用，不显示密钥。", 12, true))),
            Ui.Button("下一步：选择单帧 / 时间序列",()=>ContinueRequested?.Invoke(),true),
            Ui.Text("仅用公开向日葵/GOES时无需填写EUMETSAT账户，可直接继续。",13,true)));
    }
    public void SetStatus(string message) => state.Text = message;
    public void ClearSecret() => secret.Password = "";
    public void SetBusy(bool busy) { connect.IsEnabled = !busy; key.IsEnabled = !busy; secret.IsEnabled = !busy; }
}
